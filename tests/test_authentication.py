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

from PySide6.QtCore import Qt, QCoreApplication, QStandardPaths
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from dtf_manager.core.config import DEFAULT_API_URL as BASE_URL
from dtf_manager.services.api_client import ApiClient, ApiResult
from tests.license_fakes import (  # noqa: F401  (re-exported for the other test modules)
    FakeClient, FakeManager, FakeReply, ROTATED, TOKENS, active, build_controller,
    dispose_controller, http_error, license_data, status_body)
from tests.session_fakes import MACHINE_ID


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.client = FakeClient()
        self.window = QWidget()
        self.factory = Mock(return_value=self.window)
        self.controller = build_controller(self.app, self.client, factory=self.factory)
        self.controller.login_window  # these tests drive the login form
        self.addCleanup(lambda: dispose_controller(self.app, self.controller, self.window))

    def login(self):
        self.controller.login("user@example.com", "private-password")

    def authenticated(self):
        self.login()
        self.client.respond(ApiResult(200, TOKENS))

    def test_login_sends_machine_id_and_portuguese_password_field(self):
        self.login()
        path, payload, _ = self.client.calls[-1]
        self.assertEqual(path, "/auth/login")
        self.assertEqual(payload, {"email": "user@example.com", "senha": "private-password",
                                   "id_maquina": MACHINE_ID})

    def test_valid_login_keeps_tokens_in_memory_and_checks_license_with_machine_header(self):
        self.authenticated()
        self.assertEqual(self.controller.auth.access_token, TOKENS["access_token"])
        self.assertEqual(self.controller.auth.refresh_token, TOKENS["refresh_token"])
        self.assertEqual(self.client.calls[-1][:2], ("/licencas/status", "private-access"))
        self.assertEqual(self.client.headers[-1], {"X-Id-Maquina": MACHINE_ID})
        self.factory.assert_not_called()

    def test_old_subscription_routes_are_never_called(self):
        self.authenticated()
        self.client.respond(active())
        for path in self.client.paths():
            self.assertNotIn(path, {"/license/status", "/me"})

    def test_invalid_credentials(self):
        self.login()
        self.client.respond(http_error(401, "INVALID_CREDENTIALS"))
        self.assertIn("E-mail ou senha inválidos", self.controller.login_window.message.text())
        self.assertTrue(self.controller.login_window.enter.isEnabled())
        self.assertIsNone(self.controller.auth.access_token)
        self.factory.assert_not_called()

    def test_login_errors(self):
        for result, text in [(ApiResult(error="network"), "conectar"), (ApiResult(error="timeout"), "demorou"),
                             (ApiResult(error="invalid_json"), "resposta"),
                             (ApiResult(503, error="http"), "indisponível")]:
            with self.subTest(error=result.error, status=result.status):
                self.login()
                self.client.respond(result)
                self.assertIn(text, self.controller.login_window.message.text())
                self.assertTrue(self.controller.login_window.enter.isEnabled())
                self.factory.assert_not_called()

    def test_login_refusals_use_app_texts_not_server_text(self):
        for code, status, text in [("LICENCA_BLOQUEADA", 403, "bloqueada"),
                                   ("MAQUINA_DIFERENTE", 403, "outro computador"),
                                   ("MAQUINA_EM_USO", 409, "outra conta")]:
            with self.subTest(code=code):
                self.login()
                self.client.respond(http_error(status, code, "texto do servidor"))
                shown = self.controller.login_window.message.text()
                self.assertIn(text, shown)
                self.assertNotIn("texto do servidor", shown)

    def test_unknown_error_code_falls_back_to_server_message(self):
        self.login()
        self.client.respond(http_error(422, "NOVO_CODIGO", "Mensagem nova do servidor."))
        self.assertIn("Mensagem nova do servidor.", self.controller.login_window.message.text())

    def test_rate_limit_shows_wait_time_from_retry_after(self):
        for seconds, text in [(30, "30 segundos"), (90, "2 minutos"), (1, "1 segundo")]:
            with self.subTest(seconds=seconds):
                self.login()
                self.client.respond(http_error(429, "MUITAS_TENTATIVAS", retry_after=seconds))
                self.assertIn("Aguarde " + text, self.controller.login_window.message.text())
        self.login()
        self.client.respond(http_error(429, "MUITAS_TENTATIVAS"))
        self.assertIn("Muitas tentativas", self.controller.login_window.message.text())

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
        self.client.respond(active())
        self.client.respond(active())
        self.factory.assert_called_once_with()
        self.assertFalse(self.controller.login_window.isVisible())
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.controller._stopped)

    def test_only_status_ativa_in_a_200_authorizes(self):
        for state in ["EXPIRADA", "BLOQUEADA"]:
            with self.subTest(state=state):
                self.authenticated()
                self.client.respond(active(status=state, dias_restantes=0))
                self.factory.assert_not_called()

    def test_malformed_license_cannot_authorize(self):
        for body in [{}, {"licenca": {"status": "ATIVA"}, "servidor_agora": "2026-11-20T12:00:00Z"},
                     status_body(status="ATIVA", plano="OUTRO"), status_body(vitalicia="no"),
                     {**status_body(), "servidor_agora": "ontem"}, {"active": True, "status": "ACTIVE"}]:
            with self.subTest(body=body):
                self.authenticated()
                self.client.respond(ApiResult(200, body))
                self.factory.assert_not_called()
                self.assertIn("resposta", self.controller.login_window.message.text())

    def test_license_network_error_is_not_denial_and_keeps_session(self):
        self.authenticated()
        self.client.respond(ApiResult(error="network"))
        self.assertIn("conectar", self.controller.login_window.message.text())
        self.assertEqual(self.controller.auth.access_token, "private-access")
        self.assertEqual(self.controller.login_window.enter.text(), "Tentar novamente")
        self.factory.assert_not_called()

    def test_license_retry_button_checks_again(self):
        self.authenticated()
        self.client.respond(ApiResult(error="timeout"))
        self.controller.login_window.enter.click()
        self.assertEqual(self.client.calls[-1][0], "/licencas/status")

    def test_license_401_refreshes_once_with_machine_id_then_retries(self):
        self.authenticated()
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        path, payload, _ = self.client.calls[-1]
        self.assertEqual((path, payload), ("/auth/refresh", {"refresh_token": "private-refresh",
                                                             "id_maquina": MACHINE_ID}))
        self.client.respond(ApiResult(200, ROTATED))
        self.assertEqual(self.client.calls[-1][:2], ("/licencas/status", "fake-new-access"))
        self.client.respond(active())
        self.factory.assert_called_once()

    def test_license_401_twice_requires_new_login(self):
        self.authenticated()
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        self.client.respond(ApiResult(200, ROTATED))
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        self.assertIn("sessão expirou", self.controller.login_window.message.text())
        self.assertIsNone(self.controller.auth.access_token)
        self.assertEqual(self.client.paths().count("/auth/refresh"), 1)
        self.factory.assert_not_called()

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
        self.client.respond(active())
        self.factory.assert_not_called()

    def test_machine_id_failure_blocks_login_without_any_request(self):
        from dtf_manager.services.machine_id import MachineIdError

        def broken():
            raise MachineIdError("sem hardware")
        controller = build_controller(self.app, self.client, factory=self.factory, machine_id=broken)
        self.addCleanup(lambda: dispose_controller(self.app, controller))
        controller.start()
        self.assertEqual(self.client.calls, [])
        self.assertIn("suporte", controller.login_window.message.text())
        self.assertFalse(controller.login_window.enter.isEnabled())

    def test_tokens_and_password_never_logged(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logging.getLogger().addHandler(handler)
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.authenticated()
                self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
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

    def transport(self, reply, timeout_ms=15000, **kwargs):
        manager = FakeManager(reply)
        client = ApiClient(manager=manager, timeout_ms=timeout_ms, **kwargs)
        self.addCleanup(client.cancel_all)
        return client, manager

    def test_post_json_headers_and_cleanup(self):
        reply = FakeReply(body=json.dumps(TOKENS).encode())
        client, manager = self.transport(reply)
        results = []
        client.post_json("/auth/login", {"email": "a", "senha": "b"}, results.append)
        self.assertEqual(manager.request.url().toString(), BASE_URL + "/auth/login")
        self.assertEqual(bytes(manager.request.rawHeader("Accept")), b"application/json")
        self.assertEqual(bytes(manager.request.rawHeader("Content-Type")), b"application/json")
        self.assertEqual(json.loads(manager.body), {"email": "a", "senha": "b"})
        self.assertEqual(manager.request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute),
                         QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        reply.finished.emit()
        self.assertEqual(results[0].data, TOKENS)
        self.assertTrue(reply.deleted)
        self.assertFalse(client._pending)

    def test_base_url_comes_from_configuration(self):
        with patch.dict(os.environ, {"DTF_API_URL": "http://localhost:8000"}):
            client, manager = self.transport(FakeReply())
        client.get("/licencas/status", Mock(), access_token="a")
        self.assertEqual(manager.request.url().toString(), "http://localhost:8000/licencas/status")

    def test_custom_header_and_bearer_on_get_and_bearer_on_post(self):
        client, manager = self.transport(FakeReply())
        client.get("/licencas/status", Mock(), access_token="tok", headers={"X-Id-Maquina": "abc"})
        self.assertEqual(bytes(manager.request.rawHeader("X-Id-Maquina")), b"abc")
        self.assertEqual(bytes(manager.request.rawHeader("Authorization")), b"Bearer tok")
        client.post_json("/licencas/ativar-chave", {"chave": "k"}, Mock(), access_token="tok")
        self.assertEqual(bytes(manager.request.rawHeader("Authorization")), b"Bearer tok")

    def test_bearer_and_invalid_json(self):
        for body in [b"not-json", b"[]", b"\xff"]:
            with self.subTest(body=body):
                reply = FakeReply(body=body)
                client, manager = self.transport(reply)
                results = []
                client.get("/licencas/status", results.append, access_token="private-access")
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
                client.get("/licencas/status", results.append, access_token="a")
                reply.finished.emit()
                self.assertEqual(results[0].error, expected)
                self.assertTrue(reply.deleted)

    def test_error_body_exposes_code_message_license_and_server_time_only(self):
        body = json.dumps({"error": {"code": "LICENCA_EXPIRADA", "message": "Venceu.\x00\x07"},
                           "licenca": license_data(status="EXPIRADA"),
                           "servidor_agora": "2026-11-26T18:00:01Z", "segredo": "private-extra"}).encode()
        reply = FakeReply(status=403, body=body)
        client, _ = self.transport(reply)
        results = []
        client.get("/licencas/status", results.append, access_token="a")
        reply.finished.emit()
        result = results[0]
        self.assertEqual((result.error_code, result.error_message), ("LICENCA_EXPIRADA", "Venceu."))
        self.assertEqual(result.error_license["status"], "EXPIRADA")
        self.assertEqual(result.server_now, "2026-11-26T18:00:01Z")
        self.assertNotIn("private-extra", repr(result.__dict__.values()).replace("dict_values", ""))

    def test_retry_after_is_read_only_for_429_and_validated(self):
        for header, expected in [("120", 120), ("abc", None), ("-5", None), ("0", None), ("999999", None)]:
            with self.subTest(header=header):
                reply = FakeReply(status=429, body=b'{"error":{"code":"MUITAS_TENTATIVAS"}}',
                                  headers={"Retry-After": header})
                client, _ = self.transport(reply)
                results = []
                client.post_json("/auth/login", {}, results.append)
                reply.finished.emit()
                self.assertEqual(results[0].retry_after, expected)
                self.assertEqual(results[0].error_code, "MUITAS_TENTATIVAS")
        reply = FakeReply(status=503, body=b"{}", headers={"Retry-After": "10"})
        client, _ = self.transport(reply)
        results = []
        client.post_json("/auth/login", {}, results.append)
        reply.finished.emit()
        self.assertIsNone(results[0].retry_after)

    def test_total_timeout_aborts_and_cleans_reply(self):
        reply = FakeReply()
        client, _ = self.transport(reply, timeout_ms=1)
        results = []
        client.get("/licencas/status", results.append, access_token="a")
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
            factory.assert_called_once_with(app, development_no_auth=False)
            controller.start.assert_called_once_with()
            main.assert_not_called()
        self.assertEqual(QCoreApplication.organizationName(), "DTF Manager")
        self.assertEqual(QCoreApplication.applicationName(), "DTF Manager")
        self.assertEqual(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation),
                         expected_path)

    def test_no_auth_needs_the_environment_opt_in(self):
        from dtf_manager.core.bootstrap import run_application
        controller = Mock()
        for env, expected in [({}, False), ({"DTF_ALLOW_NO_AUTH": "1"}, True)]:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=False), \
                 patch("dtf_manager.core.application_controller.ApplicationController",
                       return_value=controller) as factory, \
                 patch.object(QApplication, "exec", return_value=0):
                if not env:
                    os.environ.pop("DTF_ALLOW_NO_AUTH", None)
                run_application(development_no_auth=True)
                self.assertEqual(factory.call_args.kwargs["development_no_auth"], expected)

    def test_app_refuses_no_auth_without_opt_in(self):
        env = {k: v for k, v in os.environ.items() if k != "DTF_ALLOW_NO_AUTH"}
        result = subprocess.run([sys.executable, "app.py", "--no-auth"], capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1], timeout=30, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("DTF_ALLOW_NO_AUTH=1", result.stderr)

    def test_invalid_api_url_is_reported_and_never_used(self):
        from dtf_manager.core.bootstrap import run_application
        app = QApplication.instance() or QApplication([])
        with patch.dict(os.environ, {"DTF_API_URL": "http://insecure.example.com"}), \
             patch("dtf_manager.core.bootstrap.QMessageBox.critical") as critical, \
             patch.object(QApplication, "exec", return_value=0):
            self.assertEqual(run_application(), 2)
        self.assertIn("DTF_API_URL", critical.call_args.args[2])
        self.assertIsNotNone(app)

    def test_real_event_loop_exits_when_login_closes_without_requests(self):
        script = """
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tests.license_fakes import build_controller
class Client:
    def cancel_all(self): pass
    def post_json(self, *args, **kwargs): raise AssertionError('Unexpected HTTP')
    def get(self, *args, **kwargs): raise AssertionError('Unexpected HTTP')
def forbidden_main(): raise AssertionError('Unexpected MainWindow')
app = QApplication([])
controller = build_controller(app, Client(), factory=forbidden_main)
controller.start()
QTimer.singleShot(20, controller.login_window.close)
result = app.exec()
assert controller._stopped
assert controller.main_window is None
raise SystemExit(result)
"""
        result = subprocess.run([sys.executable, "-c", script],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
