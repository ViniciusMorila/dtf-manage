import contextlib
import io
import logging
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from dtf_manager.core.application_controller import ApplicationController
from dtf_manager.services.api_client import ApiClient, ApiResult
from dtf_manager.services.auth_service import AuthService
from tests.session_fakes import FakeSessionStorage
from tests.test_authentication import FakeClient, FakeManager, FakeReply, TOKENS


ROTATED = {"access_token": "fake-new-access", "refresh_token": "fake-refresh-B",
           "token_type": "bearer", "expires_in": 900}
ACTIVE = {"active": True, "status": "ACTIVE"}


class SessionLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.storage = FakeSessionStorage()
        self.client = FakeClient()
        self.window = QWidget()
        self.factory = Mock(return_value=self.window)
        self.controller = ApplicationController(self.app, client=self.client, storage=self.storage,
                                                main_window_factory=self.factory)
        self.addCleanup(self.dispose)

    def dispose(self):
        self.controller.stop()
        self.controller._transitioning = True
        self.controller.login_window.close()
        self.controller.login_window.deleteLater()
        self.window.close()
        self.window.deleteLater()
        self.controller.deleteLater()
        self.app.processEvents()

    def restore(self):
        self.storage.token = "fake-refresh-A"
        self.controller.start()

    def authorize(self):
        self.controller.login("fake@example.com", "fake-password")
        self.client.respond(ApiResult(200, TOKENS))
        self.client.respond(ApiResult(200, ACTIVE))

    def test_start_without_saved_refresh_shows_login_without_http(self):
        self.controller.start()
        self.assertTrue(self.controller.login_window.isVisible())
        self.assertTrue(self.controller.login_window.enter.isEnabled())
        self.assertEqual(self.client.calls, [])
        self.factory.assert_not_called()

    def test_restoration_saves_rotated_token_before_license_and_opens_after_active(self):
        self.restore()
        self.assertEqual(self.client.calls[0][:2], ("/auth/refresh", {"refresh_token": "fake-refresh-A"}))
        self.factory.assert_not_called()
        self.client.respond(ApiResult(200, ROTATED))
        self.assertEqual(self.storage.saved, ["fake-refresh-B"])
        self.assertEqual(self.storage.token, "fake-refresh-B")
        self.assertEqual(self.client.calls[-1][:2], ("/license/status", "fake-new-access"))
        self.factory.assert_not_called()
        self.client.respond(ApiResult(200, ACTIVE))
        self.factory.assert_called_once_with()

    def test_license_pending_after_restore_never_opens_main(self):
        self.restore()
        self.client.respond(ApiResult(200, ROTATED))
        self.client.respond(ApiResult(200, {"active": False, "status": "PENDING"}))
        self.factory.assert_not_called()
        self.assertIn("não está ativa", self.controller.login_window.message.text())
        self.assertEqual(self.storage.token, "fake-refresh-B")

    def test_invalid_refresh_401_and_422_delete_saved_token(self):
        for status in [401, 422]:
            with self.subTest(status=status):
                self.restore()
                self.client.respond(ApiResult(status, error="http", error_code="INVALID_REFRESH_TOKEN"))
                self.assertIsNone(self.storage.token)
                self.assertIsNone(self.controller.auth.access_token)
                self.assertTrue(self.controller.login_window.enter.isEnabled())
                self.assertEqual(self.controller.login_window.enter.text(), "Entrar")
                self.factory.assert_not_called()

    def test_transient_refresh_failure_preserves_storage_and_requires_manual_retry(self):
        for result in [ApiResult(500, error="http"), ApiResult(503, error="http"),
                       ApiResult(error="timeout"), ApiResult(error="network"),
                       ApiResult(401, error="timeout")]:
            with self.subTest(status=result.status, kind=result.error):
                self.restore()
                calls = len(self.client.calls)
                self.client.respond(result)
                self.assertEqual(self.storage.token, "fake-refresh-A")
                self.assertEqual(len(self.client.calls), calls)
                self.assertEqual(self.controller.login_window.enter.text(), "Tentar novamente")
                self.assertIn("preservado", self.controller.login_window.message.text())
                self.factory.assert_not_called()

    def test_manual_retry_can_restore_session(self):
        self.restore()
        self.client.respond(ApiResult(error="timeout"))
        self.controller.login_window.enter.click()
        self.assertEqual(len(self.client.calls), 2)
        self.client.respond(ApiResult(200, ROTATED))
        self.client.respond(ApiResult(200, ACTIVE))
        self.factory.assert_called_once()

    def test_retry_after_ambiguous_rotation_can_require_login_without_revoking_successor(self):
        self.restore()
        self.client.respond(ApiResult(error="network"))
        self.controller.login_window.enter.click()
        self.client.respond(ApiResult(401, error="http", error_code="INVALID_REFRESH_TOKEN"))
        self.assertIsNone(self.storage.token)
        self.assertEqual([call[0] for call in self.client.calls], ["/auth/refresh", "/auth/refresh"])
        self.factory.assert_not_called()

    def test_return_to_login_explains_new_session_and_preserves_saved_token(self):
        self.restore()
        self.client.respond(ApiResult(error="network"))
        self.controller.login_window.new_login.click()
        self.assertEqual(self.controller.login_window.enter.text(), "Entrar")
        self.assertIn("nova sessão", self.controller.login_window.message.text())
        self.assertEqual(self.storage.token, "fake-refresh-A")

    def test_invalid_json_200_does_not_overwrite_or_reuse_token(self):
        self.restore()
        self.client.respond(ApiResult(200, error="invalid_json"))
        self.assertEqual(self.storage.token, "fake-refresh-A")
        self.assertEqual(self.storage.saved, [])
        self.controller.refresh_session()
        self.assertEqual(len(self.client.calls), 1)
        self.factory.assert_not_called()

    def test_missing_fields_or_nonrotating_response_never_overwrite_storage(self):
        for data in [{}, {**ROTATED, "refresh_token": "fake-refresh-A"},
                     {**ROTATED, "expires_in": None}]:
            with self.subTest(data=data):
                # Independent service, because a malformed 200 blocks A reuse.
                storage, client = FakeSessionStorage("fake-refresh-A"), FakeClient()
                auth = AuthService(client, storage=storage)
                errors = []
                auth.failed.connect(errors.append)
                auth.refresh_session()
                client.respond(ApiResult(200, data))
                self.assertEqual(errors, ["invalid_json"])
                self.assertEqual(storage.token, "fake-refresh-A")
                self.assertEqual(storage.saved, [])
                self.assertIsNone(auth.access_token)
                auth.deleteLater()

    def test_rotation_save_failure_clears_session_and_does_not_check_license(self):
        self.restore()
        self.storage.fail_save = True
        self.client.respond(ApiResult(200, ROTATED))
        self.assertIsNone(self.controller.auth.access_token)
        self.assertIsNone(self.controller.auth.refresh_token)
        self.assertIsNone(self.storage.token)
        self.assertEqual(len(self.client.calls), 1)
        self.factory.assert_not_called()
        self.assertIn("protegida", self.controller.login_window.message.text())

    def test_simultaneous_refresh_callers_share_one_request_and_one_result(self):
        self.restore()
        first, second = Mock(), Mock()
        self.controller.auth.authenticated.connect(first)
        self.controller.auth.authenticated.connect(second)
        self.controller.refresh_session()
        self.controller.auth.refresh_session()
        self.assertEqual(len(self.client.calls), 1)
        self.client.respond(ApiResult(200, ROTATED))
        first.assert_called_once_with()
        second.assert_called_once_with()
        self.assertEqual(self.storage.saved, ["fake-refresh-B"])

    def test_normal_close_preserves_refresh_and_never_calls_logout(self):
        self.authorize()
        self.controller.stop()
        self.assertEqual(self.storage.token, TOKENS["refresh_token"])
        self.assertEqual(self.storage.deletions, 0)
        self.assertIsNone(self.controller.auth.access_token)
        self.assertIsNone(self.controller.auth.refresh_token)
        self.assertNotIn("/auth/logout", [call[0] for call in self.client.calls])
        self.assertTrue(self.storage.lock_released)

    def test_real_event_loop_normal_main_close_preserves_session(self):
        script = """
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from dtf_manager.core.application_controller import ApplicationController
from dtf_manager.services.api_client import ApiResult
from tests.session_fakes import FakeSessionStorage
class Client:
    calls = []
    def post_json(self, path, payload, callback):
        self.calls.append(path)
        assert path == '/auth/refresh'
        callback(ApiResult(200, {'access_token':'fake-access', 'refresh_token':'fake-B',
                                'token_type':'bearer', 'expires_in':900}))
    def get(self, path, callback, **kwargs):
        self.calls.append(path)
        callback(ApiResult(200, {'active':True, 'status':'ACTIVE'}))
    def cancel_all(self): pass
app = QApplication([])
client, storage = Client(), FakeSessionStorage('fake-A')
controller = ApplicationController(app, client=client, storage=storage, main_window_factory=QWidget)
controller.start()
assert controller.main_window is not None
QTimer.singleShot(20, controller.main_window.close)
result = app.exec()
assert controller._stopped
assert storage.token == 'fake-B'
assert controller.auth.access_token is None
assert '/auth/logout' not in client.calls
raise SystemExit(result)
"""
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1], timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_close_while_refresh_pending_ignores_late_response_and_keeps_a(self):
        self.restore()
        self.controller.stop()
        self.client.respond(ApiResult(200, ROTATED))
        self.assertEqual(self.storage.token, "fake-refresh-A")
        self.assertEqual(self.storage.saved, [])
        self.factory.assert_not_called()

    def test_logout_uses_latest_refresh_clears_both_tokens_and_returns_to_login(self):
        self.restore()
        self.client.respond(ApiResult(200, ROTATED))
        self.client.respond(ApiResult(200, ACTIVE))
        self.controller.logout()
        self.assertEqual(self.client.calls[-1][:2], ("/auth/logout", {"refresh_token": "fake-refresh-B"}))
        calls = len(self.client.calls)
        self.controller.logout()
        self.assertEqual(len(self.client.calls), calls)
        self.client.respond(ApiResult(200, {"status": "ok"}))
        self.assertIsNone(self.storage.token)
        self.assertIsNone(self.controller.auth.access_token)
        self.assertIsNone(self.controller.auth.refresh_token)
        self.assertIsNone(self.controller.main_window)
        self.assertTrue(self.controller.login_window.isVisible())
        self.assertTrue(self.controller.auth.remote_logout_confirmed)
        self.assertIn("Você saiu", self.controller.login_window.message.text())
        self.assertFalse(self.controller._stopped)

    def test_remote_logout_failure_is_not_declared_confirmed(self):
        for result in [ApiResult(error="network"), ApiResult(503, error="http"),
                       ApiResult(200, error="invalid_json")]:
            with self.subTest(result=result.error):
                self.authorize()
                self.controller.logout()
                with patch("dtf_manager.core.application_controller.QMessageBox.question",
                           return_value=QMessageBox.StandardButton.No) as prompt:
                    self.client.respond(result)
                self.assertIn("não estará confirmada", prompt.call_args.args[2])
                self.assertFalse(self.controller.auth.remote_logout_confirmed)
                self.assertEqual(self.storage.token, TOKENS["refresh_token"])
                self.assertIsNotNone(self.controller.main_window)
                self.assertTrue(self.window.isEnabled())
                # Prepare the next subtest without issuing a second login in an active main.
                self.controller.auth.clear()
                self.controller.main_window = None

    def test_local_exit_after_remote_failure_deletes_only_local_session(self):
        self.authorize()
        self.controller.logout()
        with patch("dtf_manager.core.application_controller.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            self.client.respond(ApiResult(error="network"))
        self.assertIsNone(self.storage.token)
        self.assertIsNone(self.controller.auth.access_token)
        self.assertIsNone(self.controller.main_window)
        self.assertFalse(self.controller.auth.remote_logout_confirmed)
        self.assertIn("não foi confirmada", self.controller.login_window.message.text())

    def test_logout_during_refresh_waits_for_b_and_never_opens_main(self):
        self.restore()
        self.controller.logout()
        self.assertEqual(len(self.client.calls), 1)
        self.client.respond(ApiResult(200, ROTATED))
        self.assertEqual(self.client.calls[-1][:2], ("/auth/logout", {"refresh_token": "fake-refresh-B"}))
        self.client.respond(ApiResult(200, {"status": "ok"}))
        self.assertIsNone(self.storage.token)
        self.factory.assert_not_called()
        self.assertNotIn("/license/status", [call[0] for call in self.client.calls])

    def test_late_refresh_after_local_logout_never_restores_session(self):
        self.restore()
        callback = self.client.calls[-1][-1]
        self.controller.auth.logout_locally()
        callback(ApiResult(200, ROTATED))
        self.assertIsNone(self.storage.token)
        self.assertEqual(self.storage.saved, [])
        self.assertIsNone(self.controller.auth.access_token)
        self.factory.assert_not_called()

    def test_login_persists_only_refresh_before_publishing_session(self):
        self.controller.login("fake@example.com", "fake-password")
        observed = []
        self.controller.auth.authenticated.connect(lambda: observed.append(self.storage.token))
        self.client.respond(ApiResult(200, TOKENS))
        self.assertEqual(observed, [TOKENS["refresh_token"]])
        self.assertEqual(self.storage.saved, [TOKENS["refresh_token"]])
        self.assertNotIn(TOKENS["access_token"], self.storage.saved)
        self.assertNotIn("fake-password", self.storage.saved)

    def test_login_storage_failure_does_not_publish_or_open_main(self):
        self.storage.fail_save = True
        self.controller.login("fake@example.com", "fake-password")
        self.client.respond(ApiResult(200, TOKENS))
        self.assertEqual(self.storage.saved, [])
        self.assertIsNone(self.controller.auth.access_token)
        self.assertEqual(len(self.client.calls), 1)
        self.factory.assert_not_called()

    def test_storage_read_failure_shows_login_without_http(self):
        self.storage.fail_load = True
        self.controller.start()
        self.assertEqual(self.client.calls, [])
        self.assertIn("protegida", self.controller.login_window.message.text())
        self.assertTrue(self.controller.login_window.enter.isEnabled())

    def test_storage_delete_failure_never_claims_successful_local_logout(self):
        self.authorize()
        self.storage.fail_delete = True
        self.controller.logout()
        with patch("dtf_manager.core.application_controller.QMessageBox.warning") as warning:
            self.client.respond(ApiResult(200, {"status": "ok"}))
        self.assertIsNone(self.controller.auth.access_token)
        self.assertEqual(self.storage.token, TOKENS["refresh_token"])
        self.assertIsNotNone(self.controller.main_window)
        self.assertIn("exclusão local não foi concluída", warning.call_args.args[2])

    def test_second_process_lock_prevents_any_authentication(self):
        self.storage.lock_available = False
        self.storage.token = "fake-refresh-A"
        self.controller.start()
        self.controller.login("fake@example.com", "fake-password")
        self.controller.refresh_session()
        self.assertEqual(self.client.calls, [])
        self.assertFalse(self.controller.login_window.enter.isEnabled())
        self.assertIn("já está aberto", self.controller.login_window.message.text())

    def test_runtime_refresh_revalidates_license_without_rebuilding_main(self):
        self.authorize()
        self.controller.refresh_session()
        self.client.respond(ApiResult(200, ROTATED))
        self.assertEqual(self.client.calls[-1][:2], ("/license/status", "fake-new-access"))
        self.client.respond(ApiResult(200, ACTIVE))
        self.factory.assert_called_once()

    def test_secrets_are_never_logged_or_shown_during_refresh_and_logout(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logging.getLogger().addHandler(handler)
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.restore()
                self.client.respond(ApiResult(200, ROTATED))
                self.client.respond(ApiResult(200, ACTIVE))
                self.controller.logout()
                self.client.respond(ApiResult(200, {"status": "ok"}))
            text = output.getvalue() + self.controller.login_window.message.text()
            for secret in ["fake-refresh-A", "fake-refresh-B", "fake-new-access", "fake-password", "Authorization"]:
                self.assertNotIn(secret, text)
        finally:
            logging.getLogger().removeHandler(handler)


class SessionTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_refresh_and_logout_use_json_without_bearer_or_cookies(self):
        from PySide6.QtNetwork import QNetworkRequest
        for endpoint in ["/auth/refresh", "/auth/logout"]:
            reply = FakeReply()
            manager = FakeManager(reply)
            client = ApiClient(manager=manager)
            client.post_json(endpoint, {"refresh_token": "fake-refresh"}, Mock())
            self.assertTrue(manager.request.rawHeader("Authorization").isEmpty())
            self.assertEqual(manager.request.attribute(QNetworkRequest.Attribute.CookieLoadControlAttribute),
                             QNetworkRequest.LoadControl.Manual)
            self.assertEqual(manager.request.attribute(QNetworkRequest.Attribute.CookieSaveControlAttribute),
                             QNetworkRequest.LoadControl.Manual)
            reply.finished.emit()
            self.assertTrue(reply.deleted)

    def test_structured_invalid_refresh_error_is_parsed_without_details(self):
        reply = FakeReply(status=401,
                          body=b'{"error":{"code":"INVALID_REFRESH_TOKEN","message":"private-details"}}')
        client = ApiClient(manager=FakeManager(reply))
        results = []
        client.post_json("/auth/refresh", {"refresh_token": "fake-refresh"}, results.append)
        reply.finished.emit()
        self.assertEqual(results[0].error_code, "INVALID_REFRESH_TOKEN")
        self.assertIsNone(results[0].data)
        self.assertNotIn("private-details", repr(results[0]))
