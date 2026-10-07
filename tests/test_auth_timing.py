import contextlib
import io
import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import Mock
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget
from dtf_manager.core import auth_timing
from dtf_manager.core.application_controller import ApplicationController
from dtf_manager.services.api_client import ApiClient, ApiResult
from tests.test_authentication import FakeClient, FakeManager, FakeReply, TOKENS
from tests.session_fakes import FakeSessionStorage
from dtf_manager.services.art_directory_scanner import scan_art_directory
from dtf_manager.services.session_storage import SessionStorage, CREDENTIAL_USER


class AuthTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_monotonic_conversion_whitelist_and_opt_in(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.dict(os.environ, {"DTF_AUTH_TIMING": "1"}), patch.object(auth_timing, "perf_counter", return_value=1.32):
            auth_timing.emit("login_http", 1.0)
            auth_timing.emit("private-token", 1.0)
        self.assertEqual(output.getvalue(), "[AUTH TIMING] login_http: 320.0 ms\n")
        with contextlib.redirect_stdout(output), patch.dict(os.environ, {"DTF_AUTH_TIMING": "0"}):
            auth_timing.emit("total", 1.0)
        self.assertEqual(output.getvalue().count("\n"), 1)

    def test_disabled_diagnostics_do_not_read_clock_or_create_qt_objects(self):
        output = io.StringIO()
        window = QWidget()
        before = list(window.children())
        with contextlib.redirect_stdout(output), patch.dict(os.environ, {"DTF_AUTH_TIMING": "0"}), patch.object(auth_timing, "perf_counter", side_effect=AssertionError("unexpected clock")):
            auth_timing.start_application()
            auth_timing.start_login()
            auth_timing.bootstrap_complete()
            with auth_timing.span("login_http"):
                pass
            auth_timing.emit_duration("login_http", 1.0)
            auth_timing.observe_first_paint(window)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(list(window.children()), before)
        window.close()

    def test_span_preserves_exceptions_and_does_not_log_exception_data(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.dict(os.environ, {"DTF_AUTH_TIMING": "1"}):
            with self.assertRaises(ValueError):
                with auth_timing.span("credential_read"):
                    raise ValueError("private-error")
        self.assertEqual(output.getvalue().count("[AUTH TIMING] credential_read:"), 1)
        self.assertNotIn("private-error", output.getvalue())

    def test_catalog_breakdown_preserves_results_and_never_logs_paths(self):
        with TemporaryDirectory() as folder:
            image = Path(folder) / "private-image.png"
            Image.new("RGB", (5, 5)).save(image)
            expected = scan_art_directory(Path(folder))
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch.dict(os.environ, {"DTF_AUTH_TIMING": "1"}):
                actual = scan_art_directory(Path(folder))
            self.assertEqual(actual, expected)
            self.assertEqual(output.getvalue(), "")
            self.assertNotIn(folder, output.getvalue())
            self.assertNotIn("private-image", output.getvalue())

    def test_credential_breakdown_uses_fake_api_and_never_logs_credential(self):
        api = SimpleNamespace(CRED_TYPE_GENERIC=1, CredRead=Mock(return_value={
            "UserName": CREDENTIAL_USER, "CredentialBlob": "private-refresh".encode("utf-16-le")}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.dict(os.environ, {"DTF_AUTH_TIMING": "1"}):
            with auth_timing.span("credential_read"):
                self.assertEqual(SessionStorage(credential_api=api).load_refresh_token(), "private-refresh")
        self.assertEqual(re.findall(r"\[AUTH TIMING\] (\w+):", output.getvalue()),
                         ["credential_read"])
        api.CredRead.assert_called_once()
        self.assertNotIn("private-refresh", output.getvalue())

    def test_http_logs_no_request_or_response_data(self):
        output = io.StringIO()
        reply = FakeReply(body=b'{"access_token":"secret-response"}')
        client = ApiClient(manager=FakeManager(reply))
        with contextlib.redirect_stdout(output), patch.dict(os.environ, {"DTF_AUTH_TIMING": "1"}):
            auth_timing.start_login()
            client.post_json("/auth/login", {"password": "secret-password"}, lambda result: None)
            reply.finished.emit()
        self.assertNotIn("secret", output.getvalue())
        self.assertEqual(len(output.getvalue().splitlines()), 2)
        for line in output.getvalue().splitlines():
            self.assertRegex(line, r"^\[AUTH TIMING\] (login_dispatch|login_http): \d+\.\d ms$")

    def test_restore_preserves_calls_and_measures_first_paint_once(self):
        client = FakeClient()
        window = QWidget()
        storage = FakeSessionStorage("saved-refresh")
        controller = ApplicationController(self.app, client=client, storage=storage,
                                           main_window_factory=lambda: window)
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), patch.dict(os.environ, {"DTF_AUTH_TIMING": "1"}):
                auth_timing.start_application()
                controller.start()
                client.respond(ApiResult(200, data=TOKENS))
                client.respond(ApiResult(200, data={"active": True, "status": "ACTIVE"}))
                self.app.processEvents()
                window.update()
                self.app.processEvents()
            self.assertEqual([call[0] for call in client.calls], ["/auth/refresh", "/license/status"])
            stages = re.findall(r"\[AUTH TIMING\] (\w+):", output.getvalue())
            stages = [stage for stage in stages if stage != "main_window_usable"]
            self.assertEqual(stages, ["app_start", "app_bootstrap", "session_lock", "credential_read",
                                     "credential_write", "license_to_main_window",
                                     "main_window_init", "main_window_first_paint", "total"])
            self.assertTrue(window.isVisible())
        finally:
            controller.stop()
            controller._transitioning = True
            controller.login_window.close()
            window.close()
