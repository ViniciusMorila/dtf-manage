import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from dtf_manager.services.session_storage import (
    CREDENTIAL_TARGET, CREDENTIAL_USER, SessionStorage, SessionStorageError,
)


class SessionStorageTests(unittest.TestCase):
    def setUp(self):
        self.api = SimpleNamespace(CRED_TYPE_GENERIC=1, CRED_PERSIST_LOCAL_MACHINE=2,
                                   CredWrite=Mock(), CredRead=Mock(), CredDelete=Mock())
        self.storage = SessionStorage(credential_api=self.api)

    def test_one_credential_write_replaces_refresh_without_any_backup(self):
        self.storage.save_refresh_token("fake-refresh-B")
        self.api.CredWrite.assert_called_once()
        credential, flags = self.api.CredWrite.call_args.args
        self.assertEqual(credential["CredentialBlob"], "fake-refresh-B")
        self.assertEqual(credential["TargetName"], CREDENTIAL_TARGET)
        self.assertEqual(credential["UserName"], CREDENTIAL_USER)
        self.assertEqual(credential["Persist"], 2)
        self.assertEqual(flags, 0)
        self.api.CredRead.assert_not_called()

    def test_load_decodes_windows_blob(self):
        self.api.CredRead.return_value = {"UserName": CREDENTIAL_USER,
                                          "CredentialBlob": "fake-refresh-B".encode("utf-16-le")}
        self.assertEqual(self.storage.load_refresh_token(), "fake-refresh-B")
        self.api.CredRead.assert_called_once_with(TargetName=CREDENTIAL_TARGET, Type=1)

    def test_missing_credential_and_idempotent_delete(self):
        missing = OSError("synthetic error")
        missing.winerror = 1168
        self.api.CredRead.side_effect = missing
        self.api.CredDelete.side_effect = missing
        self.assertIsNone(self.storage.load_refresh_token())
        self.storage.delete_refresh_token()

    def test_delete_only_the_application_credential(self):
        self.storage.delete_refresh_token()
        self.api.CredDelete.assert_called_once_with(TargetName=CREDENTIAL_TARGET, Type=1)

    def test_errors_never_expose_original_exception_or_credential(self):
        for method, underlying, args in [
            (self.storage.save_refresh_token, self.api.CredWrite, ("fake-secret-token",)),
            (self.storage.load_refresh_token, self.api.CredRead, ()),
            (self.storage.delete_refresh_token, self.api.CredDelete, ()),
        ]:
            with self.subTest(method=method.__name__):
                underlying.side_effect = RuntimeError("fake-secret-token")
                with self.assertRaises(SessionStorageError) as caught:
                    method(*args)
                self.assertNotIn("fake-secret-token", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_invalid_token_never_written(self):
        for token in [None, "", "bad token", "bad\r\ntoken"]:
            with self.subTest(token=token):
                with self.assertRaises(SessionStorageError):
                    self.storage.save_refresh_token(token)
        self.api.CredWrite.assert_not_called()

    def test_corrupt_or_foreign_credential_rejected_without_printing_blob(self):
        for value in [{"UserName": "other", "CredentialBlob": b"bad"},
                      {"UserName": CREDENTIAL_USER, "CredentialBlob": b"\xff"}]:
            self.api.CredRead.return_value = value
            with self.assertRaises(SessionStorageError):
                self.storage.load_refresh_token()

    def test_no_platform_or_library_fallback(self):
        storage = SessionStorage()
        with patch("dtf_manager.services.session_storage.sys.platform", "linux"):
            with self.assertRaises(SessionStorageError):
                storage.save_refresh_token("fake-refresh")
        self.assertIsNone(storage._api)

    def test_process_lock_blocks_second_instance_then_releases(self):
        # Only temporary, token-free locks; the real credential API is not called.
        app = QCoreApplication.instance() or QCoreApplication([])
        with TemporaryDirectory() as folder, patch(
                "dtf_manager.services.session_storage.QStandardPaths.writableLocation", return_value=folder):
            second = SessionStorage(credential_api=self.api)
            try:
                self.assertTrue(self.storage.acquire_session_lock())
                self.assertFalse(second.acquire_session_lock())
                self.assertTrue(self.storage.acquire_session_lock())
                self.assertNotIn("refresh", next(Path(folder).glob("*.lock")).read_text())
                self.storage.release_session_lock()
                self.assertTrue(second.acquire_session_lock())
            finally:
                self.storage.release_session_lock()
                second.release_session_lock()
        self.api.CredRead.assert_not_called()
