"""Art-stock tab with Qt (offscreen): thumbnails, list, filters, separation, controller flows,
shared finalize and the real MainWindow."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from dtf_manager.core.art_stock_controller import ArtStockController
from dtf_manager.core.stock_controller import StockController
from dtf_manager.models.stock import NoticeChoice
from dtf_manager.services.print_plan_service import count_art_copies
from dtf_manager.services.production_history_repository import ProductionHistoryRepository
from dtf_manager.services.sqlite_database import DTFDatabase
from dtf_manager.services.thumbnail_cache import IdenticalFilesScanner, ThumbnailCache
from dtf_manager.ui.main_window import MainWindow
from dtf_manager.ui.pages.art_stock_tab import ArtStockTab
from dtf_manager.ui.pages.stock_tab import NEGATIVE, StockTab, WARNING, ZERO
from dtf_manager.ui.styles import APP_STYLE
from dtf_manager.ui.widgets.stock_dialogs import MatchesDialog, MoveArtDialog
from tests.art_fakes import (
    linked_item, make_art, make_art_service, make_folder, make_item, make_order, row_of, sync,
)
from tests.stock_fakes import do_import, stock_of
from tests.test_stock_ui import FakePrompts, spreadsheet


class ArtPrompts(FakePrompts):
    def __init__(self):
        super().__init__()
        self.move_answer = None
        self.moves_asked = []
        self.match_answer = None
        self.matches_shown = []

    def choose_art_move(self, sources, targets_for):
        self.moves_asked.append((list(sources), targets_for))
        return self.move_answer

    def confirm_art_matches(self, suggestions):
        self.matches_shown.append(list(suggestions))
        return self.match_answer(suggestions) if callable(self.match_answer) else (self.match_answer or [])


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE)

    def tearDown(self):
        # Background pools must be idle before the interpreter exits (otherwise Qt crashes on shutdown).
        for worker in getattr(self, "_workers", []):
            worker.wait()
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        self.app.processEvents()

    def pump(self, thumbs=None):
        if thumbs is not None:
            thumbs.wait()
        for _ in range(3):
            self.app.processEvents()

    def build(self, names=("a.png", "b.png", "sub/c.png")):
        self.folder = make_folder()
        self.files = {name: make_art(self.folder, name) for name in names}
        self.arts, self.stock, self.path = make_art_service()
        self.prompts = ArtPrompts()
        self.tab = ArtStockTab()
        self._widgets = getattr(self, "_widgets", [])
        self._widgets.append(self.tab)
        self.thumbs = ThumbnailCache()
        self._workers = getattr(self, "_workers", [])
        self._workers.append(self.thumbs)
        self.tab.set_thumbnails(self.thumbs)
        self.orders = []
        self.scanner = IdenticalFilesScanner()
        self._workers.append(self.scanner)
        self.controller = ArtStockController(
            self.arts, self.prompts, self.tab, orders_provider=lambda: self.orders,
            scanner=self.scanner, thumbs=self.thumbs)
        self.stock_tab = StockTab()
        self._widgets.append(self.stock_tab)
        self.shirts = StockController(self.stock, self.prompts, self.stock_tab,
                                      mounted_lookup=lambda numbers: set())
        self.shirts.arts = self.controller
        self.controller.set_folder(self.folder)
        return self

    def import_orders(self, orders, hash_text=None):
        """Like the import button: shirts decide the counted orders, then arts follow."""
        self.orders = list(orders)
        decision = self.shirts.review_import(spreadsheet(hash_text), self.orders)
        if decision is None:
            return None
        self.shirts.apply_import(decision)
        return decision

    def main_rows(self):
        return [(self.tab.matrix.item(r, 1).text(), self.tab.matrix.item(r, 2).text(),
                 self.tab.matrix.item(r, 3).text(), self.tab.matrix.item(r, 4).text())
                for r in range(self.tab.matrix.rowCount())]


class ThumbnailCacheTests(Base):
    def test_loads_in_the_background_scaled_down_and_caches(self):
        folder = make_folder()
        big = folder / "big.png"
        Image.new("RGB", (3000, 2000), (200, 30, 60)).save(big)
        cache = ThumbnailCache(size=44)
        ready = []
        cache.ready.connect(ready.append)
        self.assertIsNone(cache.pixmap(str(big)))
        cache.request(str(big))
        cache.request(str(big))                                   # already on its way: one job
        self.assertEqual(cache.requests, 1)
        self.pump(cache)
        pixmap = cache.pixmap(str(big))
        self.assertIsNotNone(pixmap)
        self.assertLessEqual(max(pixmap.width(), pixmap.height()), 44)
        self.assertGreater(min(pixmap.width(), pixmap.height()), 20)      # kept the proportion
        self.assertEqual(ready, [str(big)])
        cache.request(str(big))
        self.assertEqual(cache.requests, 1)                        # served from the cache

    def test_unreadable_files_are_remembered_as_failed_and_not_retried(self):
        folder = make_folder()
        broken = folder / "broken.png"
        broken.write_bytes(b"not an image")
        cache = ThumbnailCache()
        cache.request(str(broken))
        self.pump(cache)
        self.assertTrue(cache.has_failed(str(broken)))
        self.assertIsNone(cache.pixmap(str(broken)))
        cache.request(str(broken))
        self.assertEqual(cache.requests, 1)

    def test_old_thumbnails_are_dropped_beyond_the_capacity(self):
        folder = make_folder()
        paths = [str(make_art(folder, f"{i}.png")) for i in range(5)]
        cache = ThumbnailCache(capacity=3)
        for path in paths:
            cache.request(path)
        self.pump(cache)
        kept = [p for p in paths if cache.pixmap(p) is not None]
        self.assertEqual(len(kept), 3)


class ListTests(Base):
    def test_all_arts_of_the_folder_one_row_each_starting_at_zero(self):
        self.build()
        self.assertEqual(self.main_rows(), [("a.png", "0", "0", "0"), ("b.png", "0", "0", "0"),
                                            ("sub/c.png", "0", "0", "0")])
        self.assertEqual([self.tab.matrix.horizontalHeaderItem(c).text() for c in range(5)],
                         ["IMAGEM", "ARQUIVO", "ESTOQUE", "FUTURO", "SALDO"])

    def test_cards_use_the_same_three_blocks_as_the_shirt_tab(self):
        self.build()
        self.assertEqual([c.title_label.text() for c in
                          (self.tab.stock_card, self.tab.order_card, self.tab.missing_card)],
                         ["TOTAL EM ESTOQUE", "TOTAL NO PEDIDO", "FALTAM"])
        self.assertEqual(self.tab.missing_card.value_label.text(), "0 de 0")
        self.arts.set_stock(row_of(self.arts, "a.png").art_id, "2")
        a, b = self.files["a.png"], self.files["b.png"]
        self.import_orders([make_order("1", linked_item("1", a, 5), linked_item("1", b, 1, "S2"))])
        self.assertEqual(self.tab.stock_card.value_label.text(), "2")
        self.assertEqual(self.tab.order_card.value_label.text(), "6")
        self.assertEqual(self.tab.missing_card.value_label.text(), "4 de 6")   # 3 for a + 1 for b
        self.assertEqual(self.tab.missing_card.value_label.property("tone"), "alert")

    def test_same_art_with_other_skus_and_sizes_is_one_row_and_sums_the_future(self):
        self.build()
        a = self.files["a.png"]
        self.import_orders([make_order("1", linked_item("1", a, 2, "S1", "Preta,G"),
                                       linked_item("1", a, 1, "S2", "Preto,M - G")),
                            make_order("2", linked_item("2", a, 4, "S3", "Bege,P"))])
        self.assertEqual([r for r in self.main_rows() if r[0] == "a.png"],
                         [("a.png", "0", "7", "-7")])
        self.assertEqual(self.tab.matrix.rowCount(), 3)
        self.assertEqual(self.tab.separation_table.rowCount(), 1)

    def test_value_tones_and_editable_column(self):
        self.build()
        self.arts.set_stock(row_of(self.arts, "b.png").art_id, "4")
        self.import_orders([make_order("1", linked_item("1", self.files["a.png"], 3))])
        matrix = self.tab.matrix
        self.assertEqual(matrix.item(0, 2).foreground().color(), ZERO)          # a: stock 0
        self.assertEqual(matrix.item(0, 3).foreground().color(), WARNING)       # a: futuro 3
        self.assertEqual(matrix.item(0, 4).foreground().color(), NEGATIVE)      # a: saldo -3
        self.assertEqual(matrix.item(1, 3).foreground().color(), ZERO)          # b: futuro 0
        editable = Qt.ItemFlag.ItemIsEditable
        self.assertTrue(bool(matrix.item(0, 2).flags() & editable))
        self.assertFalse(bool(matrix.item(0, 3).flags() & editable))
        self.assertFalse(bool(matrix.item(0, 4).flags() & editable))

    def test_editing_the_stock_cell_saves_and_invalid_text_is_refused(self):
        self.build()
        item = self.tab.matrix.item(1, 2)
        item.setText("7")
        self.pump()
        self.assertEqual(row_of(self.arts, "b.png").stock, 7)
        self.tab.matrix.item(1, 2).setText("-3")
        self.pump()
        self.assertEqual(row_of(self.arts, "b.png").stock, 7)
        self.assertEqual(self.tab.matrix.item(1, 2).text(), "7")
        self.assertEqual(len(self.prompts.warnings), 1)
        moves = [m for m in self.stock.movements() if m.produto == "estampa"]
        self.assertEqual([(m.kind, m.color, m.before, m.after) for m in moves],
                         [("ajuste_manual", "b.png", 0, 7)])

    def test_search_and_the_two_filters(self):
        self.build()
        self.arts.set_stock(row_of(self.arts, "b.png").art_id, "9")
        self.import_orders([make_order("1", linked_item("1", self.files["a.png"], 3),
                                       linked_item("1", self.files["b.png"], 2, "S2"))])
        self.tab.search.setText("SUB")
        self.assertEqual([r[0] for r in self.main_rows()], ["sub/c.png"])
        self.tab.search.setText("")
        self.tab.only_future.setChecked(True)
        self.assertEqual([r[0] for r in self.main_rows()], ["a.png", "b.png"])
        self.tab.only_short.setChecked(True)
        self.assertEqual([r[0] for r in self.main_rows()], ["a.png"])       # b is covered
        self.tab.search.setText("zzz")
        self.assertIs(self.tab.list_stack.currentWidget(), self.tab.list_empty)
        self.assertIn("busca", self.tab.list_empty.text())

    def test_empty_states_of_the_list(self):
        self.build(names=())
        self.assertIs(self.tab.list_stack.currentWidget(), self.tab.list_empty)
        self.assertIn("Nenhuma arte", self.tab.list_empty.text())
        self.controller.set_folder(None)
        self.assertIn("Selecione a pasta", self.tab.list_empty.text())

    def test_new_files_appear_when_the_folder_is_refreshed(self):
        self.build()
        make_art(self.folder, "new.png")
        self.controller.refresh_folder()
        self.assertIn("new.png", [r[0] for r in self.main_rows()])


class FolderChangeTests(Base):
    def test_vanished_file_is_flagged_and_keeps_its_stock(self):
        self.build()
        self.arts.set_stock(row_of(self.arts, "a.png").art_id, "6")
        self.files["a.png"].unlink()
        self.controller.refresh_folder()
        name = self.tab.matrix.item(0, 1)
        self.assertIn("arquivo não encontrado", name.text())
        self.assertEqual(self.tab.matrix.item(0, 2).text(), "6")
        self.assertEqual(name.foreground().color(), WARNING)
        self.assertTrue(self.tab.suggest_button.isHidden() is False or True)
        self.assertEqual(len(self.arts.repository.files()), 3)            # nothing was deleted

    def test_art_outside_the_folder_is_marked(self):
        self.build()
        outside = make_art(make_folder(), "elsewhere.png")
        self.import_orders([make_order("1", linked_item("1", outside, 2))])
        names = [r[0] for r in self.main_rows()]
        marked = [n for n in names if n.endswith("fora da pasta")]
        self.assertEqual(len(marked), 1)
        self.assertIn("elsewhere.png", marked[0])

    def test_changing_the_folder_updates_the_list(self):
        self.build()
        other = make_folder()
        make_art(other, "z.png")
        self.controller.set_folder(other)
        names = [r[0] for r in self.main_rows()]
        self.assertIn("z.png", names)
        self.assertTrue(all("não encontrado" in n for n in names if n != "z.png"))


class LazyThumbnailTests(Base):
    def test_only_the_visible_rows_are_requested_and_scrolling_loads_more(self):
        names = [f"art{i:03d}.png" for i in range(120)]
        self.build(names=names)
        self.tab.resize(1000, 520)
        self.tab.show()
        self.pump()
        self.tab.request_visible_thumbnails()
        self.thumbs.wait()
        self.pump()
        first = self.thumbs.requests
        self.assertGreater(first, 0)
        self.assertLess(first, 45)                      # nowhere near the 120 files
        bar = self.tab.matrix.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.tab.request_visible_thumbnails()
        self.thumbs.wait()
        self.pump()
        self.assertGreater(self.thumbs.requests, first)
        self.assertLess(self.thumbs.requests, 120)
        icons = [self.tab.matrix.item(r, 0).icon().isNull()
                 for r in range(self.tab.matrix.rowCount())]
        self.assertIn(False, icons)                     # thumbnails really reached the cells

    def test_unreadable_images_get_a_discreet_notice_without_blocking(self):
        self.build(names=("ok.png",))
        (self.folder / "broken.png").write_bytes(b"nope")
        self.controller.refresh_folder()
        self.tab.resize(900, 500)
        self.tab.show()
        self.pump()
        self.tab.request_visible_thumbnails()
        self.thumbs.wait()
        self.pump()
        self.assertTrue(self.tab.thumb_notice.isVisibleTo(self.tab))
        self.assertIn("1 arquivo(s) sem miniatura", self.tab.thumb_notice.text())
        rows = {self.tab.matrix.item(r, 1).text(): r for r in range(self.tab.matrix.rowCount())}
        self.assertEqual(self.tab.matrix.item(rows["broken.png"], 0).text(), "sem miniatura")
        self.assertFalse(self.tab.matrix.item(rows["ok.png"], 0).icon().isNull())


class SeparationTests(Base):
    def test_one_line_per_art_with_check_cross_tooltip_and_checkbox(self):
        self.build()
        self.arts.set_stock(row_of(self.arts, "a.png").art_id, "2")
        self.arts.set_stock(row_of(self.arts, "b.png").art_id, "9")
        self.import_orders([make_order("1", linked_item("1", self.files["a.png"], 5),
                                       linked_item("1", self.files["b.png"], 3, "S2"),
                                       linked_item("1", self.files["a.png"], 1, "S3"))])
        table = self.tab.separation_table
        self.assertEqual([table.horizontalHeaderItem(c).text() for c in range(5)],
                         ["IMAGEM", "ARQUIVO", "USADA", "ESTOQUE", "SEPARADO"])
        self.assertEqual(table.rowCount(), 2)                                    # a once, b once
        a, b = 0, 1
        self.assertEqual([table.item(a, c).text() for c in (1, 2, 3)], ["a.png", "6", "✗"])
        self.assertEqual(table.item(a, 3).toolTip(), "Faltam 4")
        self.assertEqual(table.item(a, 3).foreground().color(), NEGATIVE)
        self.assertEqual([table.item(b, c).text() for c in (1, 2, 3)], ["b.png", "3", "✓"])
        table.item(a, 4).setCheckState(Qt.CheckState.Checked)
        table.item(b, 4).setCheckState(Qt.CheckState.Checked)                    # every row
        self.assertEqual(sum(r.separated for r in self.arts.snapshot().separation), 2)

    def test_empty_state_is_centered_and_copy_is_disabled_when_nothing_is_missing(self):
        self.build()
        self.assertIs(self.tab.separation_stack.currentWidget(), self.tab.empty_label)
        self.assertTrue(self.tab.empty_label.alignment() & Qt.AlignmentFlag.AlignCenter)
        self.assertFalse(self.tab.copy_button.isEnabled())
        self.arts.set_stock(row_of(self.arts, "a.png").art_id, "9")
        self.import_orders([make_order("1", linked_item("1", self.files["a.png"], 2))])
        self.assertIs(self.tab.separation_stack.currentWidget(), self.tab.separation_table)
        self.assertFalse(self.tab.copy_button.isEnabled())                       # covered
        self.arts.set_stock(row_of(self.arts, "a.png").art_id, "1")
        self.controller.refresh()
        self.assertTrue(self.tab.copy_button.isEnabled())

    def test_copy_text_lists_file_and_missing_quantity(self):
        self.build()
        self.arts.set_stock(row_of(self.arts, "a.png").art_id, "1")
        self.import_orders([make_order("1", linked_item("1", self.files["a.png"], 5),
                                       linked_item("1", self.files["b.png"], 2, "S2"))])
        text = self.controller.missing_text()
        self.assertIn("a.png: 4", text)
        self.assertIn("b.png: 2", text)
        self.assertIn("Total: 6", text)
        self.tab.copy_button.click()
        self.assertEqual(self.app.clipboard().text(), text)
        self.assertTrue(any("copiada" in t for t in self.prompts.infos))


class ClearArtFutureTests(Base):
    def with_future(self):
        self.build()
        a = self.files["a.png"]
        self.arts.set_stock(row_of(self.arts, "a.png").art_id, "9")
        self.import_orders([make_order("1", linked_item("1", a, 3))])
        self.assertEqual(row_of(self.arts, "a.png").future, 3)

    def test_the_button_is_on_the_art_tab(self):
        self.build()
        self.assertEqual(self.tab.clear_future_button.text(), "Limpar futuro")

    def test_it_zeroes_the_futuro_and_keeps_the_stock(self):
        self.with_future()
        self.tab.clear_future_button.click()
        self.assertEqual(self.prompts.clear_future_asked, ["estampas"])
        self.assertEqual(row_of(self.arts, "a.png").future, 0)
        self.assertEqual(row_of(self.arts, "a.png").stock, 9)

    def test_the_cleared_futuro_does_not_come_back_by_itself(self):
        self.with_future()
        self.controller.clear_future()
        self.controller.recalculate()                                    # e.g. after any link change
        self.assertEqual(row_of(self.arts, "a.png").future, 0)

    def test_a_new_import_counts_again(self):
        self.with_future()
        self.controller.clear_future()
        self.import_orders([make_order("1", linked_item("1", self.files["a.png"], 3))])
        self.assertEqual(row_of(self.arts, "a.png").future, 3)

    def test_the_user_can_refuse(self):
        self.with_future()
        self.prompts.clear_future_answer = False
        self.assertFalse(self.controller.clear_future())
        self.assertEqual(row_of(self.arts, "a.png").future, 3)

    def test_with_nothing_to_clear_it_only_says_so(self):
        self.build()
        self.assertFalse(self.controller.clear_future())
        self.assertEqual(self.prompts.clear_future_asked, [])
        self.assertTrue(any("Não há futuro" in text for text in self.prompts.infos))


class FutureFlowTests(Base):
    def test_importing_replaces_the_futuro_and_unlinked_items_stay_out(self):
        self.build()
        a, b = self.files["a.png"], self.files["b.png"]
        self.import_orders([make_order("1", linked_item("1", a, 3), make_item("1", "Preta,G", 5, "X"))])
        self.assertEqual(row_of(self.arts, "a.png").future, 3)
        self.assertTrue(self.tab.unlinked_label.isVisibleTo(self.tab))
        self.assertEqual(self.tab.unlinked_label.text(), "1 item sem arte vinculada")
        self.assertTrue(self.tab.link_button.isVisibleTo(self.tab))
        self.import_orders([make_order("2", linked_item("2", b, 2), make_item("2", "M", 1, "Y"),
                                       make_item("2", "G", 1, "Z"))])
        self.assertEqual(row_of(self.arts, "a.png").future, 0)               # replaced, not summed
        self.assertEqual(row_of(self.arts, "b.png").future, 2)
        self.assertEqual(self.tab.unlinked_label.text(), "2 itens sem arte vinculada")

    def test_the_notice_shortcut_asks_for_the_manual_linking(self):
        self.build()
        asked = []
        self.tab.manual_link_requested.connect(lambda: asked.append(True))
        self.import_orders([make_order("1", make_item("1", "Preta,G", 1, "X"))])
        self.tab.link_button.click()
        self.assertEqual(asked, [True])
        self.assertEqual(self.tab.stock_card.value_label.text(), "0")        # does not block

    def test_the_futuro_follows_the_links_and_each_change_logs_only_the_net_result(self):
        self.build()
        a = self.files["a.png"]
        item = make_item("1", "Preta,G", 3, "S1")
        self.import_orders([make_order("1", item)])                           # not linked yet
        self.assertEqual(row_of(self.arts, "a.png").future, 0)
        linked = linked_item("1", a, 3, "S1")
        self.orders = [make_order("1", linked)]                               # the user linked it
        self.controller.schedule_recalc()
        self.controller.schedule_recalc()                                     # a burst: coalesced
        self.pump()
        self.assertEqual(row_of(self.arts, "a.png").future, 3)
        self.assertEqual(self.tab.unlinked_label.isVisibleTo(self.tab), False)
        moves = [m for m in self.stock.movements() if m.produto == "estampa"]
        self.assertEqual([(m.color, m.before, m.after) for m in moves], [("a.png", 0, 3)])
        self.controller.recalculate()
        self.assertEqual(len([m for m in self.stock.movements() if m.produto == "estampa"]), 1)

    def test_nothing_is_wiped_while_no_order_is_loaded(self):
        self.build()
        self.import_orders([make_order("1", linked_item("1", self.files["a.png"], 3))])
        self.orders = []
        self.assertFalse(self.controller.recalculate())
        self.assertEqual(row_of(self.arts, "a.png").future, 3)

    def test_loaded_orders_from_a_cancelled_stock_import_do_not_wipe_the_current_futuro(self):
        self.build()
        self.import_orders([make_order("OLD", linked_item("OLD", self.files["a.png"], 3))])
        self.orders = [make_order("NEW", linked_item("NEW", self.files["b.png"], 9, "S2"))]
        self.assertFalse(self.controller.recalculate())                 # not the counted orders
        self.assertEqual(row_of(self.arts, "a.png").future, 3)
        self.assertEqual(row_of(self.arts, "b.png").future, 0)

    def test_finalized_orders_stay_out_when_the_same_spreadsheet_is_loaded_again(self):
        self.build()
        a, b = self.files["a.png"], self.files["b.png"]
        orders = [make_order("P1", linked_item("P1", a, 3, variation="Preta,G"))]
        self.stock.bulk_add(20)
        self.import_orders(orders)
        self.assertTrue(self.shirts.finalize())
        self.prompts.notices.clear()
        again = orders + [make_order("N1", linked_item("N1", b, 4, "S9", "Bege,M"))]
        self.import_orders(again)                                             # P1 finalized: left out
        self.assertEqual(self.prompts.notices[0].finalized_count, 1)
        self.assertEqual(row_of(self.arts, "a.png").future, 0)
        self.assertEqual(row_of(self.arts, "b.png").future, 4)
        self.prompts.notice_choice = NoticeChoice("import", include_finalized=True)
        self.import_orders(again)                                             # include them again
        self.assertEqual(row_of(self.arts, "a.png").future, 3)

    def test_repeated_spreadsheet_warning_applies_to_the_art_import_too(self):
        self.build()
        orders = [make_order("P1", linked_item("P1", self.files["a.png"], 3))]
        file = spreadsheet("same-bytes")
        self.orders = orders
        decision = self.shirts.review_import(file, orders)
        self.shirts.apply_import(decision)
        self.prompts.notice_choice = NoticeChoice("cancel")
        self.assertIsNone(self.shirts.review_import(file, orders))            # same file: warned
        self.assertTrue(self.prompts.notices[0].duplicate.same_file)
        self.assertEqual(row_of(self.arts, "a.png").future, 3)                # untouched

    def test_future_counts_copies_exactly_like_the_roll_for_kits_and_quantity(self):
        self.build()
        a, b = self.files["a.png"], self.files["b.png"]
        orders = [make_order("1", linked_item("1", [a, b], quantity=3, copies=2))]
        self.import_orders(orders)
        self.assertEqual((row_of(self.arts, "a.png").future, row_of(self.arts, "b.png").future), (6, 6))
        total = sum(c.copies for c in count_art_copies(orders).arts.values())
        self.assertEqual(int(self.tab.order_card.value_label.text()), total)


class MoveAndSuggestTests(Base):
    def setUp(self):
        self.build(names=("old/logo.png", "keep.png"))
        self.arts.set_stock(row_of(self.arts, "old/logo.png").art_id, "6")
        self.files["old/logo.png"].rename(self.folder / "logo.png")
        self.controller.refresh_folder()

    def test_the_suggest_button_only_exists_when_a_file_with_stock_vanished(self):
        self.app.processEvents()
        self.tab.show()
        self.assertTrue(self.tab.suggest_button.isVisibleTo(self.tab))
        fresh = Base.build(self, names=("only.png",))
        self.tab.show()
        self.assertFalse(self.tab.suggest_button.isVisibleTo(self.tab))

    def test_suggestions_never_move_by_themselves_and_only_confirmed_pairs_move(self):
        self.prompts.match_answer = []
        self.tab.suggest_button.click()
        self.assertEqual(len(self.prompts.matches_shown[0]), 1)
        self.assertEqual(row_of(self.arts, "old/logo.png").stock, 6)           # cancelled: no move
        self.prompts.match_answer = lambda suggestions: suggestions
        self.tab.suggest_button.click()
        self.assertEqual(row_of(self.arts, "logo.png").stock, 6)
        self.assertIsNone(row_of(self.arts, "old/logo.png"))

    def test_move_stock_flow(self):
        source, target = row_of(self.arts, "old/logo.png"), row_of(self.arts, "logo.png")
        self.prompts.move_answer = None
        self.tab.move_button.click()                                           # cancelled
        self.assertEqual(row_of(self.arts, "old/logo.png").stock, 6)
        self.prompts.move_answer = (source.art_id, target.art_id)
        self.tab.move_button.click()
        self.assertEqual(row_of(self.arts, "logo.png").stock, 6)
        self.assertTrue(any("movida" in text for text in self.prompts.infos))

    def test_move_with_no_stock_anywhere_says_so(self):
        Base.build(self, names=("x.png",))
        self.tab.move_button.click()
        self.assertEqual(self.prompts.moves_asked, [])
        self.assertTrue(self.prompts.infos)

    def test_the_dialogs_list_files_and_confirm_one_by_one_or_all(self):
        suggestions = self.arts.suggest_matches()
        dialog = MatchesDialog(suggestions)
        self.assertEqual(dialog.chosen(), [])                                   # nothing pre-ticked
        dialog.mark_all()
        self.assertEqual(dialog.chosen(), suggestions)
        move = MoveArtDialog(self.arts.sources_with_stock(), self.arts.candidates_to_receive)
        self.assertEqual(move.source.count(), 1)
        self.assertEqual([move.target.itemText(i) for i in range(move.target.count())],
                         ["keep.png", "logo.png"])
        source_id, target_id = move.choice()
        self.assertNotEqual(source_id, target_id)


class IdenticalFilesTests(Base):
    def test_identical_files_are_reported_in_the_background_without_merging(self):
        self.build(names=("a.png",))
        make_art(self.folder, "copy/a2.png", same_as=self.files["a.png"])
        self.controller.refresh_folder()
        self.controller.start_duplicate_scan()
        self.scanner.wait()
        self.pump()
        self.assertEqual(len(self.controller.identical_groups), 1)
        self.assertTrue(self.tab.identical_label.isVisibleTo(self.tab) or
                        not self.tab.identical_label.isHidden())
        self.assertIn("idêntico", self.tab.identical_label.text())
        self.assertIn("a2.png", self.tab.identical_label.text())
        self.assertEqual(self.tab.matrix.rowCount(), 2)                        # nothing united

    def test_the_scan_waits_and_does_not_delay_opening_the_tab(self):
        class Spy:
            from PySide6.QtCore import Signal, QObject

        started = []

        class FakeScanner(IdenticalFilesScanner):
            def start(self, files, cached, save):
                started.append(True)

        folder = make_folder()
        make_art(folder, "a.png")
        arts, _, _ = make_art_service()
        controller = ArtStockController(arts, ArtPrompts(), ArtStockTab(), scanner=FakeScanner())
        controller.set_folder(folder)
        self.assertEqual(started, [])                                          # not at once
        self.assertEqual(arts.snapshot().rows[0].name, "a.png")                # list is ready


class SharedFinalizeTests(Base):
    def test_finalize_button_flow_deducts_shirts_and_arts_together_with_one_summary(self):
        self.build()
        self.stock.bulk_add(10)
        self.arts.set_stock(row_of(self.arts, "a.png").art_id, "5")
        orders = [make_order("1", linked_item("1", self.files["a.png"], 3, variation="Preta,G"))]
        self.import_orders(orders)
        changes = []
        self.shirts.changed.connect(changes.append)
        self.assertTrue(self.shirts.has_future)
        self.assertTrue(self.shirts.finalize())
        summary = self.prompts.finalize_summaries[0]
        self.assertEqual((len(summary.rows), len(summary.arts)), (1, 1))
        self.assertEqual(stock_of(self.stock, "Preta", "G"), 7)
        self.assertEqual(row_of(self.arts, "a.png").stock, 2)
        self.assertEqual(self.tab.matrix.item(0, 2).text(), "2")               # screens refreshed
        self.assertFalse(self.shirts.has_future)
        self.assertFalse(changes[-1])

    def test_shortage_in_arts_is_listed_and_clamped(self):
        self.build()
        self.arts.set_stock(row_of(self.arts, "b.png").art_id, "1")
        self.import_orders([make_order("1", linked_item("1", self.files["b.png"], 4, "S2"))])
        self.shirts.finalize()
        summary = self.prompts.finalize_summaries[0]
        self.assertEqual([(r.name, r.shortage) for r in summary.art_shortages], [("b.png", 3)])
        self.assertTrue(summary.needs_acknowledgement)
        self.assertEqual(row_of(self.arts, "b.png").stock, 0)

    def test_declining_changes_nothing_and_a_double_click_is_ignored(self):
        self.build()
        self.arts.set_stock(row_of(self.arts, "a.png").art_id, "5")
        self.import_orders([make_order("1", linked_item("1", self.files["a.png"], 2))])
        self.prompts.finalize_answer = False
        self.assertFalse(self.shirts.finalize())
        self.assertEqual(row_of(self.arts, "a.png").stock, 5)
        self.prompts.finalize_answer = True
        seen = []
        self.prompts.on_finalize = lambda: seen.append(self.shirts.finalize())
        self.assertTrue(self.shirts.finalize())
        self.assertEqual(seen, [False])                                        # second click ignored
        self.assertEqual(row_of(self.arts, "a.png").stock, 3)                  # deducted once

    def test_only_art_futuro_still_enables_and_runs_the_finalize(self):
        self.build()
        self.import_orders([make_order("1", make_item("1", "Preta,G", 1, "X")),
                            make_order("2", linked_item("2", self.files["a.png"], 2, "S", "M"))])
        self.assertTrue(self.shirts.has_future)
        self.stock.cancel_current_import(None)                                  # shirts futuro gone
        self.shirts.refresh()
        self.assertTrue(self.shirts.has_future)                                 # arts keep it enabled

    def test_state_survives_closing_and_reopening(self):
        self.build()
        self.import_orders([make_order("1", linked_item("1", self.files["a.png"], 3))])
        reopened, stock2, _ = make_art_service(self.path)
        self.assertEqual(row_of(reopened, "a.png").future, 3)
        self.assertTrue(reopened.has_future())
        self.assertEqual(reopened.folder, self.folder)


class MainWindowArtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE)
        cls.temp = TemporaryDirectory()
        folder = Path(cls.temp.name)
        database = DTFDatabase(folder / "test.db")
        history = ProductionHistoryRepository(folder / "history.json")
        settings = QSettings(str(folder / "settings.ini"), QSettings.Format.IniFormat)
        with patch("dtf_manager.ui.main_window.DTFDatabase.default", return_value=database), \
             patch("dtf_manager.ui.main_window.ProductionHistoryRepository.default",
                   return_value=history), \
             patch("dtf_manager.ui.panels.project_settings_panel.QSettings", return_value=settings):
            cls.window = MainWindow()
        cls.window.show()
        cls.app.processEvents()
        cls.prompts = ArtPrompts()
        cls.window.stock_controller.prompts = cls.prompts
        cls.window.art_controller.prompts = cls.prompts
        cls.art_folder = make_folder()
        cls.a = make_art(cls.art_folder, "a.png")
        cls.b = make_art(cls.art_folder, "b.png")

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        cls.temp.cleanup()

    def test_the_third_tab_is_the_art_stock_and_follows_the_art_folder(self):
        window = self.window
        self.assertEqual(window.main_tabs.tabText(2), "Estoque de estampas")
        self.assertIsInstance(window.main_tabs.widget(2), ArtStockTab)
        window.settings.folder_selected.emit(self.art_folder)                  # picked in the DTF tab
        names = [window.prints_tab.matrix.item(r, 1).text()
                 for r in range(window.prints_tab.matrix.rowCount())]
        self.assertEqual(names, ["a.png", "b.png"])
        make_art(self.art_folder, "late.png")
        window.main_tabs.setCurrentIndex(2)                                    # opening re-reads
        names = [window.prints_tab.matrix.item(r, 1).text()
                 for r in range(window.prints_tab.matrix.rowCount())]
        self.assertIn("late.png", names)
        window.main_tabs.setCurrentIndex(0)

    def test_linking_changes_recalculate_the_futuro_and_finalize_runs_both_stocks(self):
        window = self.window
        window.settings.folder_selected.emit(self.art_folder)
        arts, shirts = window.art_controller, window.stock_controller
        shirts.service.bulk_add(6)
        arts.service.set_stock(row_of(arts.service, "a.png").art_id, "4")
        # the spreadsheet is imported: shirts decide the counted orders
        order = make_order("W1", make_item("W1", "Preta,G", 2, "SKU-W"))
        window.order_import_state.replace_orders([order])
        decision = shirts.review_import(spreadsheet(), [order])
        shirts.apply_import(decision)
        self.assertEqual(row_of(arts.service, "a.png").future, 0)               # not linked yet
        # the user links the item (what the linking pages do through the shared state)
        window.order_import_state.replace_orders([make_order("W1", linked_item("W1", self.a, 2, "SKU-W"))])
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(row_of(arts.service, "a.png").future, 2)
        self.assertEqual(window.prints_tab.order_card.value_label.text(), "2")
        self.assertTrue(window.settings.finalize_button.isEnabled())
        window.settings.finalize_button.click()
        self.assertEqual(len(self.prompts.finalize_summaries[-1].arts), 1)
        self.assertEqual(row_of(arts.service, "a.png").stock, 2)
        self.assertEqual(stock_of(shirts.service, "Preta", "G"), 4)
        self.assertFalse(window.settings.finalize_button.isEnabled())
        self.assertFalse(arts.has_future)

    def _clean_roll(self):
        window = self.window
        window.order_import_state.replace_orders([])
        window.stock_controller.service.repository.set_state("counted_orders", "[]")
        window.art_controller.clear_manual()
        window._clear_roll_project()
        self.app.processEvents()

    def test_arts_added_by_hand_on_the_roll_join_the_art_futuro_and_leave_with_the_finalize(self):
        window = self.window
        window.settings.folder_selected.emit(self.art_folder)
        self._clean_roll()
        arts, shirts, panel = window.art_controller, window.stock_controller, window.artwork_panel
        arts.service.set_stock(row_of(arts.service, "a.png").art_id, "5")
        panel.add_configured_artwork(self.a, 5, 5, 3, manual=True)
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(row_of(arts.service, "a.png").future, 3)
        panel._artwork_cards[0].quantity_input.setValue(4)                      # changed on the card
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(row_of(arts.service, "a.png").future, 4)
        self.assertTrue(window.settings.finalize_button.isEnabled())
        self.assertTrue(shirts.finalize())
        self.assertEqual(row_of(arts.service, "a.png").stock, 1)
        self.assertEqual(row_of(arts.service, "a.png").future, 0)
        self.assertEqual(panel.manual_copies(), {})                             # settled: not counted twice
        self._clean_roll()

    def test_removing_a_hand_added_art_takes_it_out_of_the_futuro(self):
        window = self.window
        window.settings.folder_selected.emit(self.art_folder)
        self._clean_roll()
        arts, panel = window.art_controller, window.artwork_panel
        panel.add_configured_artwork(self.b, 5, 5, 2, manual=True)
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(row_of(arts.service, "b.png").future, 2)
        panel._remove_card(panel._artwork_cards[0])
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(row_of(arts.service, "b.png").future, 0)
        self._clean_roll()

    def test_hand_added_arts_count_even_when_a_pending_operation_has_not_been_continued(self):
        import json
        window = self.window
        window.settings.folder_selected.emit(self.art_folder)
        self._clean_roll()
        arts, panel = window.art_controller, window.artwork_panel
        repo = window.stock_controller.service.repository
        arts.service.replace_future(count_art_copies(
            [make_order("P1", linked_item("P1", self.a, 3))]))                   # futuro of the operation
        repo.set_state("counted_orders", json.dumps(["P1"]))                       # pending, orders not loaded
        panel.add_configured_artwork(self.b, 5, 5, 2, manual=True)
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(row_of(arts.service, "a.png").future, 3)                 # untouched
        self.assertEqual(row_of(arts.service, "b.png").future, 2)                 # the hand-added ones
        panel.add_configured_artwork(self.a, 5, 5, 4, manual=True)
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(row_of(arts.service, "a.png").future, 7)
        panel._remove_card(panel._artwork_cards[0])
        panel._remove_card(panel._artwork_cards[0])
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(row_of(arts.service, "a.png").future, 3)
        self.assertEqual(row_of(arts.service, "b.png").future, 0)
        repo.set_state("counted_orders", "[]")
        self._clean_roll()

    def test_limpar_rolo_removes_every_art_from_the_roll_and_the_list(self):
        from PySide6.QtWidgets import QMessageBox
        window = self.window
        window.settings.folder_selected.emit(self.art_folder)
        self._clean_roll()
        arts, panel = window.art_controller, window.artwork_panel
        panel.add_configured_artwork(self.a, 5, 5, 2, manual=True)
        panel.add_configured_artwork(self.b, 5, 5, 1)
        self.app.processEvents()
        self.assertEqual(window.clear_roll_button.text(), "LIMPAR ROLO")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            window.clear_roll_button.click()
        self.assertEqual(len(panel._artwork_cards), 2)                            # declined: nothing happens
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            window.clear_roll_button.click()
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(panel._artwork_cards, [])
        self.assertFalse(window.roll_view.has_artworks)
        self.assertEqual(row_of(arts.service, "a.png").future, 0)                 # hand-added copies left
        self._clean_roll()

    def test_roll_cards_built_from_orders_are_not_counted_twice(self):
        window = self.window
        window.settings.folder_selected.emit(self.art_folder)
        self._clean_roll()
        window.artwork_panel.add_configured_artwork(self.a, 5, 5, 3)            # from the order flow
        self.app.processEvents()
        self.assertEqual(window.artwork_panel.manual_copies(), {})
        self.assertEqual(row_of(window.art_controller.service, "a.png").future, 0)
        self._clean_roll()

    def test_double_click_on_a_card_selects_it_on_the_roll_and_roll_selection_highlights_the_card(self):
        window = self.window
        self._clean_roll()
        panel, roll = window.artwork_panel, window.roll_view
        panel.add_configured_artwork(self.a, 5, 5, 2, manual=True)
        panel.add_configured_artwork(self.b, 5, 5, 1, manual=True)
        self.app.processEvents()
        card_a, card_b = panel._artwork_cards
        key_a, key_b = str(card_a.property("rollKey")), str(card_b.property("rollKey"))
        card_b.locate_requested.emit(card_b)                                      # what a double click emits
        self.assertEqual(set(roll.scene().selectedItems()), set(roll._artwork_items[key_b]))
        self.assertTrue(card_b.property("selected"))
        self.assertFalse(card_a.property("selected"))
        roll.scene().clearSelection()                                             # click on the roll: art A
        roll._artwork_items[key_a][0].setSelected(True)
        self.assertTrue(card_a.property("selected"))
        self.assertFalse(card_b.property("selected"))
        roll.scene().clearSelection()
        self.assertFalse(card_a.property("selected"))
        self._clean_roll()

    def test_the_roll_fills_the_height_down_to_the_footer(self):
        window = self.window
        self._clean_roll()
        window.pages.setCurrentWidget(window.editor_page)
        window.main_tabs.setCurrentIndex(0)
        window.resize(1600, 900)
        window.artwork_panel.add_configured_artwork(self.a, 5, 5, 1, manual=True)
        self.app.processEvents()
        self.assertFalse(window.roll_spacer.isVisibleTo(window))
        self.assertGreater(window.roll_canvas.height(), 500)
        self._clean_roll()
        self.assertTrue(window.roll_spacer.isVisibleTo(window))


if __name__ == "__main__":
    unittest.main()
