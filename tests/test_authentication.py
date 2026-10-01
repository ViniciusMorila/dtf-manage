import contextlib
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal, QByteArray, Qt, QCoreApplication, QStandardPaths
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from dtf_manager.core.application_controller import ApplicationController
from dtf_manager.services.api_client import ApiClient, ApiResult, BASE_URL
from dtf_manager.services.auth_service import AuthService


TOKENS = {"access_token": "private-access", "refresh_token": "private-refresh",
          "token_type": "bearer", "expires_in": 900}


class FakeClient:
    def __init__(self):
        self.calls = []

    def post_json(self, path, payload, callback):
        self.calls.append((path, payload, callback))

    def get(self, path, callback, *, access_token):
        self.calls.append((path, access_token, callback))

    def respond(self, result):
        self.calls[-1][-1](result)

    def cancel_all(self):
        pass


class FakeReply(QObject):
    finished = Signal()

    def __init__(self, status=200, body=b"{}", error=QNetworkReply.NetworkError.NoError):
        super().__init__()
        self.status, self.body, self.network_error = status, body, error
        self.deleted = False

    def attribute(self, attr):
        return self.status

    def error(self):
        return self.network_error

    def readAll(self):
        return QByteArray(self.body)

    def abort(self):
        self.network_error = QNetworkReply.NetworkError.OperationCanceledError
        self.finished.emit()

    def deleteLater(self):
        self.deleted = True


class FakeManager:
    def __init__(self, reply):
        self.reply = reply

    def post(self, request, body):
        self.request, self.body = request, body
        return self.reply

    def get(self, request):
        self.request = request
        return self.reply


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.client = FakeClient()
        self.window = QWidget()
        self.factory = Mock(return_value=self.window)
        self.controller = ApplicationController(self.app, client=self.client,
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

    def login(self):
        self.controller.login("user@example.com", "private-password")

    def authenticated(self):
        self.login()
        self.client.respond(ApiResult(200, TOKENS))

    def test_valid_login_keeps_tokens_in_memory_and_checks_license(self):
        self.authenticated()
        self.assertEqual(self.controller.auth.access_token, TOKENS["access_token"])
        self.assertEqual(self.controller.auth.refresh_token, TOKENS["refresh_token"])
        self.assertEqual(self.client.calls[-1][:2], ("/license/status", "private-access"))
        self.factory.assert_not_called()

    def test_invalid_credentials(self):
        self.login()
        self.client.respond(ApiResult(401, error="http"))
        self.assertIn("E-mail ou senha inválidos", self.controller.login_window.message.text())
        self.assertTrue(self.controller.login_window.enter.isEnabled())
        self.assertIsNone(self.controller.auth.access_token)
        self.factory.assert_not_called()

    def test_login_errors(self):
        for kind, text in [("network", "conectar"), ("timeout", "demorou"),
                           ("invalid_json", "resposta"), ("server", "indisponível")]:
            with self.subTest(kind=kind):
                self.login()
                self.client.respond(ApiResult(error=kind))
                self.assertIn(text, self.controller.login_window.message.text())
                self.assertTrue(self.controller.login_window.enter.isEnabled())
                self.factory.assert_not_called()

    def test_malformed_login_payload(self):
        for data in [{}, {**TOKENS, "token_type": None}, {**TOKENS, "access_token": "bad\r\ntoken"}]:
            with self.subTest():
                self.login()
                self.client.respond(ApiResult(200, data))
                self.factory.assert_not_called()
                self.assertIsNone(self.controller.auth.access_token)

    def test_active_constructs_exactly_once_and_closes_login(self):
        self.controller.start()
        self.factory.assert_not_called()
        self.authenticated()
        self.factory.assert_not_called()
        response = ApiResult(200, {"active": True, "status": "ACTIVE"})
        self.client.respond(response)
        self.client.respond(response)
        self.factory.assert_called_once_with()
        self.assertFalse(self.controller.login_window.isVisible())
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.controller._stopped)

    def test_denied_license_and_retry(self):
        self.authenticated()
        for active, status in [(False, "PENDING"), (False, "ACTIVE"), (True, "PENDING")]:
            with self.subTest(active=active, status=status):
                self.client.respond(ApiResult(200, {"active": active, "status": status,
                                                    "plan": {"name": "1 mês"}}))
                self.factory.assert_not_called()
                self.assertIn("não está ativa", self.controller.login_window.message.text())
                self.assertIn("1 mês", self.controller.login_window.message.text())
                self.assertEqual(self.controller.login_window.enter.text(), "Tentar novamente")
                self.controller.login_window.enter.click()
                self.assertEqual(self.client.calls[-1][0], "/license/status")

    def test_license_401_requires_new_login(self):
        self.authenticated()
        self.client.respond(ApiResult(401, error="http"))
        self.assertIn("sessão é inválida", self.controller.login_window.message.text())
        self.assertIsNone(self.controller.auth.access_token)
        self.assertEqual(self.controller.login_window.enter.text(), "Entrar")
        self.factory.assert_not_called()

    def test_license_network_error_is_not_denial(self):
        self.authenticated()
        self.client.respond(ApiResult(error="network"))
        self.assertIn("conectar", self.controller.login_window.message.text())
        self.assertNotIn("não está ativa", self.controller.login_window.message.text())
        self.assertEqual(self.controller.auth.access_token, "private-access")
        self.factory.assert_not_called()

    def test_malformed_license_cannot_authorize(self):
        self.authenticated()
        self.client.respond(ApiResult(200, {"active": "true", "status": "ACTIVE"}))
        self.factory.assert_not_called()
        self.assertIn("resposta", self.controller.login_window.message.text())

    def test_double_click_and_enter_only_submit_once(self):
        view = self.controller.login_window
        view.email.setText("user@example.com")
        view.password.setText("private-password")
        view.enter.click()
        view.enter.click()
        QTest.keyClick(view.password, Qt.Key.Key_Return)
        self.controller.login("user@example.com", "private-password")
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(view.password.text(), "")

    def test_enter_submits_and_password_is_masked(self):
        view = self.controller.login_window
        view.email.setText("user@example.com")
        view.password.setText("private-password")
        QTest.keyClick(view.password, Qt.Key.Key_Return)
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(view.password.echoMode(), view.password.EchoMode.Password)

    def test_close_quits_and_late_reply_cannot_open_main(self):
        self.login()
        real_app = self.controller.app
        self.controller.app = Mock()
        self.controller.login_window.close()
        self.controller.app.quit.assert_called_once()
        self.controller.app = real_app
        self.client.respond(ApiResult(200, TOKENS))
        self.factory.assert_not_called()
        self.assertIsNone(self.controller.auth.access_token)

    def test_close_during_license_ignores_late_authorization(self):
        self.authenticated()
        self.controller.app = Mock()
        self.controller.login_window.close()
        self.client.respond(ApiResult(200, {"active": True, "status": "ACTIVE"}))
        self.factory.assert_not_called()

    def test_tokens_and_password_never_logged(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logging.getLogger().addHandler(handler)
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.authenticated()
                self.client.respond(ApiResult(401, error="http"))
                print(repr(ApiResult(200, TOKENS)))
            for secret in ["private-access", "private-refresh", "private-password", "Authorization"]:
                self.assertNotIn(secret, output.getvalue())
        finally:
            logging.getLogger().removeHandler(handler)


class ApiClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def transport(self, reply, timeout_ms=15000):
        manager = FakeManager(reply)
        client = ApiClient(manager=manager, timeout_ms=timeout_ms)
        self.addCleanup(client.cancel_all)
        return client, manager

    def test_post_json_headers_and_cleanup(self):
        reply = FakeReply(body=json.dumps(TOKENS).encode())
        client, manager = self.transport(reply)
        results = []
        client.post_json("/auth/login", {"email": "a", "password": "b"}, results.append)
        self.assertEqual(manager.request.url().toString(), BASE_URL + "/auth/login")
        self.assertEqual(bytes(manager.request.rawHeader("Accept")), b"application/json")
        self.assertEqual(bytes(manager.request.rawHeader("Content-Type")), b"application/json")
        self.assertEqual(json.loads(manager.body), {"email": "a", "password": "b"})
        self.assertEqual(manager.request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute),
                         QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        reply.finished.emit()
        self.assertEqual(results[0].data, TOKENS)
        self.assertTrue(reply.deleted)
        self.assertFalse(client._pending)

    def test_bearer_and_invalid_json(self):
        for body in [b"not-json", b"[]", b"\xff"]:
            with self.subTest(body=body):
                reply = FakeReply(body=body)
                client, manager = self.transport(reply)
                results = []
                client.get("/license/status", results.append, access_token="private-access")
                self.assertEqual(bytes(manager.request.rawHeader("Authorization")), b"Bearer private-access")
                reply.finished.emit()
                self.assertEqual(results[0].error, "invalid_json")
                self.assertTrue(reply.deleted)

    def test_http_errors_distinct_from_network(self):
        for status, error, expected in [
            (401, QNetworkReply.NetworkError.AuthenticationRequiredError, "http"),
            (500, QNetworkReply.NetworkError.InternalServerError, "http"),
            (0, QNetworkReply.NetworkError.HostNotFoundError, "network"),
            (0, QNetworkReply.NetworkError.TimeoutError, "timeout"),
        ]:
            with self.subTest(status=status, expected=expected):
                reply = FakeReply(status=status, error=error)
                client, _ = self.transport(reply)
                results = []
                client.get("/license/status", results.append, access_token="a")
                reply.finished.emit()
                self.assertEqual(results[0].error, expected)
                self.assertTrue(reply.deleted)

    def test_total_timeout_aborts_and_cleans_reply(self):
        reply = FakeReply()
        client, _ = self.transport(reply, timeout_ms=1)
        results = []
        client.get("/license/status", results.append, access_token="a")
        QTest.qWait(30)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].error, "timeout")
        self.assertTrue(reply.deleted)


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_preserves_identity_and_never_constructs_main(self):
        from dtf_manager.ui.main_window import run_application
        app = QApplication.instance() or QApplication([])
        QCoreApplication.setOrganizationName("DTF Manager")
        QCoreApplication.setApplicationName("DTF Manager")
        expected_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        controller = Mock()
        with patch("dtf_manager.core.application_controller.ApplicationController", return_value=controller) as factory, \
             patch("dtf_manager.ui.main_window.MainWindow") as main, \
             patch.object(QApplication, "exec", return_value=0):
            self.assertEqual(run_application(), 0)
            factory.assert_called_once_with(app)
            controller.start.assert_called_once_with()
            main.assert_not_called()
        self.assertEqual(QCoreApplication.organizationName(), "DTF Manager")
        self.assertEqual(QCoreApplication.applicationName(), "DTF Manager")
        self.assertEqual(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation),
                         expected_path)

    def test_real_event_loop_exits_when_login_closes_without_requests(self):
        script = """
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from dtf_manager.core.application_controller import ApplicationController
class Client:
    def cancel_all(self): pass
    def post_json(self, *args): raise AssertionError('Unexpected HTTP')
    def get(self, *args, **kwargs): raise AssertionError('Unexpected HTTP')
def forbidden_main(): raise AssertionError('Unexpected MainWindow')
app = QApplication([])
controller = ApplicationController(app, client=Client(), main_window_factory=forbidden_main)
controller.start()
QTimer.singleShot(20, controller.login_window.close)
result = app.exec()
assert controller._stopped
assert controller.main_window is None
raise SystemExit(result)
"""
        result = subprocess.run([sys.executable, "-c", script],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
