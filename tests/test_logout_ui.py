from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox

from dtf_manager.core.application_controller import ApplicationController
from dtf_manager.services.api_client import ApiResult
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from dtf_manager.ui.main_window import MainWindow
from dtf_manager.ui.styles import APP_STYLE
from dtf_manager.services.sqlite_database import DTFDatabase
from dtf_manager.services.production_history_repository import ProductionHistoryRepository
from tests.session_fakes import FakeSessionStorage
from tests.test_authentication import FakeClient, TOKENS


class LogoutUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        database = DTFDatabase(folder / "test.db")
        history = ProductionHistoryRepository(folder / "history.json")
        settings = QSettings(str(folder / "settings.ini"), QSettings.Format.IniFormat)
        with patch("dtf_manager.ui.main_window.DTFDatabase.default", return_value=database), \
             patch("dtf_manager.ui.main_window.ProductionHistoryRepository.default", return_value=history), \
             patch("dtf_manager.ui.panels.project_settings_panel.QSettings", return_value=settings):
            self.window = MainWindow()
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.dispose_window)

    def dispose_window(self):
        self.window._export_timer.stop()
        self.window.pages.setCurrentWidget(self.window.editor_page)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def connect_session(self):
        client = FakeClient()
        storage = FakeSessionStorage()
        controller = ApplicationController(self.app, client=client, storage=storage,
                                           main_window_factory=lambda: self.window)
        def dispose():
            controller.stop()
            controller._transitioning = True
            controller.login_window.close()
            controller.login_window.deleteLater()
            controller.deleteLater()
        self.addCleanup(dispose)
        controller.login("fake@example.com", "fake-password")
        client.respond(ApiResult(200, TOKENS))
        client.respond(ApiResult(200, {"active": True, "status": "ACTIVE"}))
        return controller, client, storage

    def test_visible_logout_button_reaches_controller_and_returns_to_login(self):
        controller, client, storage = self.connect_session()
        self.assertTrue(self.window.logout_button.isVisible())
        self.window.logout_button.click()
        self.assertEqual(client.calls[-1][0], "/auth/logout")
        # Let the shared operational fixture dispose its window once.
        with patch.object(self.window, "deleteLater"):
            client.respond(ApiResult(200, {"status": "ok"}))
        self.assertIsNone(storage.token)
        self.assertTrue(controller.login_window.isVisible())
        self.assertFalse(self.window.isVisible())

    def test_unsaved_manual_work_can_cancel_logout_before_any_remote_call(self):
        controller, client, _ = self.connect_session()
        self.window.pages.setCurrentWidget(self.window.manual_linking_page)
        calls = len(client.calls)
        with patch.object(self.window.manual_linking_page, "confirm_can_leave", return_value=False):
            self.window.logout_button.click()
        self.assertEqual(len(client.calls), calls)
        self.assertFalse(controller._logout_pending)
        self.assertFalse(self.window._authentication_logout)
        self.window.pages.setCurrentWidget(self.window.editor_page)

    def test_active_export_prevents_logout_without_changing_export(self):
        controller, client, _ = self.connect_session()
        self.window._export_timer.setInterval(60000)
        self.window._export_timer.start()
        calls = len(client.calls)
        with patch("dtf_manager.ui.main_window.QMessageBox.information"):
            self.window.logout_button.click()
        self.assertEqual(len(client.calls), calls)
        self.assertTrue(self.window._export_timer.isActive())
        self.assertFalse(controller._logout_pending)
        self.window._export_timer.stop()

    def test_remote_failure_restores_normal_close_guard(self):
        controller, client, _ = self.connect_session()
        self.window.pages.setCurrentWidget(self.window.manual_linking_page)
        with patch.object(self.window.manual_linking_page, "confirm_can_leave", return_value=True):
            self.window.logout_button.click()
        self.assertTrue(self.window._authentication_logout)
        with patch("dtf_manager.core.application_controller.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.No):
            client.respond(ApiResult(error="network"))
        self.assertFalse(self.window._authentication_logout)
        with patch.object(self.window.manual_linking_page, "confirm_can_leave", return_value=False):
            self.assertFalse(self.window.close())
        self.window.pages.setCurrentWidget(self.window.editor_page)

    def test_import_or_link_work_defers_logout(self):
        controller, client, _ = self.connect_session()
        calls = len(client.calls)
        for flag in ["_is_importing_orders", "_is_auto_linking", "_is_building_order"]:
            with patch.object(self.window, flag, True), \
                 patch("dtf_manager.ui.main_window.QMessageBox.information"):
                self.window.logout_button.click()
            self.assertEqual(len(client.calls), calls)
            self.assertFalse(controller._logout_pending)
