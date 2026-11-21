"""Stock rules without Qt: balance, catalog, bulk add, parser, futuro, finalizing, duplicates."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dtf_manager.models.stock import LineDecision
from dtf_manager.services.sqlite_database import DTFDatabase, STOCK_BACKUP_SUFFIX
from dtf_manager.services.stock_parser import parse_variation
from dtf_manager.services.stock_service import StockError
from tests.stock_fakes import (
    do_import, future_of, ids, make_order, make_service, stock_of,
)

SIZES = {"p", "m", "g", "gg"}


class ParserTests(unittest.TestCase):
    def parse(self, text):
        return parse_variation(text, SIZES)

    def test_formats_found_in_real_spreadsheets(self):
        cases = {
            "Preta,G": ("preta", ("g",)),
            "PRETO,M": ("preto", ("m",)),
            "Preto,M - G": ("preto", ("m", "g")),
            "G - GG,Preto": ("preto", ("g", "gg")),
            "Kit Bege,P - G": ("bege", ("p", "g")),
            "Kit Preto, GG - GG": ("preto", ("gg", "gg")),
            "Marrom - Estampa Preta,P - G": ("marrom", ("p", "g")),
            "  Preta  ,  G ": ("preta", ("g",)),
        }
        for text, (color, sizes) in cases.items():
            with self.subTest(text):
                parsed = self.parse(text)
                self.assertEqual((parsed.color, parsed.sizes), (color, sizes))
                self.assertEqual(parsed.color_state, "found")

    def test_no_color_and_ambiguous(self):
        self.assertEqual(self.parse("P - M").color_state, "missing")
        self.assertEqual(self.parse("GG").sizes, ("gg",))
        self.assertEqual(self.parse("Marrom - Preto,M").color_state, "ambiguous")
        self.assertFalse(self.parse("Preto").sizes_ok)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.service, self.path = make_service()

    def test_initial_stock_is_zero_for_every_color_and_size(self):
        snap = self.service.snapshot()
        self.assertEqual([c.name for c in snap.colors], ["Preta", "Marrom", "Bege", "Branca"])
        self.assertEqual([s.name for s in snap.sizes], ["P", "M", "G", "GG"])
        self.assertTrue(all(v == 0 for v in snap.stock.values()))
        self.assertFalse(snap.has_future)

    def test_duplicate_color_or_size_is_refused_ignoring_case_and_accents(self):
        for name in ("preta", " PRETA ", "préta"):
            with self.assertRaises(StockError):
                self.service.add_color(name)
        with self.assertRaises(StockError):
            self.service.add_size("gg")
        with self.assertRaises(StockError):
            self.service.add_color("   ")
        self.assertEqual(self.service.add_color("Azul").name, "Azul")
        self.assertEqual(self.service.add_size("XG").name, "XG")
        self.assertEqual(len(self.service.snapshot().colors), 5)

    def test_manual_edit_validates_and_logs(self):
        colors, sizes = ids(self.service)
        for bad in ("-1", "abc", "1.5", ""):
            with self.assertRaises(StockError):
                self.service.set_stock(colors["Preta"], sizes["M"], bad)
        self.assertTrue(self.service.set_stock(colors["Preta"], sizes["M"], "7"))
        self.assertFalse(self.service.set_stock(colors["Preta"], sizes["M"], "7"))
        self.assertEqual(stock_of(self.service, "Preta", "M"), 7)
        move = self.service.movements()[0]
        self.assertEqual((move.kind, move.color, move.size, move.before, move.after),
                         ("ajuste_manual", "Preta", "M", 0, 7))

    def test_bulk_add_all_colors_and_one_color_selected_sizes(self):
        colors, sizes = ids(self.service)
        self.assertEqual(self.service.bulk_add(2), 16)
        self.assertEqual(stock_of(self.service, "Bege", "GG"), 2)
        self.service.bulk_add(3, colors["Preta"], [sizes["P"], sizes["G"]])
        self.assertEqual(stock_of(self.service, "Preta", "P"), 5)
        self.assertEqual(stock_of(self.service, "Preta", "M"), 2)
        self.assertEqual(stock_of(self.service, "Marrom", "P"), 2)
        with self.assertRaises(StockError):
            self.service.bulk_add(0)
        kinds = {m.kind for m in self.service.movements()}
        self.assertEqual(kinds, {"adicao_em_massa"})

    def test_persists_after_reopening(self):
        colors, sizes = ids(self.service)
        self.service.set_stock(colors["Bege"], sizes["G"], "4")
        self.service.add_color("Azul")
        reopened, _ = make_service(self.path)
        self.assertEqual(stock_of(reopened, "Bege", "G"), 4)
        self.assertIn("Azul", [c.name for c in reopened.snapshot().colors])
        self.assertEqual(len(reopened.movements()), 1)


class BackupTests(unittest.TestCase):
    def test_existing_database_is_copied_once_before_the_stock_migration(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / "dtf_manager.db"
        legacy = sqlite3.connect(path)
        legacy.execute("CREATE TABLE processed_orders(order_number TEXT PRIMARY KEY, "
                       "fingerprint TEXT, processed_at TEXT)")
        legacy.execute("INSERT INTO processed_orders VALUES('1','f','t')")
        legacy.commit()
        legacy.close()
        DTFDatabase(path)
        backup = folder / (path.name + STOCK_BACKUP_SUFFIX)
        self.assertTrue(backup.exists())
        copy = sqlite3.connect(backup)
        tables = {r[0] for r in copy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("stock_colors", tables)          # copy of the original state
        self.assertEqual(copy.execute("SELECT COUNT(*) FROM processed_orders").fetchone()[0], 1)
        copy.close()
        stamp = backup.stat().st_mtime_ns
        DTFDatabase(path)                                  # second start: no new copy
        self.assertEqual(backup.stat().st_mtime_ns, stamp)

    def test_new_installation_has_nothing_to_back_up(self):
        folder = Path(tempfile.mkdtemp())
        DTFDatabase(folder / "dtf_manager.db")
        self.assertFalse((folder / ("dtf_manager.db" + STOCK_BACKUP_SUFFIX)).exists())


class FutureTests(unittest.TestCase):
    def setUp(self):
        self.service, self.path = make_service()
        self.colors, self.sizes = ids(self.service)

    def test_balance_is_stock_minus_future(self):
        self.service.bulk_add(5)
        do_import(self.service, [make_order("A", ("Preta,G", 3))])
        snap = self.service.snapshot()
        cell = (self.colors["Preta"], self.sizes["G"])
        self.assertEqual(snap.stock[cell] - snap.future[cell], 2)
        do_import(self.service, [make_order("B", ("Preta,G", 8))])
        snap = self.service.snapshot()
        self.assertEqual(snap.stock[cell] - snap.future[cell], -3)
        row = snap.separation[0]
        self.assertEqual((row.needed, row.available, row.missing), (8, 5, 3))

    def test_kit_counts_one_shirt_per_size_and_multiplies_by_quantity(self):
        do_import(self.service, [
            make_order("A", ("Preto,M - G", 3), ("Kit Preto, GG - GG", 1),
                       ("Kit Bege,P - G", 2, "SKU-2"), ("G - GG,Preta", 1, "SKU-3")),
        ])
        self.assertEqual(future_of(self.service, "Preta", "M"), 3)
        self.assertEqual(future_of(self.service, "Preta", "G"), 4)      # 3 + 1 (G - GG)
        self.assertEqual(future_of(self.service, "Preta", "GG"), 3)     # M-M style: 2 + 1
        self.assertEqual(future_of(self.service, "Bege", "P"), 2)
        self.assertEqual(future_of(self.service, "Bege", "G"), 2)

    def test_each_import_replaces_the_future(self):
        do_import(self.service, [make_order("A", ("Preta,G", 3))])
        do_import(self.service, [make_order("B", ("Bege,M", 2))], file_hash="h2")
        self.assertEqual(future_of(self.service, "Preta", "G"), 0)
        self.assertEqual(future_of(self.service, "Bege", "M"), 2)
        kinds = [(m.kind, m.scope) for m in self.service.movements()]
        self.assertEqual(kinds.count(("importacao", "futuro")), 3)

    def test_print_color_is_never_the_shirt_color(self):
        do_import(self.service, [make_order("A", ("Marrom - Estampa Preta,P - G", 2))])
        self.assertEqual(future_of(self.service, "Marrom", "P"), 2)
        self.assertEqual(future_of(self.service, "Preta", "P"), 0)

    def test_unrecognized_items_are_left_out_and_become_validation_lines(self):
        orders = [make_order("A", ("Preta,G", 1), ("Verde,G", 4, "S-V"), ("P - M", 2, "S-NC"),
                             ("Marrom - Preto,M", 1, "S-AMB"))]
        result, prep = do_import(self.service, orders)
        self.assertEqual(future_of(self.service, "Preta", "G"), 1)
        self.assertEqual(sum(self.service.snapshot().future.values()), 1)
        self.assertEqual(len(prep.lines), 3)
        self.assertEqual(result.pending, 4 + 4 + 1)                    # 2 shirts x 2 sizes
        self.assertEqual(len(self.service.snapshot().pending), 3)

    def test_repeated_identical_lines_are_summed_and_reported(self):
        order = make_order("A", ("Preta,G", 2), ("Preta,G", 2))
        result, _ = do_import(self.service, [order])
        self.assertEqual(future_of(self.service, "Preta", "G"), 4)
        self.assertEqual(result.repeated_lines, 1)

    def test_sku_names_the_color_when_the_variation_has_none(self):
        do_import(self.service, [make_order("A", ("P - M", 1, "SOLO - DOCTOR DOOM-PRETO-M"))])
        self.assertEqual(future_of(self.service, "Preta", "P"), 1)
        self.assertEqual(future_of(self.service, "Preta", "M"), 1)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.service, _ = make_service()
        self.colors, self.sizes = ids(self.service)

    def orders(self):
        return [make_order("A", ("P - M", 2, "SKU-X"), ("GG", 1, "SKU-X")),
                make_order("B", ("P - M", 3, "SKU-X"))]

    def test_lines_are_grouped_by_sku_with_total_shirts(self):
        prep = self.service.prepare_import(self.orders())
        self.assertEqual(len(prep.lines), 1)
        line = prep.lines[0]
        self.assertTrue(line.needs_color and not line.needs_size)
        self.assertEqual(line.shirts, 2 * 2 + 1 + 3 * 2)

    def test_nothing_to_validate_when_everything_is_recognized(self):
        prep = self.service.prepare_import([make_order("A", ("Preta,G", 1))])
        self.assertEqual(prep.lines, [])

    def test_decision_by_sku_is_remembered_for_the_next_import(self):
        prep = self.service.prepare_import(self.orders())
        key = prep.lines[0].key
        self.service.commit_import(
            prep, {key: LineDecision(color=self.colors["Bege"], remember=True)}, "a.xlsx", "h1")
        self.assertEqual(future_of(self.service, "Bege", "P"), 5)
        self.assertEqual(future_of(self.service, "Bege", "GG"), 1)
        again = self.service.prepare_import(self.orders())
        self.assertEqual(again.lines, [])
        self.assertEqual(sum(again.totals.values()), 5 * 2 + 1)

    def test_not_remembering_asks_again(self):
        prep = self.service.prepare_import(self.orders())
        self.service.commit_import(
            prep, {prep.lines[0].key: LineDecision(color=self.colors["Bege"], remember=False)},
            "a.xlsx", "h1")
        self.assertEqual(len(self.service.prepare_import(self.orders()).lines), 1)

    def test_item_without_sku_is_never_remembered(self):
        orders = [make_order("A", ("P - M", 1, ""))]
        prep = self.service.prepare_import(orders)
        self.service.commit_import(
            prep, {prep.lines[0].key: LineDecision(color=self.colors["Bege"])}, "a.xlsx", "h1")
        self.assertEqual(future_of(self.service, "Bege", "P"), 1)
        self.assertEqual(self.service.repository.sku_colors(), {})
        self.assertEqual(len(self.service.prepare_import(orders).lines), 1)

    def test_variation_text_alone_is_never_saved_as_a_mapping(self):
        prep = self.service.prepare_import(self.orders())
        self.service.commit_import(
            prep, {prep.lines[0].key: LineDecision(color=self.colors["Bege"])}, "a.xlsx", "h1")
        other_sku = [make_order("Z", ("P - M", 1, "SKU-OTHER"))]
        self.assertEqual(len(self.service.prepare_import(other_sku).lines), 1)

    def test_new_color_created_from_the_window_and_unknown_text_becomes_an_alias(self):
        orders = [make_order("A", ("Verde,G", 2, "SKU-V"))]
        prep = self.service.prepare_import(orders)
        self.service.commit_import(prep, {prep.lines[0].key: LineDecision(color="Verde")},
                                   "a.xlsx", "h1")
        self.assertIn("Verde", ids(self.service)[0])
        self.assertEqual(future_of(self.service, "Verde", "G"), 2)
        self.assertEqual(self.service.prepare_import(orders).lines, [])

    def test_size_can_be_set_for_one_or_two_shirts(self):
        orders = [make_order("A", ("Preta", 2, "SKU-S"))]
        prep = self.service.prepare_import(orders)
        self.assertTrue(prep.lines[0].needs_size and not prep.lines[0].needs_color)
        self.service.commit_import(
            prep, {prep.lines[0].key: LineDecision(sizes=(self.sizes["M"], self.sizes["G"]))},
            "a.xlsx", "h1")
        self.assertEqual(future_of(self.service, "Preta", "M"), 2)
        self.assertEqual(future_of(self.service, "Preta", "G"), 2)

    def test_pending_lines_stay_out_of_the_total_and_are_listed(self):
        orders = [make_order("A", ("Preta,G", 1), ("P - M", 2, "SKU-X"))]
        result, _ = do_import(self.service, orders)
        snap = self.service.snapshot()
        self.assertEqual(sum(snap.future.values()), 1)
        self.assertEqual([p.quantity for p in snap.pending], [4])
        self.assertEqual(result.pending, 4)


class FinalizeTests(unittest.TestCase):
    def setUp(self):
        self.service, self.path = make_service()

    def test_nothing_to_finalize_without_future(self):
        self.assertIsNone(self.service.finalize())
        self.assertIsNone(self.service.finalize_summary())

    def test_deducts_zeroes_future_and_logs_without_shortage(self):
        self.service.bulk_add(10)
        do_import(self.service, [make_order("A", ("Preta,G", 3), ("Bege,M", 1))])
        self.service.set_separated(*[ids(self.service)[0]["Preta"], ids(self.service)[1]["G"]], True)
        summary = self.service.finalize_summary()
        self.assertEqual(summary.shortages, ())
        self.service.finalize()
        self.assertEqual(stock_of(self.service, "Preta", "G"), 7)
        self.assertEqual(stock_of(self.service, "Bege", "M"), 9)
        snap = self.service.snapshot()
        self.assertFalse(snap.has_future)
        self.assertEqual(snap.separation, ())
        last = [m for m in self.service.movements() if m.kind == "finalizacao"]
        self.assertEqual(len(last), 2)
        self.assertTrue(all(m.before - m.after > 0 for m in last))

    def test_shortage_clamps_to_zero_and_is_logged(self):
        colors, sizes = ids(self.service)
        self.service.set_stock(colors["Preta"], sizes["G"], "2")
        do_import(self.service, [make_order("A", ("Preta,G", 5))])
        summary = self.service.finalize_summary()
        self.assertEqual([(r.color, r.size, r.shortage) for r in summary.shortages],
                         [("Preta", "G", 3)])
        self.assertTrue(summary.needs_acknowledgement)
        self.service.finalize()
        self.assertEqual(stock_of(self.service, "Preta", "G"), 0)
        move = [m for m in self.service.movements() if m.kind == "finalizacao"][0]
        self.assertEqual((move.before, move.after), (2, 0))
        self.assertIn("faltaram 3", move.note)

    def test_second_finalize_does_nothing(self):
        self.service.bulk_add(5)
        do_import(self.service, [make_order("A", ("Preta,G", 1))])
        self.assertIsNotNone(self.service.finalize())
        self.assertIsNone(self.service.finalize())
        self.assertEqual(stock_of(self.service, "Preta", "G"), 4)

    def test_pending_items_are_reported_and_cleared(self):
        do_import(self.service, [make_order("A", ("Preta,G", 1), ("P - M", 1, "S"))])
        summary = self.service.finalize_summary()
        self.assertEqual(summary.pending, 2)
        self.assertTrue(summary.needs_acknowledgement)
        self.service.finalize()
        self.assertEqual(self.service.snapshot().pending, ())

    def test_finalized_state_survives_reopening(self):
        self.service.bulk_add(5)
        do_import(self.service, [make_order("A", ("Preta,G", 2))])
        self.service.finalize()
        reopened, _ = make_service(self.path)
        self.assertEqual(stock_of(reopened, "Preta", "G"), 3)
        self.assertFalse(reopened.snapshot().has_future)
        self.assertIn("A", reopened.finalized_info(["A", "B"]))


class DuplicateProtectionTests(unittest.TestCase):
    def setUp(self):
        self.service, _ = make_service()
        self.service.bulk_add(50)

    def orders(self, prefix="P", n=10, variation="Preta,G"):
        return [make_order(f"{prefix}{i}", (variation, 1)) for i in range(n)]

    def numbers(self, orders):
        return [o.platform_order_number for o in orders]

    def test_new_spreadsheet_gives_no_warning(self):
        self.assertIsNone(self.service.check_duplicate("h", self.numbers(self.orders())))
        do_import(self.service, self.orders(), file_hash="h")
        self.assertIsNone(self.service.check_duplicate("h2", self.numbers(self.orders("N"))))

    def test_same_file_is_detected_by_hash(self):
        do_import(self.service, self.orders(), file_hash="h")
        info = self.service.check_duplicate("h", self.numbers(self.orders("Q")))   # other numbers
        self.assertTrue(info.same_file)
        self.assertFalse(info.finalized)

    def test_same_orders_with_another_file_name_and_hash(self):
        do_import(self.service, self.orders(), file_name="a.xlsx", file_hash="h")
        info = self.service.check_duplicate("other", self.numbers(self.orders()))
        self.assertFalse(info.same_file)
        self.assertEqual(info.overlap, 1.0)
        self.assertEqual(info.new_orders, ())
        self.assertFalse(info.mixed)

    def test_mixed_spreadsheet_over_the_limit_offers_only_new(self):
        do_import(self.service, self.orders(n=10), file_hash="h")
        mixed = self.numbers(self.orders(n=10)) + ["NEW1"]          # 10 of 11 = 91%
        info = self.service.check_duplicate("other", mixed)
        self.assertTrue(info.mixed)
        self.assertEqual(info.new_orders, ("NEW1",))
        below = self.numbers(self.orders(n=8)) + ["N1", "N2"]       # 80% is not more than 80%
        self.assertIsNone(self.service.check_duplicate("other", below))

    def test_previous_finalized_state_is_reported(self):
        do_import(self.service, self.orders(), file_hash="h")
        self.service.finalize()
        info = self.service.check_duplicate("h", self.numbers(self.orders()))
        self.assertTrue(info.finalized)

    def test_finalized_orders_are_excluded_from_the_future_by_default(self):
        old = self.orders("O", 3)
        do_import(self.service, old, file_hash="h")
        self.service.finalize()
        new = [make_order("NEW", ("Bege,M", 2))]
        loaded = old + new
        finalized = self.service.finalized_info(self.numbers(loaded))
        self.assertEqual(set(finalized), set(self.numbers(old)))
        do_import(self.service, loaded, file_hash="h2", excluded=finalized)
        self.assertEqual(future_of(self.service, "Preta", "G"), 0)
        self.assertEqual(future_of(self.service, "Bege", "M"), 2)
        self.service.finalize()
        self.assertEqual(stock_of(self.service, "Preta", "G"), 47)      # only deducted once

    def test_including_finalized_orders_again_counts_them(self):
        old = self.orders("O", 3)
        do_import(self.service, old, file_hash="h")
        self.service.finalize()
        do_import(self.service, old, file_hash="h2")                    # nothing excluded
        self.assertEqual(future_of(self.service, "Preta", "G"), 3)

    def test_orders_already_in_a_previous_import_stay_known(self):
        do_import(self.service, self.orders("K", 2), file_hash="h")
        self.assertEqual(self.service.known_orders(), {"K0", "K1"})


if __name__ == "__main__":
    unittest.main()
