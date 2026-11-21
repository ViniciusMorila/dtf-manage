"""Art stock rules without Qt: listing, one record per file, copy counting, futuro, move."""
import unittest

from dtf_manager.services.art_duplicates import find_identical
from dtf_manager.services.art_folder_listing import list_art_files
from dtf_manager.services.print_plan_service import (
    PrintPlanValidationError, build_dtf_print_plan, count_art_copies,
)
from dtf_manager.services.stock_service import StockError
from tests.art_fakes import (
    linked_item, make_art, make_art_service, make_folder, make_item, make_order, row_of, sync,
)


class ListingTests(unittest.TestCase):
    def test_lists_every_art_of_the_folder_recursively_without_decoding_them(self):
        folder = make_folder()
        make_art(folder, "a.png")
        make_art(folder, "sub/b.JPG")
        make_art(folder, "sub/deep/c.webp")
        (folder / "broken.png").write_bytes(b"not an image")        # listed: no decoding here
        (folder / "notes.txt").write_text("x")
        (folder / "Thumbs.db").write_bytes(b"x")
        (folder / ".hidden.png").write_bytes(b"x")
        (folder / "~tmp.png").write_bytes(b"x")
        names = [f.relative_path for f in list_art_files(folder)]
        self.assertEqual(names, ["a.png", "broken.png", "sub/b.JPG", "sub/deep/c.webp"])

    def test_the_stock_list_has_all_the_arts_starting_at_zero(self):
        folder = make_folder()
        for name in ("a.png", "sub/b.png", "c.png"):
            make_art(folder, name)
        arts, _, _ = make_art_service()
        sync(arts, folder)
        snap = arts.snapshot()
        self.assertEqual([r.relative_path for r in snap.rows], ["a.png", "c.png", "sub/b.png"])
        self.assertTrue(all(r.stock == 0 and r.future == 0 for r in snap.rows))
        self.assertFalse(snap.has_future)


class CountTests(unittest.TestCase):
    def test_same_formula_as_the_roll_for_kits_quantity_and_sizes(self):
        folder = make_folder()
        a, b = make_art(folder, "a.png"), make_art(folder, "b.png")
        orders = [
            make_order("1", linked_item("1", [a, b], quantity=3, copies=1)),         # kit: 2 arts x 3
            make_order("2", linked_item("2", a, quantity=2, copies=2, width=10, height=10)),
            make_order("3", linked_item("3", a, quantity=1, copies=1, width=20, height=20)),
        ]
        plan = build_dtf_print_plan(orders, validate_files=False)
        count = count_art_copies(orders)
        self.assertEqual(sum(c.copies for c in count.arts.values()), plan.total_print_copies)
        by_file = {}
        for art in plan.arts:                      # the roll keeps sizes apart; the stock sums them
            by_file[art.file_name] = by_file.get(art.file_name, 0) + art.total_copies
        self.assertEqual({c.file_name: c.copies for c in count.arts.values()}, by_file)
        self.assertEqual(by_file, {"a.png": 3 + 4 + 1, "b.png": 3})
        self.assertEqual(count.unlinked_items, 0)

    def test_items_without_a_link_are_skipped_and_counted_instead_of_raising(self):
        folder = make_folder()
        a = make_art(folder, "a.png")
        orders = [make_order("1", linked_item("1", a, quantity=2), make_item("1", "Preta,G", 5, "X"))]
        with self.assertRaises(PrintPlanValidationError):
            build_dtf_print_plan(orders, validate_files=False)
        count = count_art_copies(orders)
        self.assertEqual((count.unlinked_items, count.item_count), (1, 2))
        self.assertEqual([c.copies for c in count.arts.values()], [2])


class FutureTests(unittest.TestCase):
    def setUp(self):
        self.folder = make_folder()
        self.a = make_art(self.folder, "a.png")
        self.b = make_art(self.folder, "sub/b.png")
        self.arts, self.stock, self.path = make_art_service()
        sync(self.arts, self.folder)

    def recalc(self, orders, **kwargs):
        return self.arts.replace_future(count_art_copies(orders), **kwargs)

    def test_one_row_per_file_summing_skus_sizes_and_orders(self):
        orders = [make_order("1", linked_item("1", self.a, 2, "SKU-A", "Preta,G"),
                             linked_item("1", self.a, 1, "SKU-B", "Preto,M - G")),
                  make_order("2", linked_item("2", self.a, 4, "SKU-C", "Branca,P"))]
        self.recalc(orders)
        snap = self.arts.snapshot()
        self.assertEqual(len([r for r in snap.rows if r.name == "a.png"]), 1)
        self.assertEqual(row_of(self.arts, "a.png").future, 7)
        self.assertEqual(len(snap.rows), 2)                           # no row per SKU/size
        self.assertEqual([(s.name, s.needed) for s in snap.separation], [("a.png", 7)])

    def test_balance_is_stock_minus_future_and_shortage_never_negative(self):
        art = row_of(self.arts, "a.png")
        self.arts.set_stock(art.art_id, "5")
        self.recalc([make_order("1", linked_item("1", self.a, 8))])
        row = row_of(self.arts, "a.png")
        self.assertEqual((row.stock, row.future, row.balance, row.shortage), (5, 8, -3, 3))
        self.recalc([make_order("1", linked_item("1", self.a, 2))])
        row = row_of(self.arts, "a.png")
        self.assertEqual((row.balance, row.shortage), (3, 0))

    def test_each_recalculation_replaces_the_future(self):
        self.recalc([make_order("1", linked_item("1", self.a, 3))])
        self.recalc([make_order("2", linked_item("2", self.b, 2))])
        self.assertEqual(row_of(self.arts, "a.png").future, 0)
        self.assertEqual(row_of(self.arts, "sub/b.png").future, 2)
        self.recalc([])
        self.assertFalse(self.arts.snapshot().has_future)

    def test_only_the_net_result_is_logged_and_unchanged_recalculations_log_nothing(self):
        orders = [make_order("1", linked_item("1", self.a, 3), linked_item("1", self.a, 1, "S2"),
                             linked_item("1", self.b, 2, "S3"))]
        self.assertEqual(self.recalc(orders), 2)                      # a and b: one line each
        moves = [m for m in self.stock.movements() if m.produto == "estampa"]
        self.assertEqual(sorted((m.color, m.before, m.after) for m in moves),
                         [("a.png", 0, 4), ("sub/b.png", 0, 2)])
        self.assertTrue(all(m.kind == "importacao" and m.scope == "futuro" for m in moves))
        self.assertEqual(self.recalc(orders), 0)
        self.assertEqual(len([m for m in self.stock.movements() if m.produto == "estampa"]), 2)

    def test_separated_marks_survive_a_recalculation_and_reset_on_a_new_import(self):
        orders = [make_order("1", linked_item("1", self.a, 3))]
        self.recalc(orders)
        art = row_of(self.arts, "a.png")
        self.arts.set_separated(art.art_id, True)
        self.recalc(orders + [make_order("2", linked_item("2", self.a, 1))])
        self.assertTrue(self.arts.snapshot().separation[0].separated)
        self.recalc(orders, reset_marks=True)
        self.assertFalse(self.arts.snapshot().separation[0].separated)

    def test_unlinked_items_are_remembered_for_the_notice(self):
        orders = [make_order("1", linked_item("1", self.a, 1), make_item("1", "Preta,G", 1, "X"),
                             make_item("1", "Preta,M", 1, "Y"))]
        self.recalc(orders)
        self.assertEqual(self.arts.snapshot().unlinked_items, 2)
        self.recalc([make_order("1", linked_item("1", self.a, 1))])
        self.assertEqual(self.arts.snapshot().unlinked_items, 0)

    def test_art_outside_the_folder_is_listed_with_its_own_mark(self):
        elsewhere = make_art(make_folder(), "outside.png")
        self.recalc([make_order("1", linked_item("1", elsewhere, 2))])
        row = row_of(self.arts, "outside.png") or [r for r in self.arts.snapshot().rows
                                                   if r.outside_folder][0]
        self.assertTrue(row.outside_folder)
        self.assertFalse(row.missing)
        self.assertEqual(row.future, 2)
        self.assertTrue(row.relative_path.casefold().endswith("outside.png"))
        sync(self.arts, self.folder)                                  # refresh keeps it
        self.assertTrue([r for r in self.arts.snapshot().rows if r.outside_folder])

    def test_case_and_slash_variants_of_the_same_file_are_one_record(self):
        upper = str(self.a).upper().replace("\\", "/")
        orders = [make_order("1", linked_item("1", self.a, 1), linked_item("1", upper, 2, "S2"))]
        self.recalc(orders)
        self.assertEqual(row_of(self.arts, "a.png").future, 3)
        self.assertEqual(len(self.arts.snapshot().rows), 2)


class MissingFileTests(unittest.TestCase):
    def test_a_file_that_vanished_keeps_its_stock_flagged_and_is_never_deleted(self):
        folder = make_folder()
        a, b = make_art(folder, "a.png"), make_art(folder, "b.png")
        arts, stock, path = make_art_service()
        sync(arts, folder)
        arts.set_stock(row_of(arts, "a.png").art_id, "9")
        a.unlink()
        b.unlink()
        sync(arts, folder)
        kept = row_of(arts, "a.png")
        self.assertTrue(kept.missing)
        self.assertEqual(kept.stock, 9)
        self.assertIsNone(row_of(arts, "b.png"))                       # nothing registered: hidden
        self.assertEqual(len(arts.repository.files()), 2)              # but still in the database
        make_art(folder, "a.png")                                      # it comes back
        sync(arts, folder)
        self.assertFalse(row_of(arts, "a.png").missing)
        self.assertEqual(row_of(arts, "a.png").stock, 9)

    def test_changing_the_folder_refreshes_the_list_and_flags_the_old_records(self):
        first, second = make_folder(), make_folder()
        make_art(first, "x.png")
        make_art(second, "y.png")
        arts, _, _ = make_art_service()
        sync(arts, first)
        arts.set_stock(row_of(arts, "x.png").art_id, "4")
        sync(arts, second)
        rows = {r.relative_path: r for r in arts.snapshot().rows}
        self.assertEqual(set(rows), {"x.png", "y.png"})
        self.assertTrue(rows["x.png"].missing)
        self.assertFalse(rows["y.png"].missing)


class MoveTests(unittest.TestCase):
    def setUp(self):
        self.folder = make_folder()
        self.arts, self.stock, _ = make_art_service()
        old = make_art(self.folder, "old/logo.png")
        sync(self.arts, self.folder)
        self.arts.set_stock(row_of(self.arts, "old/logo.png").art_id, "6")
        old.rename(self.folder / "logo.png")                           # moved out of its folder
        make_art(self.folder, "other.png")
        sync(self.arts, self.folder)

    def test_suggestions_pair_the_same_file_name_and_nothing_moves_by_itself(self):
        suggestions = self.arts.suggest_matches()
        self.assertEqual([(s.from_path, s.to_path, s.stock) for s in suggestions],
                         [("old/logo.png", "logo.png", 6)])
        self.assertEqual(row_of(self.arts, "old/logo.png").stock, 6)       # still untouched
        self.assertEqual(row_of(self.arts, "logo.png").stock, 0)
        self.assertTrue(self.arts.has_missing_with_stock())

    def test_ambiguous_names_are_not_suggested(self):
        make_art(self.folder, "copy/logo.png")
        sync(self.arts, self.folder)
        self.assertEqual(self.arts.suggest_matches(), [])

    def test_moving_transfers_the_stock_and_logs_both_sides(self):
        source, target = row_of(self.arts, "old/logo.png"), row_of(self.arts, "logo.png")
        self.assertEqual(self.arts.move_stock(source.art_id, target.art_id), 6)
        self.assertEqual(row_of(self.arts, "logo.png").stock, 6)
        self.assertIsNone(row_of(self.arts, "old/logo.png"))               # emptied and vanished
        notes = [(m.color, m.before, m.after) for m in self.stock.movements()
                 if m.note.startswith("Estoque")]
        self.assertIn(("old/logo.png", 6, 0), notes)
        self.assertIn(("logo.png", 0, 6), notes)
        self.assertFalse(self.arts.has_missing_with_stock())

    def test_moving_adds_to_the_stock_the_target_already_had(self):
        target = row_of(self.arts, "logo.png")
        self.arts.set_stock(target.art_id, "2")
        self.arts.move_stock(row_of(self.arts, "old/logo.png").art_id, target.art_id)
        self.assertEqual(row_of(self.arts, "logo.png").stock, 8)

    def test_invalid_moves_are_refused(self):
        target = row_of(self.arts, "logo.png")
        with self.assertRaises(StockError):
            self.arts.move_stock(target.art_id, target.art_id)
        with self.assertRaises(StockError):
            self.arts.move_stock(target.art_id, row_of(self.arts, "other.png").art_id)  # no stock


class StockEditAndPersistenceTests(unittest.TestCase):
    def test_manual_edit_is_validated_and_logged_with_the_file(self):
        folder = make_folder()
        make_art(folder, "sub/a.png")
        arts, stock, path = make_art_service()
        sync(arts, folder)
        art = row_of(arts, "sub/a.png")
        for bad in ("-1", "abc", "1.5", ""):
            with self.assertRaises(StockError):
                arts.set_stock(art.art_id, bad)
        self.assertTrue(arts.set_stock(art.art_id, "7"))
        self.assertFalse(arts.set_stock(art.art_id, "7"))
        move = [m for m in stock.movements() if m.produto == "estampa"][0]
        self.assertEqual((move.kind, move.color, move.before, move.after, move.scope),
                         ("ajuste_manual", "sub/a.png", 0, 7, "estoque"))
        self.assertTrue(move.at)

    def test_everything_survives_closing_and_reopening(self):
        folder = make_folder()
        a = make_art(folder, "a.png")
        arts, stock, path = make_art_service()
        sync(arts, folder)
        arts.set_stock(row_of(arts, "a.png").art_id, "5")
        arts.replace_future(count_art_copies([make_order("1", linked_item("1", a, 3))]))
        reopened, _, _ = make_art_service(path)
        row = row_of(reopened, "a.png")
        self.assertEqual((row.stock, row.future), (5, 3))
        self.assertEqual(reopened.folder, folder)


class DuplicateTests(unittest.TestCase):
    def test_identical_content_is_reported_but_never_merged(self):
        folder = make_folder()
        a = make_art(folder, "a.png")
        make_art(folder, "copy/a_copy.png", same_as=a)
        make_art(folder, "different.png")
        arts, _, _ = make_art_service()
        sync(arts, folder)
        groups = find_identical(list_art_files(folder), {})
        self.assertEqual(len(groups), 1)
        self.assertEqual({p.replace("\\", "/").rsplit("/", 1)[-1] for p in groups[0]},
                         {"a.png", "a_copy.png"})
        self.assertEqual(len(arts.snapshot().rows), 3)                  # nothing was united

    def test_only_same_size_files_are_hashed_and_hashes_are_cached(self):
        folder = make_folder()
        a = make_art(folder, "a.png")
        make_art(folder, "b.png", same_as=a)
        files = list_art_files(folder)
        saved = []
        find_identical(files, {}, save=saved.extend)
        self.assertEqual(len(saved), 2)
        cache = {path: (size, mtime, sha) for path, size, mtime, sha in saved}
        again = []
        groups = find_identical(files, cache, save=again.extend)
        self.assertEqual(again, [])                                    # nothing re-hashed
        self.assertEqual(len(groups), 1)
        unique = make_folder()
        make_art(unique, "x.png")
        make_art(unique, "yy.png")
        calls = []
        find_identical(list_art_files(unique), {}, save=calls.extend)
        self.assertEqual(calls, [])                                    # different sizes: no hashing


if __name__ == "__main__":
    unittest.main()
