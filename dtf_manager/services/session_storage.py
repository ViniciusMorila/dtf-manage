"""One protected refresh credential, scoped to this API and Windows user."""
import hashlib
from pathlib import Path
import sys

from PySide6.QtCore import QLockFile, QStandardPaths

from dtf_manager.core import config


TARGET_PREFIX = "DTF Manager/session/"
# Fixed name plus the environment (production, or dev-<hash> for a custom API).
CREDENTIAL_TARGET = TARGET_PREFIX + "production"
CREDENTIAL_USER = "desktop-refresh-token"


class SessionStorageError(RuntimeError):
    """Sanitized local error; never contains underlying credential data."""


class SessionStorage:
    def __init__(self, *, credential_api=None, environment=None):
        self._api = credential_api
        self.target = TARGET_PREFIX + (environment or config.environment_name())
        self._lock = None

    def _credential_api(self):
        if self._api is None:
            try:
                if sys.platform != "win32":
                    raise RuntimeError()
                from win32ctypes.pywin32 import win32cred
                self._api = win32cred
            except Exception:
                raise SessionStorageError("Armazenamento protegido do Windows indisponível.") from None
        return self._api

    def acquire_session_lock(self):
        """Prevent two processes rotating the same saved token.

        The temporary lock contains only process metadata, never credentials.
        QLockFile detects dead processes, including after an abnormal exit.
        """
        if self._lock is not None:
            return True
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
        name = hashlib.sha256(self.target.encode()).hexdigest()[:20]
        lock = QLockFile(str(Path(folder) / ("dtf_manager_session_" + name + ".lock")))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            if lock.error() == QLockFile.LockError.LockFailedError:
                return False
            raise SessionStorageError("Não foi possível proteger o uso exclusivo da sessão.")
        self._lock = lock
        return True

    def release_session_lock(self):
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None

    def save_refresh_token(self, token):
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise SessionStorageError("Refresh token inválido para armazenamento.")
        try:
            api = self._credential_api()
            # One CredWrite replaces the value, without archiving the old token.
            api.CredWrite({"Type": api.CRED_TYPE_GENERIC,
                           "TargetName": self.target,
                           "UserName": CREDENTIAL_USER,
                           "CredentialBlob": token,
                           "Persist": api.CRED_PERSIST_LOCAL_MACHINE,
                           "Comment": "DTF Manager - sessão protegida"}, 0)
        except Exception:
            raise SessionStorageError("Não foi possível salvar a sessão protegida.") from None

    def load_refresh_token(self):
        try:
            api = self._credential_api()
            credential = api.CredRead(TargetName=self.target, Type=api.CRED_TYPE_GENERIC)
            if credential["UserName"] != CREDENTIAL_USER:
                raise ValueError()
            blob = credential["CredentialBlob"]
            token = blob.decode("utf-16-le") if isinstance(blob, bytes) else blob
            if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                raise ValueError()
            return token
        except Exception as error:
            if getattr(error, "winerror", None) == 1168:
                return None
            raise SessionStorageError("Não foi possível ler a sessão protegida.") from None

    def delete_refresh_token(self):
        try:
            api = self._credential_api()
            api.CredDelete(TargetName=self.target, Type=api.CRED_TYPE_GENERIC)
        except Exception as error:
            if getattr(error, "winerror", None) == 1168:
                return
            raise SessionStorageError("Não foi possível apagar a sessão protegida.") from None
