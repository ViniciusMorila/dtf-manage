import os
import subprocess
import sys
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget
from dtf_manager.core.application_controller import ApplicationController
from dtf_manager.services.api_client import ApiResult
from tests.test_authentication import FakeClient, TOKENS
from tests.session_fakes import FakeSessionStorage


class LazyAuthUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.client = FakeClient()
        self.storage = FakeSessionStorage("saved-refresh")
        self.main = QWidget()
        self.factory = Mock(return_value=self.main)
        self.controller = ApplicationController(self.app, client=self.client,
            storage=self.storage, main_window_factory=self.factory)

    def tearDown(self):
        self.controller.stop()
        self.controller._transitioning = True
        if self.controller._login_window is not None:
            self.controller._login_window.close()
            self.controller._login_window.deleteLater()
        self.main.close()
        self.main.deleteLater()
        self.controller.deleteLater()
        self.app.processEvents()

    def restore(self):
        self.controller.start()
        self.assertIsNone(self.controller._login_window)
        self.factory.assert_not_called()
        self.client.respond(ApiResult(200, TOKENS))
        self.assertIsNone(self.controller._login_window)
        self.factory.assert_not_called()
        self.assertEqual(self.client.calls[-1][0], "/license/status")

    def test_valid_restore_never_constructs_login(self):
        self.restore()
        self.client.respond(ApiResult(200, {"active": True, "status": "ACTIVE"}))
        self.factory.assert_called_once()
        self.assertIsNone(self.controller._login_window)
        self.assertTrue(self.main.isVisible())

    def test_no_session_shows_login(self):
        self.storage.token = None
        self.controller.start()
        self.assertTrue(self.controller._login_window.isVisible())
        self.assertEqual(self.client.calls, [])
        self.factory.assert_not_called()

    def test_invalid_refresh_shows_login_and_clears_invalid_session(self):
        self.controller.start()
        self.client.respond(ApiResult(401, error="http"))
        self.assertTrue(self.controller._login_window.isVisible())
        self.assertIsNone(self.storage.token)
        self.factory.assert_not_called()

    def test_denied_license_shows_login_not_main(self):
        self.restore()
        self.client.respond(ApiResult(200, {"active": False, "status": "EXPIRED"}))
        self.assertTrue(self.controller._login_window.isVisible())
        self.factory.assert_not_called()

    def test_logout_constructs_login_only_when_needed(self):
        self.restore()
        self.client.respond(ApiResult(200, {"active": True, "status": "ACTIVE"}))
        self.controller.logout()
        self.client.respond(ApiResult(200, {"status": "ok"}))
        self.assertTrue(self.controller._login_window.isVisible())
        self.assertIsNone(self.controller.main_window)
        self.assertIsNone(self.storage.token)

    def test_pending_restore_stop_discards_late_response_preserves_refresh(self):
        self.controller.start()
        self.controller.stop()
        self.client.respond(ApiResult(200, TOKENS))
        self.assertEqual(self.storage.token, "saved-refresh")
        self.assertIsNone(self.controller._login_window)
        self.factory.assert_not_called()

    def test_bootstrap_import_does_not_import_operational_ui(self):
        result = subprocess.run([sys.executable, "-c",
            "import sys; import dtf_manager.core.bootstrap; "
            "assert 'dtf_manager.ui.main_window' not in sys.modules; "
            "assert 'dtf_manager.ui.login_window' not in sys.modules"],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
