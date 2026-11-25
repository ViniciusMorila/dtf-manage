"""Export history: one summary per finished export (weekday, length used, project value)."""
from datetime import datetime
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from dtf_manager.services.export_history_repository import ExportHistoryRepository, ExportRecord
from dtf_manager.ui.panels.project_settings_panel import ProjectSettingsPanel
from dtf_manager.ui.styles import APP_STYLE
from dtf_manager.ui.widgets.export_history_dialog import ExportHistoryDialog


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "export_history.json"

    def test_a_record_has_the_weekday_length_and_value_of_the_project(self):
        monday = datetime(2026, 11, 23, 14, 32, 5)                    # a Monday
        record = ExportRecord.new("Pedidos do dia", 6.805, 79.90, parts=1, when=monday)
        self.assertEqual(record.weekday, "segunda-feira")
        self.assertEqual(record.used_length_m, 6.805)
        self.assertEqual(record.project_value, round(6.805 * 79.90, 2))   # the "Valor do projeto" of the summary
        self.assertEqual(record.moment, monday)

    def test_every_weekday_is_named_in_portuguese(self):
        names = [ExportRecord.new("x", 1, 1, when=datetime(2026, 11, 23 + day)).weekday for day in range(7)]
        self.assertEqual(names, ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                                 "sexta-feira", "sábado", "domingo"])

    def test_records_are_saved_and_come_back_newest_first_after_reopening(self):
        repository = ExportHistoryRepository(self.path)
        repository.add(ExportRecord.new("a", 1, 10, when=datetime(2026, 11, 20, 9, 0)))
        repository.add(ExportRecord.new("c", 3, 10, when=datetime(2026, 11, 22, 9, 0)))
        repository.add(ExportRecord.new("b", 2, 10, when=datetime(2026, 11, 21, 9, 0)))
        reopened = ExportHistoryRepository(self.path)
        self.assertEqual([record.name for record in reopened.list_all()], ["c", "b", "a"])
        self.assertIsNone(reopened.load_warning)

    def test_a_corrupt_file_is_kept_and_the_history_starts_empty(self):
        self.path.write_text("{ not json", encoding="utf-8")
        repository = ExportHistoryRepository(self.path)
        self.assertEqual(repository.list_all(), [])
        self.assertIsNotNone(repository.load_warning)
        self.assertTrue(list(self.path.parent.glob("export_history.corrupt-*.bak")))

    def test_a_bad_record_is_ignored_without_losing_the_others(self):
        from dataclasses import asdict
        good = ExportRecord.new("ok", 1, 10)
        self.path.write_text(json.dumps({"schemaVersion": 1, "exports": [{"id": "x"}, asdict(good)]}),
                             encoding="utf-8")
        repository = ExportHistoryRepository(self.path)
        self.assertEqual([record.name for record in repository.list_all()], ["ok"])
        self.assertIsNotNone(repository.load_warning)

    def test_a_write_failure_raises_and_keeps_nothing_in_memory(self):
        blocked = Path(self.temp.name) / "blocked"
        blocked.write_text("a file, not a folder", encoding="utf-8")
        repository = ExportHistoryRepository(blocked / "history.json")
        with self.assertRaises(OSError):
            repository.add(ExportRecord.new("x", 1, 1))
        self.assertEqual(repository.list_all(), [])


class DialogAndWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE)

    def test_the_dialog_lists_day_date_length_and_value_with_totals(self):
        records = [ExportRecord.new("Pedido A", 6.8, 79.90, when=datetime(2026, 11, 23, 14, 32)),
                   ExportRecord.new("Pedido B", 12.5, 79.90, parts=2, when=datetime(2026, 11, 24, 9, 5))]
        dialog = ExportHistoryDialog(records)
        self.addCleanup(dialog.deleteLater)
        table = dialog.table
        self.assertEqual((dialog.record_rows(), table.rowCount()), (2, 3))      # + the total row
        self.assertEqual([table.item(0, c).text() for c in range(5)],
                         ["Segunda-feira", "23/11/2026 14:32", "Pedido A", "6,80 m", "R$ 543,32"])
        self.assertEqual(table.item(1, 2).text(), "Pedido B (2 partes)")
        self.assertEqual(table.item(1, 4).text(), "R$ 998,75")
        self.assertIn("2 exportação(ões)", dialog.totals_label.text())
        self.assertTrue(dialog.empty_label.isHidden())                  # there is data, so no empty message

    def test_clearing_the_history_asks_first_and_empties_dialog_and_file(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        with TemporaryDirectory() as folder:
            path = Path(folder) / "history.json"
            repository = ExportHistoryRepository(path)
            repository.add(ExportRecord.new("a", 1, 10))
            dialog = ExportHistoryDialog(repository.list_all(), clear_callback=repository.clear)
            self.addCleanup(dialog.deleteLater)
            self.assertTrue(dialog.clear_button.isEnabled())
            box = "dtf_manager.ui.widgets.export_history_dialog.QMessageBox.question"
            with patch(box, return_value=QMessageBox.StandardButton.No):
                self.assertFalse(dialog.clear_history())
            self.assertEqual(dialog.record_rows(), 1)                       # refused: nothing lost
            self.assertEqual(len(ExportHistoryRepository(path).list_all()), 1)
            with patch(box, return_value=QMessageBox.StandardButton.Yes):
                self.assertTrue(dialog.clear_history())
            self.assertEqual((dialog.record_rows(), dialog.table.rowCount()), (0, 0))
            self.assertFalse(dialog.clear_button.isEnabled())
            self.assertFalse(dialog.empty_label.isHidden())
            self.assertEqual(ExportHistoryRepository(path).list_all(), [])  # also gone after reopening

    def test_a_failed_clear_keeps_the_history(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        with TemporaryDirectory() as folder:
            blocked = Path(folder) / "history.json"
            repository = ExportHistoryRepository(blocked)
            repository.add(ExportRecord.new("a", 1, 10))
            dialog = ExportHistoryDialog(repository.list_all(), clear_callback=repository.clear)
            self.addCleanup(dialog.deleteLater)
            base = "dtf_manager.ui.widgets.export_history_dialog.QMessageBox"
            with patch.object(ExportHistoryRepository, "_persist", side_effect=OSError("disk")), \
                    patch(base + ".question", return_value=QMessageBox.StandardButton.Yes), \
                    patch(base + ".warning") as warning:
                self.assertFalse(dialog.clear_history())
            warning.assert_called_once()
            self.assertEqual(dialog.record_rows(), 1)
            self.assertEqual(len(repository.list_all()), 1)

    def test_the_last_row_is_the_total_of_length_and_value(self):
        records = [ExportRecord.new("A", 6.8, 79.90, when=datetime(2026, 11, 23, 14, 32)),
                   ExportRecord.new("B", 12.5, 79.90, when=datetime(2026, 11, 24, 9, 5))]
        dialog = ExportHistoryDialog(records)
        self.addCleanup(dialog.deleteLater)
        table = dialog.table
        last = table.rowCount() - 1
        self.assertEqual([table.item(last, c).text() for c in (2, 3, 4)], ["TOTAL", "19,30 m", "R$ 1.542,07"])
        self.assertFalse(table.item(last, 2).flags() & Qt.ItemFlag.ItemIsSelectable)

    def _two_lines(self, folder):
        path = Path(folder) / "history.json"
        repository = ExportHistoryRepository(path)
        repository.add(ExportRecord.new("faltou arte", 1, 10, when=datetime(2026, 11, 25, 1, 58)))
        repository.add(ExportRecord.new("completo", 2, 10, when=datetime(2026, 11, 25, 2, 30)))
        dialog = ExportHistoryDialog(repository.list_all(), clear_callback=repository.clear,
                                     remove_callback=repository.remove)       # newest first: completo, faltou
        self.addCleanup(dialog.deleteLater)
        return path, dialog

    def test_each_line_has_a_trash_button_in_the_last_column_but_the_total_row_does_not(self):
        from PySide6.QtWidgets import QPushButton
        with TemporaryDirectory() as folder:
            _, dialog = self._two_lines(folder)
            table = dialog.table
            self.assertEqual(table.columnCount(), 6)
            for row in (0, 1):
                self.assertIsInstance(table.cellWidget(row, 5), QPushButton)
            self.assertIsNone(table.cellWidget(2, 5))                      # the total row
            self.assertFalse(hasattr(dialog, "delete_button"))             # the old button is gone

    def test_the_trash_button_asks_first_then_updates_list_total_and_file(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        with TemporaryDirectory() as folder:
            path, dialog = self._two_lines(folder)
            box = "dtf_manager.ui.widgets.export_history_dialog.QMessageBox.question"
            with patch(box, return_value=QMessageBox.StandardButton.No):
                dialog.table.cellWidget(1, 5).click()                       # "faltou arte"
            self.assertEqual(dialog.record_rows(), 2)
            with patch(box, return_value=QMessageBox.StandardButton.Yes):
                dialog.table.cellWidget(1, 5).click()
            self.assertEqual(dialog.record_rows(), 1)
            self.assertEqual(dialog.table.item(0, 2).text(), "completo")
            self.assertEqual(dialog.table.item(1, 3).text(), "2,00 m")      # the total follows
            self.assertEqual([r.name for r in ExportHistoryRepository(path).list_all()], ["completo"])

    def test_right_click_menu_deletes_the_line_under_the_cursor(self):
        from unittest.mock import patch
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QMessageBox
        with TemporaryDirectory() as folder:
            path, dialog = self._two_lines(folder)
            dialog.show()
            table = dialog.table
            point = QPoint(20, table.rowViewportPosition(1) + 5)
            menu = "dtf_manager.ui.widgets.export_history_dialog.QMenu"
            question = "dtf_manager.ui.widgets.export_history_dialog.QMessageBox.question"
            with patch(menu) as fake_menu, patch(question, return_value=QMessageBox.StandardButton.Yes):
                action = fake_menu.return_value.addAction.return_value
                fake_menu.return_value.exec.return_value = action           # the user picked "Excluir"
                dialog._show_context_menu(point)
            self.assertEqual([r.name for r in ExportHistoryRepository(path).list_all()], ["completo"])
            with patch(menu) as fake_menu:                                  # right click on the total row: no menu
                dialog._show_context_menu(QPoint(20, table.rowViewportPosition(1) + 5))
            fake_menu.assert_not_called()

    def test_the_total_row_cannot_be_deleted(self):
        dialog = ExportHistoryDialog([ExportRecord.new("A", 1, 10)],
                                     remove_callback=lambda record_id: self.fail("deleted"))
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.delete_row(1))                              # the total row
        self.assertFalse(dialog.delete_row(-1))

    def test_a_failed_delete_keeps_the_line(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        def broken(record_id):
            raise OSError("disk")
        dialog = ExportHistoryDialog([ExportRecord.new("A", 1, 10)], remove_callback=broken)
        self.addCleanup(dialog.deleteLater)
        base = "dtf_manager.ui.widgets.export_history_dialog.QMessageBox"
        with patch(base + ".question", return_value=QMessageBox.StandardButton.Yes), \
                patch(base + ".warning") as warning:
            self.assertFalse(dialog.delete_row(0))
        warning.assert_called_once()
        self.assertEqual(dialog.record_rows(), 1)

    def test_the_dialog_explains_when_there_is_nothing_yet(self):
        dialog = ExportHistoryDialog([])
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.empty_label.isHidden())
        self.assertTrue(dialog.table.isHidden())

    def test_the_history_button_sits_next_to_regroup_and_asks_for_the_history(self):
        panel = ProjectSettingsPanel()
        self.addCleanup(panel.deleteLater)
        asked = []
        panel.history_requested.connect(lambda: asked.append(True))
        self.assertEqual(panel.history_button.text(), "HISTÓRICO")
        row = panel.regroup_button.parentWidget().layout()
        self.assertIsNotNone(row)
        panel.history_button.click()
        self.assertEqual(asked, [True])

    def test_finishing_an_export_records_length_and_value(self):
        from dtf_manager.ui.main_window import MainWindow
        with TemporaryDirectory() as folder:
            repository = ExportHistoryRepository(Path(folder) / "history.json")
            caller = SimpleNamespace(
                _export_file_name="Pedidos 24-11", _output_paths=[Path("a.png"), Path("b.png")],
                roll_view=SimpleNamespace(sceneRect=lambda: SimpleNamespace(height=lambda: 6805.0)),
                settings=SimpleNamespace(cost_input=SimpleNamespace(value=lambda: 79.90)),
                _export_history_repository=lambda: repository, statusBar=Mock())
            MainWindow._record_export_history(caller)
            (record,) = repository.list_all()
            self.assertEqual((record.name, record.parts), ("Pedidos 24-11", 2))
            self.assertAlmostEqual(record.used_length_m, 6.805)
            self.assertAlmostEqual(record.project_value, round(6.805 * 79.90, 2))

    def test_a_history_failure_never_breaks_the_export(self):
        from dtf_manager.ui.main_window import MainWindow
        repository = Mock()
        repository.add.side_effect = OSError("disk full")
        status = Mock()
        caller = SimpleNamespace(
            _export_file_name="x", _output_paths=[Path("a.png")],
            roll_view=SimpleNamespace(sceneRect=lambda: SimpleNamespace(height=lambda: 1000.0)),
            settings=SimpleNamespace(cost_input=SimpleNamespace(value=lambda: 10.0)),
            _export_history_repository=lambda: repository, statusBar=lambda: status)
        MainWindow._record_export_history(caller)                    # must not raise
        status.showMessage.assert_called_once()


if __name__ == "__main__":
    unittest.main()
