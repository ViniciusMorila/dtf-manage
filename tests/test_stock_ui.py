"""Stock tabs with Qt (offscreen): controller flows, dialogs and the real MainWindow."""
import os
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QLabel

from dtf_manager.core.stock_controller import StockController
from dtf_manager.models.stock import LineDecision, NoticeChoice
from dtf_manager.services.production_history_repository import ProductionHistoryRepository
from dtf_manager.services.sqlite_database import DTFDatabase
from dtf_manager.ui.main_window import MainWindow
from dtf_manager.ui.pages.art_stock_tab import ArtStockTab
from dtf_manager.ui.pages.stock_tab import NEGATIVE, StockTab
from dtf_manager.ui.styles import APP_STYLE
from dtf_manager.ui.widgets.stock_dialogs import (
    BulkAddDialog, FinalizeDialog, ImportNoticeDialog, StockHistoryDialog,
    ValidationDialog,
)
from tests.stock_fakes import (
    future_of, ids, make_item, make_order, make_service, stock_of,
)

_counter = [0]


def spreadsheet(content: str | None = None) -> Path:
    """A throwaway file standing in for an .xlsx (only its bytes are hashed)."""
    _counter[0] += 1
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", prefix=f"s{_counter[0]}_")
    handle.write((content or f"file-{_counter[0]}").encode())
    handle.close()
    return Path(handle.name)


class FakePrompts:
    def __init__(self):
        self.names, self.warnings, self.infos = [], [], []
        self.notices, self.notice_choice = [], NoticeChoice("import", False)
        self.validations, self.validate_answer = [], {}
        self.finalize_summaries, self.finalize_answer = [], True
        self.on_finalize = None
        self.bulk_answer = None
        self.history_calls = []
        self.delete_choice, self.delete_confirm, self.delete_confirms = None, True, []

    def choose_color(self, colors):
        return self.delete_choice

    def confirm_delete_color(self, name, stock, future):
        self.delete_confirms.append((name, stock, future))
        return self.delete_confirm

    def ask_name(self, title, label):
        return self.names.pop(0) if self.names else None

    def warn(self, title, text):
        self.warnings.append(text)

    def info(self, title, text):
        self.infos.append(text)

    def bulk(self, colors, sizes, preview):
        return self.bulk_answer

    def import_notice(self, notice):
        self.notices.append(notice)
        return self.notice_choice

    def validate(self, lines, colors, sizes):
        self.validations.append(list(lines))
        answer = self.validate_answer
        return answer(lines) if callable(answer) else answer

    def confirm_finalize(self, summary):
        self.finalize_summaries.append(summary)
        if self.on_finalize:
            self.on_finalize()
        return self.finalize_answer

    def show_history(self, movements, imports):
        self.history_calls.append((movements, imports))


class ControllerBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE)

    def setUp(self):
        self.service, self.path = make_service()
        self.prompts = FakePrompts()
        self.tab = StockTab()
        self.mounted = set()
        self.controller = StockController(
            self.service, self.prompts, self.tab,
            mounted_lookup=lambda numbers: self.mounted & set(numbers))
        self.colors, self.sizes = ids(self.service)

    def orders(self, prefix="P", n=3, variation="Preta,G", quantity=1):
        return [make_order(f"{prefix}{i}", (variation, quantity)) for i in range(n)]

    def run_import(self, orders, file=None, include=False):
        decision = self.controller.review_import(file or spreadsheet(), orders)
        if decision is None:
            return None
        self.controller.apply_import(decision)
        return decision

    def cell(self, kind, color, size):
        """kind: "stock" | "future" | "balance" -> the item in the single matrix table."""
        snap = self.service.snapshot()
        row = (2 + [c.name for c in snap.colors].index(color) * (len(snap.sizes) + 1)
               + [s.name for s in snap.sizes].index(size))
        return self.tab.matrix.item(row, 2 + ("stock", "future", "balance").index(kind))


class TabTests(ControllerBase):
    def test_one_block_per_color_with_the_sizes_stacked(self):
        matrix = self.tab.matrix
        self.assertEqual(matrix.rowCount(), 2 + 4 * 5 + 1)         # header+gap, 4 boxes+gaps, Total
        self.assertEqual(matrix.columnCount(), 5)
        self.assertEqual([matrix.item(0, c).text() for c in range(5)],
                         ["COR", "TAM.", "ESTOQUE", "FUTURO", "SALDO"])
        self.assertEqual([matrix.item(r, 1).text() for r in range(2, 6)], ["P", "M", "G", "GG"])
        self.assertEqual(matrix.rowSpan(2, 0), 4)                  # the color box covers its sizes
        self.assertEqual([matrix.item(r, 1).text() for r in range(7, 11)], ["P", "M", "G", "GG"])
        for kind in ("stock", "future", "balance"):
            self.assertEqual(self.cell(kind, "Preta", "G").text(), "0")
        self.service.bulk_add(2)
        self.run_import(self.orders(n=5, variation="Preta,G"))           # needs 5, has 2
        self.assertEqual(self.cell("future", "Preta", "G").text(), "5")
        balance = self.cell("balance", "Preta", "G")
        self.assertEqual(balance.text(), "-3")
        self.assertEqual(balance.foreground().color(), NEGATIVE)
        self.assertEqual(self.cell("balance", "Bege", "M").text(), "2")
        editable = Qt.ItemFlag.ItemIsEditable
        self.assertFalse(bool(self.cell("future", "Preta", "G").flags() & editable))
        self.assertFalse(bool(self.cell("balance", "Preta", "G").flags() & editable))
        self.assertTrue(bool(self.cell("stock", "Preta", "G").flags() & editable))

    def test_each_color_is_its_own_rounded_box_with_a_gap_between_them(self):
        from dtf_manager.ui.pages.stock_tab import GAP_HEIGHT
        matrix = self.tab.matrix
        self.assertEqual(matrix._blocks, [(2, 5), (7, 10), (12, 15), (17, 20), (22, 22)])
        for gap in (1, 6, 11, 16, 21):                                # between boxes and before Total
            self.assertIsNone(matrix.item(gap, 0))
            self.assertEqual(matrix.rowHeight(gap), GAP_HEIGHT)
            self.assertNotIn(gap, matrix.stock_rows)
        self.assertFalse(matrix.showGrid())
        matrix.resize(900, 700)
        matrix.show()
        self.app.processEvents()
        image = matrix.viewport().grab().toImage()                    # the paint code runs
        self.assertFalse(image.isNull())

    def test_size_rows_alternate_a_lighter_tone_for_contrast(self):
        from dtf_manager.ui.pages.stock_tab import ROW_DARK, ROW_LIGHT
        matrix = self.tab.matrix
        for column in (1, 2, 3):                 # TAM., ESTOQUE, FUTURO
            tones = [matrix.item(row, column).background().color() for row in range(2, 6)]
            self.assertEqual(tones, [ROW_DARK, ROW_LIGHT, ROW_DARK, ROW_LIGHT])
        self.assertEqual(matrix.item(7, 2).background().color(), ROW_DARK)   # next block restarts

    def test_color_column_is_painted_with_the_shirt_color(self):
        from dtf_manager.ui.pages.stock_tab import shirt_colors
        matrix = self.tab.matrix
        starts = (2, 7, 12, 17)
        names = [matrix.item(r, 0).text() for r in starts]
        self.assertEqual(names, ["PRETA", "MARROM", "BEGE", "BRANCA"])
        for row, color in zip(starts, ("Preta", "Marrom", "Bege", "Branca")):
            self.assertEqual(matrix.item(row, 0).background().color(), shirt_colors(color)[0])
        self.assertNotEqual(shirt_colors("Preta")[0], shirt_colors("Branca")[0])

    def test_editing_a_stock_cell_saves_and_invalid_text_is_refused(self):
        self.cell("stock", "Preta", "M").setText("7")
        self.app.processEvents()
        self.assertEqual(stock_of(self.service, "Preta", "M"), 7)
        self.cell("stock", "Preta", "M").setText("-4")
        self.app.processEvents()
        self.assertEqual(stock_of(self.service, "Preta", "M"), 7)
        self.assertEqual(self.cell("stock", "Preta", "M").text(), "7")
        self.assertEqual(len(self.prompts.warnings), 1)

    def test_new_color_and_size_refuse_duplicates(self):
        self.prompts.names = ["Azul"]
        self.controller.new_color()
        self.assertEqual(self.tab.matrix.rowCount(), 2 + 5 * 5 + 1)
        self.prompts.names = ["PRETA"]
        self.controller.new_color()
        self.assertEqual(self.tab.matrix.rowCount(), 2 + 5 * 5 + 1)
        self.assertEqual(len(self.prompts.warnings), 1)
        self.prompts.names = ["xg"]
        self.controller.new_size()
        self.assertEqual(self.tab.matrix.rowCount(), 2 + 5 * 6 + 1)
        self.prompts.names = [None]
        self.controller.new_size()                                       # cancelled
        self.assertEqual(self.tab.matrix.rowCount(), 2 + 5 * 6 + 1)

    def test_delete_color_button_asks_which_color_and_confirms(self):
        self.prompts.names = ["Verde"]
        self.controller.new_color()
        green = ids(self.service)[0]["Verde"]
        self.service.set_stock(green, self.sizes["P"], "3")
        self.controller.refresh()
        rows_before = self.tab.matrix.rowCount()
        self.prompts.delete_choice = None                                   # cancelled at the list
        self.tab.delete_color_button.click()
        self.assertEqual(self.tab.matrix.rowCount(), rows_before)
        self.prompts.delete_choice, self.prompts.delete_confirm = green, False
        self.tab.delete_color_button.click()                                 # declined
        self.assertEqual(self.prompts.delete_confirms[-1], ("Verde", 3, 0))
        self.assertEqual(self.tab.matrix.rowCount(), rows_before)
        self.prompts.delete_confirm = True
        self.tab.delete_color_button.click()
        self.assertLess(self.tab.matrix.rowCount(), rows_before)
        self.assertNotIn("Verde", [c.name for c in self.service.snapshot().colors])

    def test_delete_color_signal_with_an_id_skips_the_list(self):
        green = self.service.add_color("Verde").id
        self.controller.refresh()
        self.tab.delete_color_requested.emit(green)
        self.assertEqual(self.prompts.delete_confirms, [("Verde", 0, 0)])
        self.assertNotIn("Verde", [c.name for c in self.service.snapshot().colors])

    def test_bulk_add_through_the_controller(self):
        self.prompts.bulk_answer = (3, self.colors["Bege"], None)
        self.controller.bulk_add()
        self.assertEqual(self.cell("stock", "Bege", "GG").text(), "3")
        self.assertEqual(self.cell("stock", "Preta", "GG").text(), "0")
        self.prompts.bulk_answer = None
        self.controller.bulk_add()
        self.assertEqual(stock_of(self.service, "Bege", "GG"), 3)

    def test_separation_list_and_checkbox(self):
        self.service.set_stock(self.colors["Preta"], self.sizes["G"], "2")
        self.run_import(self.orders(n=5, variation="Preta,G") + [make_order("X", ("Bege,M", 1))])
        self.service.set_stock(self.colors["Bege"], self.sizes["M"], "4")
        self.controller.refresh()
        table = self.tab.separation_table
        self.assertEqual(table.columnCount(), 5)
        self.assertEqual([table.horizontalHeaderItem(c).text() for c in range(5)],
                         ["COR", "TAM.", "PRECISA", "ESTOQUE", "SEPARADO"])
        self.assertEqual(table.rowCount(), 2)
        rows = {table.item(r, 0).text(): r for r in range(2)}
        preta, bege = rows["Preta"], rows["Bege"]
        self.assertEqual([table.item(preta, c).text() for c in (1, 2, 3)], ["G", "5", "✗"])
        self.assertEqual(table.item(preta, 3).toolTip(), "Faltam 3")
        self.assertEqual(table.item(preta, 3).foreground().color(), NEGATIVE)
        self.assertEqual(table.item(bege, 3).text(), "✓")
        table.item(preta, 4).setCheckState(Qt.CheckState.Checked)
        table.item(bege, 4).setCheckState(Qt.CheckState.Checked)       # checkable on every row
        self.assertEqual(sum(r.separated for r in self.service.snapshot().separation), 2)

    def test_separation_empty_state_is_centered(self):
        self.assertIs(self.tab.separation_stack.currentWidget(), self.tab.empty_label)
        self.assertTrue(self.tab.empty_label.alignment() & Qt.AlignmentFlag.AlignCenter)
        self.service.bulk_add(10)
        self.run_import(self.orders(n=2))                                # stock covers it
        self.assertIs(self.tab.separation_stack.currentWidget(), self.tab.separation_table)
        self.assertEqual(self.tab.separation_table.item(0, 3).text(), "✓")
        self.service.set_stock(self.colors["Preta"], self.sizes["G"], "1")
        self.controller.refresh()
        self.assertEqual(self.tab.separation_table.item(0, 3).text(), "✗")

    def test_summary_cards(self):
        self.assertEqual(self.tab.stock_card.value_label.text(), "0")
        self.assertEqual(self.tab.order_card.value_label.text(), "0")
        self.assertEqual(self.tab.missing_card.value_label.text(), "0 de 0")
        self.assertEqual(self.tab.missing_card.value_label.property("tone"), "normal")
        self.assertEqual([self.tab.stock_card.title_label.text(),
                          self.tab.order_card.title_label.text(),
                          self.tab.missing_card.title_label.text()],
                         ["EM ESTOQUE", "TOTAL NO PEDIDO", "FALTAM COMPRAR"])
        self.service.set_stock(self.colors["Preta"], self.sizes["G"], "2")
        self.service.set_stock(self.colors["Bege"], self.sizes["M"], "9")
        self.run_import(self.orders(n=5, variation="Preta,G") + [make_order("X", ("Bege,M", 1))])
        self.assertEqual(self.tab.stock_card.value_label.text(), "11")
        self.assertEqual(self.tab.order_card.value_label.text(), "6")
        self.assertEqual(self.tab.missing_card.value_label.text(), "3 de 6")   # Bege is covered
        self.assertEqual(self.tab.missing_card.value_label.property("tone"), "alert")

    def test_only_one_total_row_at_the_end_and_no_total_per_color(self):
        from dtf_manager.ui.pages.stock_tab import ZERO, WARNING, NORMAL
        self.service.set_stock(self.colors["Preta"], self.sizes["G"], "4")
        self.service.set_stock(self.colors["Bege"], self.sizes["M"], "3")
        self.run_import(self.orders(n=6, variation="Preta,G"))
        matrix = self.tab.matrix
        labels = [matrix.item(r, 0).text() for r in range(matrix.rowCount())
                  if matrix.item(r, 0) is not None and matrix.item(r, 0).text()]
        self.assertEqual(labels, ["COR", "PRETA", "MARROM", "BEGE", "BRANCA", "TOTAL GERAL"])
        last = matrix.rowCount() - 1
        self.assertEqual(matrix.item(last, 0).text(), "TOTAL GERAL")
        self.assertEqual([matrix.item(last, c).text() for c in (2, 3, 4)], ["7", "6", "1"])
        editable = Qt.ItemFlag.ItemIsEditable
        self.assertFalse(bool(matrix.item(last, 2).flags() & editable))
        self.assertNotIn(last, matrix.stock_rows)
        # value tones: zero weak gray, positive normal, futuro > 0 amber
        self.assertEqual(self.cell("stock", "Marrom", "P").foreground().color(), ZERO)
        self.assertEqual(self.cell("stock", "Preta", "G").foreground().color(), NORMAL)
        self.assertEqual(self.cell("future", "Preta", "G").foreground().color(), WARNING)
        self.assertEqual(self.cell("future", "Marrom", "P").foreground().color(), ZERO)
        self.assertEqual(self.cell("balance", "Preta", "G").foreground().color(), NEGATIVE)

    # ---- keyboard editing ----------------------------------------------------------------
    def editor(self):
        from PySide6.QtWidgets import QLineEdit
        self.app.processEvents()
        boxes = [w for w in self.tab.matrix.findChildren(QLineEdit) if w.isVisible()]
        return boxes[-1] if boxes else None

    def press(self, widget, key, modifiers=Qt.KeyboardModifier.NoModifier):
        from PySide6.QtTest import QTest
        QTest.keyClick(widget, key, modifiers)
        self.app.processEvents()

    def current(self):
        return (self.tab.matrix.currentRow(), self.tab.matrix.currentColumn())

    def test_enter_confirms_and_goes_down_and_tab_moves_between_stock_cells(self):
        self.tab.show()
        matrix = self.tab.matrix
        first = matrix.stock_rows[0]
        matrix.edit_stock_row(first)
        editor = self.editor()
        editor.setText("5")
        self.press(editor, Qt.Key.Key_Return)
        self.assertEqual(stock_of(self.service, "Preta", "P"), 5)       # saved
        self.assertEqual(self.current(), (first + 1, 2))                 # next size, editing
        self.assertIsNotNone(self.editor())
        editor = self.editor()
        editor.setText("6")
        self.press(editor, Qt.Key.Key_Tab)
        self.assertEqual(stock_of(self.service, "Preta", "M"), 6)
        self.assertEqual(self.current(), (first + 2, 2))
        self.press(self.editor(), Qt.Key.Key_Backtab)
        self.assertEqual(self.current(), (first + 1, 2))
        self.assertEqual(self.cell("stock", "Preta", "P").text(), "5")   # still shown
        self.assertEqual(self.tab.stock_card.value_label.text(), "11")

    def test_enter_after_the_last_size_of_a_color_jumps_over_the_gap_to_the_next_color(self):
        self.tab.show()
        matrix = self.tab.matrix
        matrix.edit_stock_row(5)                                       # Preta GG
        self.editor().setText("2")
        self.press(self.editor(), Qt.Key.Key_Return)
        self.assertEqual(stock_of(self.service, "Preta", "GG"), 2)
        self.assertEqual(self.current(), (7, 2))                       # Marrom P

    def test_the_total_row_is_never_entered_by_the_keyboard(self):
        self.tab.show()
        matrix = self.tab.matrix
        last = matrix.stock_rows[-1]
        matrix.edit_stock_row(last)
        self.editor().setText("2")
        self.press(self.editor(), Qt.Key.Key_Return)
        self.assertEqual(stock_of(self.service, "Branca", "GG"), 2)
        self.assertLess(self.current()[0], matrix.rowCount() - 1)

    def test_hover_highlights_editable_cells_only(self):
        from dtf_manager.ui.pages.stock_tab import HOVER_BG
        matrix = self.tab.matrix
        row = matrix.stock_rows[0]
        matrix.set_hover((row, 2))
        self.assertEqual(self.cell("stock", "Preta", "P").background().color(), HOVER_BG)
        matrix.set_hover(None)
        self.assertNotEqual(self.cell("stock", "Preta", "P").background().color(), HOVER_BG)
        self.assertEqual(self.cell("stock", "Preta", "P").background().color(),
                         self.cell("stock", "Preta", "P").data(Qt.ItemDataRole.UserRole + 1))

    def test_quick_count_walks_the_stock_cells_and_logs_manual_adjustments(self):
        self.tab.show()
        self.tab.quick_button.click()
        self.assertTrue(self.tab.matrix.quick_mode)
        self.assertTrue(self.tab.quick_banner.isVisibleTo(self.tab))
        self.assertEqual(self.current(), (self.tab.matrix.stock_rows[0], 2))
        for text in ("3", "", "4"):               # P=3, M unchanged (empty -> refused), G=4
            editor = self.editor()
            editor.setText(text)
            self.press(editor, Qt.Key.Key_Return)
        self.assertEqual(stock_of(self.service, "Preta", "P"), 3)
        self.assertEqual(stock_of(self.service, "Preta", "G"), 4)
        self.assertEqual(self.current(), (self.tab.matrix.stock_rows[3], 2))
        self.press(self.editor(), Qt.Key.Key_Escape)                      # leave
        self.assertFalse(self.tab.matrix.quick_mode)
        self.assertFalse(self.tab.quick_button.isChecked())
        self.assertFalse(self.tab.quick_banner.isVisibleTo(self.tab))
        kinds = {(m.kind, m.color, m.size, m.before, m.after) for m in self.service.movements()}
        self.assertIn(("ajuste_manual", "Preta", "P", 0, 3), kinds)
        self.assertIn(("ajuste_manual", "Preta", "G", 0, 4), kinds)
        self.assertEqual(len([m for m in self.service.movements()]), 2)   # unchanged cells log nothing

    def test_quick_count_ends_by_itself_after_the_last_cell(self):
        self.tab.show()
        self.tab.start_quick_count()
        for _ in self.tab.matrix.stock_rows:
            editor = self.editor()
            editor.setText("1")
            self.press(editor, Qt.Key.Key_Return)
        self.assertFalse(self.tab.matrix.quick_mode)
        self.assertFalse(self.tab.quick_button.isChecked())
        self.app.processEvents()                                  # the last refresh is deferred
        self.assertEqual(self.tab.stock_card.value_label.text(), "16")
        self.assertEqual(len(self.service.movements()), 16)

    def test_quick_count_button_toggles_off(self):
        self.tab.show()
        self.tab.quick_button.click()
        self.tab.quick_button.click()
        self.assertFalse(self.tab.matrix.quick_mode)
        self.assertFalse(self.tab.quick_banner.isVisibleTo(self.tab))

    def test_edit_hint_is_larger_and_has_its_own_style(self):
        self.assertEqual(self.tab.hint_label.objectName(), "stockHint")
        self.assertIn("Enter", self.tab.hint_label.text())
        self.assertIn("Esc", self.tab.hint_label.text())

    def test_saved_equivalences_still_change_how_names_are_read(self):
        self.service.replace_aliases([("color", "Black", self.colors["Preta"])])
        self.run_import([make_order("A", ("black,G", 2))])
        self.assertEqual(future_of(self.service, "Preta", "G"), 2)
        self.assertEqual(self.prompts.validations, [])

    def test_there_is_no_copy_list_or_equivalences_button(self):
        self.assertFalse(hasattr(self.tab, "copy_button"))
        self.assertFalse(hasattr(self.tab, "aliases_button"))
        texts = [b.text() for b in self.tab.findChildren(type(self.tab.new_color_button))]
        self.assertNotIn("Equivalências", texts)
        self.assertFalse(any("Copiar" in text for text in texts))

    def test_history_screen_receives_movements_and_imports(self):
        self.run_import(self.orders())
        self.controller.show_history()
        movements, imports = self.prompts.history_calls[0]
        self.assertEqual([m.kind for m in movements], ["importacao"])
        self.assertEqual(len(imports), 1)


class ImportFlowTests(ControllerBase):
    def test_validation_window_only_opens_when_something_is_unrecognized(self):
        self.run_import(self.orders())
        self.assertEqual(self.prompts.validations, [])
        self.run_import([make_order("N", ("P - M", 1, "S-1"))])
        self.assertEqual(len(self.prompts.validations), 1)

    def test_cancelling_the_validation_keeps_the_previous_future(self):
        self.run_import(self.orders(n=3))
        self.prompts.validate_answer = None
        decision = self.controller.review_import(spreadsheet(), [make_order("N", ("P - M", 1, "S"))])
        self.assertFalse(self.controller.apply_import(decision))
        self.assertEqual(future_of(self.service, "Preta", "G"), 3)

    def test_leaving_items_pending_keeps_them_out_and_highlighted(self):
        self.prompts.validate_answer = {}
        self.run_import([make_order("N", ("Preta,G", 2), ("P - M", 3, "S"))])
        self.assertEqual(future_of(self.service, "Preta", "G"), 2)
        self.assertTrue(self.tab.pending_table.isVisibleTo(self.tab))
        self.assertEqual(self.tab.pending_table.rowCount(), 1)
        self.assertIn("6", self.tab.pending_label.text())

    def test_decision_by_sku_is_reused_in_the_next_import(self):
        self.prompts.validate_answer = lambda lines: {
            lines[0].key: LineDecision(color=self.colors["Marrom"])}
        self.run_import([make_order("A", ("P - M", 1, "S-9"))])
        self.assertEqual(future_of(self.service, "Marrom", "P"), 1)
        before = len(self.prompts.validations)
        self.run_import([make_order("B", ("P - M", 4, "S-9"))])
        self.assertEqual(len(self.prompts.validations), before)
        self.assertEqual(future_of(self.service, "Marrom", "P"), 4)

    def test_item_without_sku_makes_no_permanent_mapping(self):
        self.prompts.validate_answer = lambda lines: {
            lines[0].key: LineDecision(color=self.colors["Marrom"])}
        self.run_import([make_order("A", ("P - M", 1, ""))])
        self.assertEqual(self.service.repository.sku_colors(), {})
        self.run_import([make_order("B", ("P - M", 1, ""))])
        self.assertEqual(len(self.prompts.validations), 2)

    def test_importing_replaces_the_future_each_time(self):
        self.run_import(self.orders("A", 3))
        self.run_import(self.orders("B", 2, variation="Bege,M"))
        self.assertEqual(future_of(self.service, "Preta", "G"), 0)
        self.assertEqual(future_of(self.service, "Bege", "M"), 2)

    def test_orders_mounted_before_are_reported_but_still_counted(self):
        self.mounted = {"P0", "P1"}
        self.run_import(self.orders())
        self.assertEqual(self.prompts.notices[0].mounted_count, 2)
        self.assertEqual(future_of(self.service, "Preta", "G"), 3)

    def test_repeated_identical_lines_are_reported(self):
        order = make_order("A", ("Preta,G", 1), ("Preta,G", 1))
        self.run_import([order])
        self.assertTrue(any("repetidas" in text for text in self.prompts.infos))
        self.assertEqual(future_of(self.service, "Preta", "G"), 2)


class DuplicateProtectionFlowTests(ControllerBase):
    def finalized_import(self, prefix="P", n=3):
        orders = self.orders(prefix, n)
        file = spreadsheet()
        self.service.bulk_add(50)
        self.run_import(orders, file)
        self.assertTrue(self.controller.finalize())
        self.prompts.notices.clear()
        return orders, file

    def test_new_spreadsheet_shows_no_notice(self):
        self.run_import(self.orders("A"))
        self.run_import(self.orders("B"))
        self.assertEqual(self.prompts.notices, [])

    def test_reimporting_after_finalizing_does_not_create_future_for_finalized_orders(self):
        orders, _ = self.finalized_import()
        self.run_import(orders, spreadsheet())                           # same orders, new name
        notice = self.prompts.notices[0]
        self.assertEqual(notice.finalized_count, 3)
        self.assertTrue(notice.duplicate.finalized)
        self.assertEqual(future_of(self.service, "Preta", "G"), 0)

    def test_including_finalized_orders_again_creates_the_future(self):
        orders, _ = self.finalized_import()
        self.prompts.notice_choice = NoticeChoice("import", include_finalized=True)
        self.run_import(orders, spreadsheet())
        self.assertEqual(future_of(self.service, "Preta", "G"), 3)

    def test_new_order_in_the_same_spreadsheet_counts_normally(self):
        orders, _ = self.finalized_import()
        self.run_import(orders + [make_order("NEW", ("Bege,M", 2))], spreadsheet())
        self.assertEqual(future_of(self.service, "Bege", "M"), 2)
        self.assertEqual(future_of(self.service, "Preta", "G"), 0)

    def test_same_file_again_is_detected_by_hash(self):
        file = spreadsheet()
        self.run_import(self.orders("A", 4), file)
        self.run_import(self.orders("Z", 4), file)                       # same bytes
        notice = self.prompts.notices[0]
        self.assertTrue(notice.duplicate.same_file)
        self.assertFalse(notice.duplicate.finalized)

    def test_same_orders_with_another_file_name(self):
        self.run_import(self.orders("A", 5), spreadsheet())
        self.run_import(self.orders("A", 5), spreadsheet())
        self.assertFalse(self.prompts.notices[0].duplicate.same_file)

    def test_cancel_import_leaves_everything_untouched(self):
        self.run_import(self.orders("A", 5), spreadsheet())
        before = self.service.snapshot().future
        self.prompts.notice_choice = NoticeChoice("cancel")
        self.assertIsNone(self.controller.review_import(spreadsheet(), self.orders("A", 5)))
        self.assertEqual(self.service.snapshot().future, before)

    def test_import_anyway_replaces_the_future_with_the_same_orders(self):
        self.run_import(self.orders("A", 5), spreadsheet())
        self.prompts.notice_choice = NoticeChoice("import")
        self.run_import(self.orders("A", 5), spreadsheet())
        self.assertEqual(future_of(self.service, "Preta", "G"), 5)

    def test_import_only_new_orders_from_a_mixed_spreadsheet(self):
        self.run_import(self.orders("A", 10), spreadsheet())
        mixed = self.orders("A", 10) + [make_order("NEW", ("Bege,M", 3))]
        self.prompts.notice_choice = NoticeChoice("only_new")
        decision = self.controller.review_import(spreadsheet(), mixed)
        self.assertTrue(self.prompts.notices[0].duplicate.mixed)
        self.assertEqual([o.platform_order_number for o in decision.orders], ["NEW"])
        self.controller.apply_import(decision)
        self.assertEqual(future_of(self.service, "Bege", "M"), 3)
        self.assertEqual(future_of(self.service, "Preta", "G"), 0)


class FinalizeFlowTests(ControllerBase):
    def setUp(self):
        super().setUp()
        self.enabled = []
        self.controller.changed.connect(self.enabled.append)

    def test_nothing_happens_without_future(self):
        self.assertFalse(self.controller.finalize())
        self.assertEqual(self.prompts.finalize_summaries, [])
        self.assertFalse(self.controller.has_future)

    def test_confirmed_finalize_deducts_and_clears(self):
        self.service.bulk_add(10)
        self.run_import(self.orders(n=4))
        self.assertTrue(self.controller.finalize())
        self.assertEqual(stock_of(self.service, "Preta", "G"), 6)
        self.assertEqual(self.cell("stock", "Preta", "G").text(), "6")
        self.assertFalse(self.controller.has_future)
        self.assertFalse(self.enabled[-1])

    def test_declining_changes_nothing(self):
        self.service.bulk_add(10)
        self.run_import(self.orders(n=4))
        self.prompts.finalize_answer = False
        self.assertFalse(self.controller.finalize())
        self.assertEqual(stock_of(self.service, "Preta", "G"), 10)
        self.assertTrue(self.controller.has_future)

    def test_shortage_and_pending_are_shown_in_the_summary(self):
        self.prompts.validate_answer = {}
        self.run_import([make_order("A", ("Preta,G", 3), ("P - M", 1, "S"))])
        self.controller.finalize()
        summary = self.prompts.finalize_summaries[0]
        self.assertEqual([(r.color, r.size, r.shortage) for r in summary.shortages],
                         [("Preta", "G", 3)])
        self.assertEqual(summary.pending, 2)
        self.assertEqual(stock_of(self.service, "Preta", "G"), 0)
        movement = [m for m in self.service.movements() if m.kind == "finalizacao"][0]
        self.assertIn("faltaram 3", movement.note)

    def test_button_is_disabled_during_the_operation_and_double_click_is_ignored(self):
        self.service.bulk_add(10)
        self.run_import(self.orders(n=4))
        seen = []

        def second_click():
            seen.append((self.controller.busy, self.enabled[-1]))
            seen.append(self.controller.finalize())            # a second click while running

        self.prompts.on_finalize = second_click
        self.assertTrue(self.controller.finalize())
        self.assertEqual(seen, [(True, False), False])
        self.assertEqual(stock_of(self.service, "Preta", "G"), 6)   # deducted once
        self.assertEqual(len(self.prompts.finalize_summaries), 1)

    def test_state_survives_closing_and_reopening(self):
        self.service.bulk_add(10)
        self.run_import(self.orders(n=2))
        reopened = StockController(make_service(self.path)[0], FakePrompts(), StockTab())
        self.assertTrue(reopened.has_future)
        self.assertEqual(reopened.service.snapshot().stock[(self.colors["Preta"], self.sizes["G"])], 10)
        self.controller.finalize()
        again = StockController(make_service(self.path)[0], FakePrompts(), StockTab())
        self.assertFalse(again.has_future)
        self.assertEqual(again.service.snapshot().stock[(self.colors["Preta"], self.sizes["G"])], 8)


class DialogTests(ControllerBase):
    def test_import_notice_buttons_and_default(self):
        from dtf_manager.models.stock import DuplicateInfo, ImportNotice, ImportRecord
        record = ImportRecord(1, "2026-11-20T10:30:00-03:00", "a.xlsx", "h", 10,
                              tuple(f"P{i}" for i in range(10)), "2026-11-20T11:00:00-03:00")
        duplicate = DuplicateInfo(record, False, 0.9, ("N1",), 10)
        dialog = ImportNoticeDialog(ImportNotice(duplicate, 3, "20/11", 2))
        self.assertTrue(dialog.cancel_button.isDefault())          # finalized: safe default
        self.assertIsNotNone(dialog.only_new_button)               # mixed
        self.assertTrue(any("finalizada no estoque" in label.text()
                            for label in dialog.findChildren(QLabel)))
        dialog.include_finalized.setChecked(True)
        dialog.only_new_button.click()
        self.assertEqual((dialog.choice.action, dialog.choice.include_finalized), ("only_new", True))
        again = ImportNoticeDialog(ImportNotice(duplicate, 0, "", 0))
        again.import_button.click()
        self.assertEqual(again.choice.action, "import")
        pending = DuplicateInfo(ImportRecord(2, record.at, "b.xlsx", "h2", 5, ("A",), None),
                                True, 1.0, (), 5)
        notice = ImportNoticeDialog(ImportNotice(pending, 0, "", 0))
        self.assertTrue(notice.import_button.isDefault())          # not finalized: default import
        self.assertIsNone(notice.only_new_button)
        notice.cancel_button.click()
        self.assertEqual(notice.choice.action, "cancel")

    def test_validation_dialog_apply_to_equals_and_buttons(self):
        orders = [make_order("A", ("P - M", 2, "S-1"), ("G", 1, "S-2")),
                  make_order("B", ("P - M", 1, "S-1"))]
        prep = self.service.prepare_import(orders)
        snap = self.service.snapshot()
        dialog = ValidationDialog(prep.lines, snap.colors, snap.sizes)
        self.assertEqual(len(prep.lines), 2)
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertTrue(dialog.pending_button.isEnabled())
        dialog.color_boxes[0].setCurrentIndex(dialog.color_boxes[0].findData(self.colors["Bege"]))
        dialog.apply_to_equals(0)
        self.assertEqual(dialog.color_boxes[1].currentData(), self.colors["Bege"]
                         if prep.lines[1].sku == prep.lines[0].sku else None)
        for box in dialog.color_boxes:
            box.setCurrentIndex(box.findData(self.colors["Bege"]))
        self.assertTrue(dialog.confirm_button.isEnabled())
        decisions = dialog.decisions()
        self.assertEqual(len(decisions), 2)
        self.assertTrue(all(d.remember for d in decisions.values()))
        dialog.add_color_choice("Azul", 0)
        self.assertEqual(dialog.color_boxes[0].currentData(), "Azul")
        self.assertIn("Azul", [dialog.color_boxes[1].itemData(i) for i in range(dialog.color_boxes[1].count())])

    def png_bytes(self):
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QColor, QImage
        image = QImage(20, 20, QImage.Format.Format_RGB32)
        image.fill(QColor("#cc3344"))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(data)

    def test_validation_dialog_shows_the_spreadsheet_image_and_no_size_column(self):
        from dataclasses import replace
        items = [replace(make_item("A", "P - M", 2, "S-1"), product_image_url="https://img/x.png"),
                 replace(make_item("B", "G", 1, "S-2"), product_image_url="https://img/x.png"),
                 make_item("C", "GG", 1, "S-3")]                          # no image link at all
        prep = self.service.prepare_import([make_order("A", items[0]), make_order("B", items[1]),
                                            make_order("C", items[2])])
        self.assertEqual(sorted(line.image_url for line in prep.lines),
                         ["", "https://img/x.png", "https://img/x.png"])
        requests, png = [], self.png_bytes()
        snap = self.service.snapshot()
        dialog = ValidationDialog(prep.lines, snap.colors, snap.sizes,
                                  image_fetcher=lambda url, done: (requests.append(url), done(png)))
        headers = [dialog.table.horizontalHeaderItem(c).text() for c in range(dialog.table.columnCount())]
        self.assertEqual(headers[0], "IMAGEM")
        self.assertNotIn("TAM.", headers)
        self.assertTrue(dialog.table.isColumnHidden(6) and dialog.table.isColumnHidden(7))
        self.assertEqual(requests, ["https://img/x.png"])               # the second row reuses it
        shown = [bool(label.pixmap() and not label.pixmap().isNull()) for label in dialog.image_labels]
        self.assertEqual(sorted(shown), [False, True, True])
        self.assertEqual(dialog.image_labels[[ln.image_url for ln in dialog.lines].index("")].text(),
                         "sem imagem")

    def test_validation_dialog_failed_image_keeps_the_placeholder_and_sizes_show_when_needed(self):
        from dataclasses import replace
        item = replace(make_item("A", "Preta", 1, "S-1"), product_image_url="https://img/bad.png")
        prep = self.service.prepare_import([make_order("A", item)])
        snap = self.service.snapshot()
        dialog = ValidationDialog(prep.lines, snap.colors, snap.sizes,
                                  image_fetcher=lambda url, done: done(None))
        self.assertEqual(dialog.image_labels[0].text(), "sem imagem")
        self.assertFalse(dialog.table.isColumnHidden(6))               # this line needs a size

    def test_validation_dialog_size_and_no_sku_cannot_be_remembered(self):
        prep = self.service.prepare_import([make_order("A", ("Preta", 1, ""))])
        snap = self.service.snapshot()
        dialog = ValidationDialog(prep.lines, snap.colors, snap.sizes)
        self.assertFalse(dialog.color_boxes[0].isEnabled())
        self.assertFalse(dialog.remember_boxes[0].isEnabled())
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.size_boxes[0][0].setCurrentIndex(1)
        dialog.size_boxes[0][1].setCurrentIndex(3)
        self.assertTrue(dialog.confirm_button.isEnabled())
        decision = next(iter(dialog.decisions().values()))
        self.assertEqual(len(decision.sizes), 2)

    def test_finalize_dialog_requires_acknowledgement_with_shortage(self):
        self.run_import([make_order("A", ("Preta,G", 3))])
        summary = self.service.finalize_summary()
        dialog = FinalizeDialog(summary)
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.acknowledge.setChecked(True)
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.service.bulk_add(10)
        calm = FinalizeDialog(self.service.finalize_summary())
        self.assertIsNone(calm.acknowledge)
        self.assertTrue(calm.confirm_button.isEnabled())

    def test_history_dialog_lists_import_and_finalize_movements(self):
        self.service.bulk_add(5)
        self.run_import(self.orders(n=2))
        self.controller.finalize()
        dialog = StockHistoryDialog(self.service.movements(), self.service.imports())
        kinds = {dialog.movements_table.item(r, 2).text()
                 for r in range(dialog.movements_table.rowCount())}
        self.assertIn("Importação (futuro)", kinds)
        self.assertIn("Finalização", kinds)
        index = dialog.filter.findData("finalizacao")
        dialog.filter.setCurrentIndex(index)
        self.assertEqual({dialog.movements_table.item(r, 2).text()
                          for r in range(dialog.movements_table.rowCount())}, {"Finalização"})
        self.assertEqual(dialog.imports_table.rowCount(), 1)
        self.assertTrue(dialog.imports_table.item(0, 3).text().startswith("Sim"))

    def test_bulk_dialog_summary(self):
        snap = self.service.snapshot()
        bulk = BulkAddDialog(snap.colors, snap.sizes, self.service.preview_bulk)
        bulk.quantity.setValue(4)
        bulk.color.setCurrentIndex(1)
        for size, box in bulk.size_boxes[2:]:
            box.setChecked(False)
        quantity, color_id, sizes = bulk.request()
        self.assertEqual((quantity, color_id, len(sizes)), (4, self.colors["Preta"], 2))
        self.assertIn("2 combinação", bulk.summary())


class MainWindowStockTests(unittest.TestCase):
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
        cls.prompts = FakePrompts()
        cls.window.stock_controller.prompts = cls.prompts

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        cls.temp.cleanup()

    def test_three_tabs_and_the_dtf_tab_keeps_its_pages(self):
        tabs = self.window.main_tabs
        self.assertEqual([tabs.tabText(i) for i in range(3)],
                         ["DTF", "Estoque de camisetas", "Estoque de estampas"])
        self.assertIs(tabs.widget(0), self.window.pages)
        self.assertGreaterEqual(self.window.pages.count(), 6)        # all DTF pages intact
        self.assertNotEqual(self.window.pages.indexOf(self.window.editor_page), -1)
        self.assertIsInstance(self.window.prints_tab, ArtStockTab)       # no longer "Em breve"
        self.assertIs(tabs.widget(2), self.window.prints_tab)
        self.assertIs(tabs.widget(1), self.window.stock_tab)

    def test_finalize_button_sits_below_export_and_follows_the_future(self):
        settings = self.window.settings
        layout = settings.export_button.parentWidget().layout()
        order = [layout.itemAt(i).widget() for i in range(layout.count())
                 if layout.itemAt(i).widget() is not None]
        self.assertLess(order.index(settings.export_button), order.index(settings.finalize_button))
        self.assertFalse(settings.finalize_button.isEnabled())
        controller = self.window.stock_controller
        orders = [make_order("W1", ("Preta,G", 2))]
        decision = controller.review_import(spreadsheet(), orders)
        controller.apply_import(decision)
        self.assertTrue(settings.finalize_button.isEnabled())
        settings.finalize_button.click()
        self.assertFalse(settings.finalize_button.isEnabled())
        self.assertEqual(len(self.prompts.finalize_summaries), 1)

    # ---- end to end: the real import button flow with a real .xlsx ---------------------
    def write_xlsx(self, rows, name):
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Nº de Pedido da Plataforma", "Nome do Anúncio", "ID do Anúncio", "SKU",
                      "Variação", "ID da Variante", "Qtd. do Produto"])
        for number, variation, sku, quantity in rows:
            sheet.append([number, "Camiseta", "L1", sku, variation, "V1", quantity])
        path = Path(self.temp.name) / name
        workbook.save(path)
        return path

    def import_file(self, path):
        with patch("dtf_manager.ui.main_window.QFileDialog.getOpenFileName",
                   return_value=(str(path), "")),              patch("dtf_manager.ui.main_window.QMessageBox.warning"),              patch("dtf_manager.ui.main_window.ExistingOperationDialog"):
            self.window._import_orders()

    def test_import_button_flow_computes_the_future_after_the_operation_starts(self):
        controller = self.window.stock_controller
        self.prompts.notices.clear()
        path = self.write_xlsx([("E1", "Preto,M - G", "SKU-E", 2), ("E2", "Preta,P", "SKU-F", 1)],
                               "e2e.xlsx")
        self.import_file(path)
        snapshot = controller.service.snapshot()
        colors = {c.name: c.id for c in snapshot.colors}
        sizes = {s.name: s.id for s in snapshot.sizes}
        self.assertEqual(snapshot.future[(colors["Preta"], sizes["M"])], 2)
        self.assertEqual(snapshot.future[(colors["Preta"], sizes["G"])], 2)
        self.assertEqual(snapshot.future[(colors["Preta"], sizes["P"])], 1)
        self.assertEqual(len(self.window.order_import_state.imported_orders), 2)
        # the same file again: warning first; cancelling leaves the project as it was
        self.prompts.notice_choice = NoticeChoice("cancel")
        before = controller.service.snapshot().future
        self.import_file(path)
        self.assertEqual(len(self.prompts.notices), 1)
        self.assertTrue(self.prompts.notices[0].duplicate.same_file)
        self.assertEqual(controller.service.snapshot().future, before)
        self.prompts.notice_choice = NoticeChoice("import")
        controller.service.finalize()

    def test_restoring_an_operation_does_not_double_count(self):
        controller = self.window.stock_controller
        orders = [make_order("R1", ("Bege,G", 3))]
        controller.apply_import(controller.review_import(spreadsheet(), orders))
        before = controller.service.snapshot().future
        controller.sync_loaded_orders(orders)                          # same set: nothing to do
        self.assertEqual(controller.service.snapshot().future, before)
        controller.service.finalize()
        controller.sync_loaded_orders(orders)                          # finalized: stays at zero
        self.assertFalse(controller.service.snapshot().has_future)

    # ---- operation card: cancel and finalize ----------------------------------------------
    def reset_operation(self):
        window = self.window
        if window.active_operation is not None:
            window._end_active_operation()
        window.stock_controller.cancel_import()
        self.prompts.finalize_answer = True
        self.prompts.notice_choice = NoticeChoice("import")
        self.prompts.notices.clear()
        self.prompts.finalize_summaries.clear()

    def start_operation(self, name, rows):
        path = self.write_xlsx(rows, name)
        self.import_file(path)
        self.assertIsNotNone(self.window.active_operation)
        return path

    def answer(self, button):
        return patch("dtf_manager.ui.main_window.QMessageBox.question", return_value=button)

    def test_tabs_are_centered(self):
        from PySide6.QtCore import QPoint
        self.window.resize(1400, 800)
        self.window.show()
        self.app.processEvents()
        bar = self.window.main_tabs.tabBar()
        first = bar.tabRect(0).left()
        last = bar.tabRect(bar.count() - 1).right()
        middle = bar.mapTo(self.window.main_tabs, QPoint((first + last) // 2, 0)).x()
        self.assertAlmostEqual(middle, self.window.main_tabs.width() / 2, delta=40)

    def test_operation_card_has_only_continue_and_cancel_buttons(self):
        self.reset_operation()
        self.start_operation("card.xlsx", [("K1", "Preta,G", "SKU-K", 1)])
        settings = self.window.settings
        self.assertTrue(settings.active_operation_card.isVisibleTo(settings))
        self.assertEqual(settings.cancel_operation_button.text(), "CANCELAR")
        self.assertFalse(hasattr(settings, "finalize_operation_button"))
        self.reset_operation()
        self.assertFalse(settings.active_operation_card.isVisibleTo(settings))

    def test_cancel_discards_the_work_and_the_same_file_can_be_loaded_again(self):
        from PySide6.QtWidgets import QMessageBox
        self.reset_operation()
        controller = self.window.stock_controller
        path = self.start_operation("cancel.xlsx", [("C1", "Preto,M", "SKU-C", 2),
                                                   ("C2", "Preta,G", "SKU-D", 1)])
        self.assertTrue(controller.has_future)
        with self.answer(QMessageBox.StandardButton.No):
            self.window.settings.cancel_operation_button.click()           # declined
        self.assertIsNotNone(self.window.active_operation)
        self.assertTrue(controller.has_future)
        with self.answer(QMessageBox.StandardButton.Yes):
            self.window.settings.cancel_operation_button.click()
        self.assertIsNone(self.window.active_operation)
        self.assertEqual(self.window.order_import_state.imported_orders, ())
        self.assertFalse(controller.has_future)
        self.assertFalse(self.window.settings.active_operation_card.isVisibleTo(self.window.settings))
        self.assertFalse(self.window.settings.finalize_button.isEnabled())
        self.prompts.notices.clear()
        self.import_file(path)                                              # again, from zero
        self.assertEqual(self.prompts.notices, [])                          # no "already imported"
        self.assertEqual(len(self.window.order_import_state.imported_orders), 2)
        self.assertTrue(controller.has_future)
        self.reset_operation()

    def test_sidebar_finalize_button_deducts_the_stock_and_zeroes_the_future(self):
        self.reset_operation()
        controller = self.window.stock_controller
        service = controller.service
        service.bulk_add(5)
        colors = {c.name: c.id for c in service.snapshot().colors}
        sizes = {s.name: s.id for s in service.snapshot().sizes}
        self.start_operation("finalize.xlsx", [("F1", "Preta,G", "SKU-F", 2)])
        before = service.snapshot().stock[(colors["Preta"], sizes["G"])]
        self.prompts.finalize_answer = False
        self.window.settings.finalize_button.click()                        # declined in the summary
        self.assertEqual(service.snapshot().stock[(colors["Preta"], sizes["G"])], before)
        self.prompts.finalize_answer = True
        self.window.settings.finalize_button.click()
        self.assertEqual(service.snapshot().stock[(colors["Preta"], sizes["G"])], before - 2)
        self.assertFalse(controller.has_future)
        self.assertEqual(len(self.prompts.finalize_summaries), 2)
        self.reset_operation()



if __name__ == "__main__":
    unittest.main()
