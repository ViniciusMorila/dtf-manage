"""Operation in progress: it stays after the roll is mounted, FINALIZAR PEDIDO ends it, mounting again
replaces the old roll, and importing the same spreadsheet again alerts and redoes the futuro."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from dtf_manager.models.stock import DuplicateInfo, ImportNotice, ImportRecord
from dtf_manager.services.active_operation_repository import ActiveOperationStorageError
from dtf_manager.ui.styles import APP_STYLE
from dtf_manager.ui.widgets.stock_dialogs import ImportNoticeDialog


def record(finalized):
    return ImportRecord(1, "2026-11-24T10:00:00", "pedidos.xlsx", "hash", 3, ("A", "B", "C"),
                        "2026-11-24T11:00:00" if finalized else None)


class FinalizeEndsTheOperationTests(unittest.TestCase):
    def caller(self, operation):
        return SimpleNamespace(active_operation=operation, _end_active_operation=Mock(), statusBar=Mock())

    def test_finalizing_ends_the_operation_so_its_card_goes_away(self):
        from dtf_manager.ui.main_window import MainWindow
        caller = self.caller(object())
        MainWindow._on_order_finalized(caller)
        caller._end_active_operation.assert_called_once()

    def test_without_an_operation_there_is_nothing_to_end(self):
        from dtf_manager.ui.main_window import MainWindow
        caller = self.caller(None)
        MainWindow._on_order_finalized(caller)
        caller._end_active_operation.assert_not_called()

    def test_a_storage_error_is_shown_and_does_not_crash(self):
        from dtf_manager.ui.main_window import MainWindow
        caller = self.caller(object())
        caller._end_active_operation.side_effect = ActiveOperationStorageError("no disk")
        status = Mock()
        caller.statusBar = lambda: status
        MainWindow._on_order_finalized(caller)
        status.showMessage.assert_called_once()


class MountTheRollTests(unittest.TestCase):
    """_apply_reviewed_plan with the heavy collaborators replaced by mocks."""

    def setUp(self):
        self.events = []
        entries = [SimpleNamespace(file_path=Path("a.png"), width_cm=5, height_cm=5, quantity=2, color_mode="x")]
        roll = Mock()
        roll.artwork_quantity.return_value = 2
        roll.regroup_artworks.side_effect = lambda: self.events.append("regroup")
        panel = Mock()
        panel.artwork_entries.return_value = ((Path("old.png"), 1, 1, 1),)
        panel.add_configured_artwork.side_effect = lambda *a, **k: self.events.append("add") or "key"
        history = Mock()
        history.next_batch_number.return_value = 7
        history.save.return_value = SimpleNamespace(batch_number=7, mounted_at="t", created_at="t")
        self.caller = SimpleNamespace(
            production_review_page=SimpleNamespace(
                validation_result=SimpleNamespace(is_valid=True, errors=()), reviewed_orders=[]),
            _is_building_order=False, roll_view=roll, artwork_panel=panel,
            orders_dashboard=Mock(), pages=Mock(), editor_page=Mock(), statusBar=Mock(),
            production_history_repository=history, processed_order_repository=Mock(),
            settings=SimpleNamespace(
                width_input=SimpleNamespace(value=lambda: 58), gap_mm=5,
                dpi_combo=SimpleNamespace(currentText=lambda: "300"),
                auto_split=SimpleNamespace(isChecked=lambda: True),
                length_input=SimpleNamespace(value=lambda: 7.0)),
            active_operation=object(), active_operation_repository=Mock(),
            order_import_state=SimpleNamespace(all_items=()),
            _clear_roll_project=Mock(side_effect=lambda: self.events.append("clear")),
            _set_roll_canvas_visible=Mock(), _checkpoint_current_operation=Mock(),
            _refresh_active_operation_card=Mock())
        self.entries = entries
        self.patches = [
            patch("dtf_manager.ui.main_window.prepare_print_plan_for_roll", return_value=entries),
            patch("dtf_manager.ui.main_window.create_production_batch_snapshot", return_value=object()),
            patch("dtf_manager.ui.main_window.BatchRollSettingsSnapshot", return_value=object()),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def mount(self, answer):
        """answer: 'clear' = LIMPAR / MONTAR, 'cancel' = CANCELAR."""
        from dtf_manager.ui.main_window import MainWindow
        cancel, clear = Mock(name="cancel"), Mock(name="clear")
        box = Mock()
        box.addButton.side_effect = [cancel, clear]
        box.clickedButton.return_value = clear if answer == "clear" else cancel
        with patch("dtf_manager.ui.main_window.QMessageBox") as message_box:
            message_box.return_value = box
            MainWindow._apply_reviewed_plan(self.caller, SimpleNamespace())
        return box

    def test_mounting_again_clears_the_previous_roll_before_loading_the_new_one(self):
        self.caller.roll_view.has_artworks = True                  # the roll from the first mounting
        box = self.mount("clear")
        box.exec.assert_called_once()                              # the user is warned first
        self.assertEqual(self.events, ["clear", "add", "regroup"])  # old roll out, new arts in
        self.caller.pages.setCurrentWidget.assert_called_with(self.caller.editor_page)

    def test_cancelling_the_warning_keeps_the_previous_roll(self):
        self.caller.roll_view.has_artworks = True
        self.mount("cancel")
        self.assertEqual(self.events, [])
        self.caller._clear_roll_project.assert_not_called()
        self.assertFalse(self.caller._is_building_order)            # the screen is not left locked

    def test_an_empty_roll_is_mounted_without_any_warning(self):
        self.caller.roll_view.has_artworks = False
        box = self.mount("clear")
        box.exec.assert_not_called()
        self.assertEqual(self.events, ["add", "regroup"])

    def test_the_operation_stays_active_after_the_roll_is_mounted(self):
        self.caller.roll_view.has_artworks = False
        self.mount("clear")
        self.caller.active_operation_repository.clear_active.assert_not_called()
        self.assertIsNotNone(self.caller.active_operation)
        self.caller._checkpoint_current_operation.assert_called_once_with("orders_dashboard")


class SameSpreadsheetAgainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE)

    def dialog(self, duplicate, finalized_count=3):
        notice = ImportNotice(duplicate, finalized_count, "24/11" if finalized_count else "", 0)
        dialog = ImportNoticeDialog(notice)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def same_file(self, finalized=True):
        return DuplicateInfo(record(finalized), True, 1.0, (), 3)

    def test_the_same_file_warns_that_the_futuro_is_redone_and_counts_finalized_orders_again(self):
        dialog = self.dialog(self.same_file())
        texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn("zerado e refeito", texts)
        self.assertIn("FINALIZAR PEDIDO", texts)
        self.assertTrue(dialog.include_finalized.isChecked())
        dialog.import_button.click()
        self.assertEqual((dialog.choice.action, dialog.choice.include_finalized), ("import", True))

    def test_the_user_can_still_refuse_to_count_the_finalized_orders_again(self):
        dialog = self.dialog(self.same_file())
        dialog.include_finalized.setChecked(False)
        dialog.import_button.click()
        self.assertEqual((dialog.choice.action, dialog.choice.include_finalized), ("import", False))

    def test_a_different_spreadsheet_keeps_finalized_orders_out_by_default(self):
        dialog = self.dialog(None)
        self.assertFalse(dialog.include_finalized.isChecked())
        dialog.import_button.click()
        self.assertEqual(dialog.choice.include_finalized, False)

    def test_cancelling_changes_nothing(self):
        dialog = self.dialog(self.same_file())
        dialog.cancel_button.click()
        self.assertEqual(dialog.choice.action, "cancel")

    def test_continuing_the_open_operation_also_redoes_the_futuro_that_was_accepted(self):
        from dtf_manager.ui.main_window import MainWindow
        decision = object()
        stock = Mock()
        caller = SimpleNamespace(_pending_stock_import=decision, stock_controller=stock)
        caller._continue_active_operation = lambda: setattr(caller, "_pending_stock_import", None)
        MainWindow._continue_keeping_the_import(caller)
        stock.apply_import.assert_called_once_with(decision)

    def test_continuing_without_an_accepted_import_changes_no_futuro(self):
        from dtf_manager.ui.main_window import MainWindow
        stock = Mock()
        caller = SimpleNamespace(_pending_stock_import=None, stock_controller=stock,
                                 _continue_active_operation=Mock())
        MainWindow._continue_keeping_the_import(caller)
        caller._continue_active_operation.assert_called_once()
        stock.apply_import.assert_not_called()


if __name__ == "__main__":
    unittest.main()
