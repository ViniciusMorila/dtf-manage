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
from dtf_manager.ui.pages.stock_tab import NEGATIVE, StockTab
from dtf_manager.ui.styles import APP_STYLE
from dtf_manager.ui.widgets.stock_dialogs import (
    AliasesDialog, BulkAddDialog, FinalizeDialog, ImportNoticeDialog, StockHistoryDialog,
    ValidationDialog,
)
from tests.stock_fakes import (
    future_of, ids, make_order, make_service, stock_of,
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
        self.aliases_answer = None
        self.history_calls = []

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

    def edit_aliases(self, colors, sizes, aliases):
        return self.aliases_answer


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

    def cell(self, table, color, size):
        colors = [c.name for c in self.service.snapshot().colors]
        sizes = [s.name for s in self.service.snapshot().sizes]
        return table.item(colors.index(color), sizes.index(size))


class TabTests(ControllerBase):
    def test_three_views_with_zero_stock_and_the_balance(self):
        self.assertEqual(self.tab.stock_table.rowCount(), 4)
        self.assertEqual(self.tab.stock_table.columnCount(), 4)
        self.assertEqual(self.cell(self.tab.stock_table, "Preta", "G").text(), "0")
        self.service.bulk_add(2)
        self.run_import(self.orders(n=5, variation="Preta,G"))           # needs 5, has 2
        self.assertEqual(self.cell(self.tab.future_table, "Preta", "G").text(), "5")
        balance = self.cell(self.tab.balance_table, "Preta", "G")
        self.assertEqual(balance.text(), "-3")
        self.assertEqual(balance.foreground().color(), NEGATIVE)
        self.assertEqual(self.cell(self.tab.balance_table, "Bege", "M").text(), "2")
        self.assertFalse(bool(self.cell(self.tab.future_table, "Preta", "G").flags()
                              & Qt.ItemFlag.ItemIsEditable))
        self.assertTrue(bool(self.cell(self.tab.stock_table, "Preta", "G").flags()
                             & Qt.ItemFlag.ItemIsEditable))
        self.tab.view_buttons[2].click()
        self.assertIs(self.tab.pages.currentWidget(), self.tab.balance_table)

    def test_editing_a_stock_cell_saves_and_invalid_text_is_refused(self):
        self.cell(self.tab.stock_table, "Preta", "M").setText("7")
        self.app.processEvents()
        self.assertEqual(stock_of(self.service, "Preta", "M"), 7)
        self.cell(self.tab.stock_table, "Preta", "M").setText("-4")
        self.app.processEvents()
        self.assertEqual(stock_of(self.service, "Preta", "M"), 7)
        self.assertEqual(self.cell(self.tab.stock_table, "Preta", "M").text(), "7")
        self.assertEqual(len(self.prompts.warnings), 1)

    def test_new_color_and_size_refuse_duplicates(self):
        self.prompts.names = ["Azul"]
        self.controller.new_color()
        self.assertEqual(self.tab.stock_table.rowCount(), 5)
        self.prompts.names = ["PRETA"]
        self.controller.new_color()
        self.assertEqual(self.tab.stock_table.rowCount(), 5)
        self.assertEqual(len(self.prompts.warnings), 1)
        self.prompts.names = ["xg"]
        self.controller.new_size()
        self.assertEqual(self.tab.stock_table.columnCount(), 5)
        self.prompts.names = [None]
        self.controller.new_size()                                       # cancelled
        self.assertEqual(self.tab.stock_table.columnCount(), 5)

    def test_bulk_add_through_the_controller(self):
        self.prompts.bulk_answer = (3, self.colors["Bege"], None)
        self.controller.bulk_add()
        self.assertEqual(self.cell(self.tab.stock_table, "Bege", "GG").text(), "3")
        self.assertEqual(self.cell(self.tab.stock_table, "Preta", "GG").text(), "0")
        self.prompts.bulk_answer = None
        self.controller.bulk_add()
        self.assertEqual(stock_of(self.service, "Bege", "GG"), 3)

    def test_separation_list_checkbox_and_missing_text(self):
        self.service.set_stock(self.colors["Preta"], self.sizes["G"], "2")
        self.run_import(self.orders(n=5, variation="Preta,G") + [make_order("X", ("Bege,M", 1))])
        table = self.tab.separation_table
        self.assertEqual(table.rowCount(), 2)
        row = [table.item(r, 0).text() for r in range(2)].index("Preta")
        self.assertEqual([table.item(row, c).text() for c in range(1, 5)], ["G", "5", "2", "3"])
        table.item(row, 5).setCheckState(Qt.CheckState.Checked)
        snapshot = self.service.snapshot()
        self.assertTrue(any(r.separated for r in snapshot.separation))
        text = self.controller.missing_text()
        self.assertIn("Preta G: 3", text)
        self.assertIn("Bege M: 1", text)
        self.assertNotIn("Total: 5", text)
        self.assertIn("Total: 4", text)

    def test_aliases_are_editable_and_change_how_names_are_read(self):
        self.prompts.aliases_answer = [("color", "Black", self.colors["Preta"])]
        self.controller.edit_aliases()
        self.run_import([make_order("A", ("black,G", 2))])
        self.assertEqual(future_of(self.service, "Preta", "G"), 2)
        self.assertEqual(self.prompts.validations, [])

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
        self.assertEqual(self.cell(self.tab.stock_table, "Preta", "G").text(), "6")
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
        kinds = {dialog.movements_table.item(r, 1).text()
                 for r in range(dialog.movements_table.rowCount())}
        self.assertIn("Importação (futuro)", kinds)
        self.assertIn("Finalização", kinds)
        index = dialog.filter.findData("finalizacao")
        dialog.filter.setCurrentIndex(index)
        self.assertEqual({dialog.movements_table.item(r, 1).text()
                          for r in range(dialog.movements_table.rowCount())}, {"Finalização"})
        self.assertEqual(dialog.imports_table.rowCount(), 1)
        self.assertTrue(dialog.imports_table.item(0, 3).text().startswith("Sim"))

    def test_bulk_dialog_summary_and_aliases_dialog(self):
        snap = self.service.snapshot()
        bulk = BulkAddDialog(snap.colors, snap.sizes, self.service.preview_bulk)
        bulk.quantity.setValue(4)
        bulk.color.setCurrentIndex(1)
        for size, box in bulk.size_boxes[2:]:
            box.setChecked(False)
        quantity, color_id, sizes = bulk.request()
        self.assertEqual((quantity, color_id, len(sizes)), (4, self.colors["Preta"], 2))
        self.assertIn("2 combinação", bulk.summary())
        dialog = AliasesDialog(snap.colors, snap.sizes, self.service.repository.aliases())
        self.assertEqual(dialog.table.rowCount(), 2)
        dialog.add_row("size", "extra grande", self.sizes["GG"])
        self.assertIn(("size", "extra grande", self.sizes["GG"]), dialog.rows())


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
        self.assertEqual(self.window.prints_tab.text(), "Em breve")
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


if __name__ == "__main__":
    unittest.main()
