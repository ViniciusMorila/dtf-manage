"""Central asynchronous session lifecycle; credentials are never logged."""
from PySide6.QtCore import QObject, Signal
from dtf_manager.core import auth_timing

from dtf_manager.services.session_storage import SessionStorage, SessionStorageError


def failure_kind(result):
    if result.error in {"network", "timeout", "invalid_json"}:
        return result.error
    if result.status == 401:
        return "unauthorized"
    return "server"


class AuthService(QObject):
    # All consumers can await the same result of a single refresh in flight.
    authenticated = Signal()
    failed = Signal(str)
    logged_out = Signal(bool)  # True only after confirmed remote logout.
    logout_failed = Signal(str)

    def __init__(self, client, parent=None, *, storage=None):
        super().__init__(parent)
        self.client = client
        self.storage = storage if storage is not None else SessionStorage()
        self.access_token = None
        self.refresh_token = None
        self.expires_in = None
        self.last_operation = None
        self.remote_logout_confirmed = False
        self._generation = 0
        self._operation = None
        self._logout_waiting = False
        self._refresh_blocked = False

    @property
    def refresh_in_progress(self):
        return self._operation == "refresh"

    def clear(self):
        """Cancel logical requests and clear memory, never persistent storage."""
        self._generation += 1
        self._operation = None
        self._logout_waiting = False
        self.access_token = None
        self.refresh_token = None
        self.expires_in = None

    @staticmethod
    def _tokens(data):
        if not isinstance(data, dict):
            return None
        access, refresh = data.get("access_token"), data.get("refresh_token")
        kind = data.get("token_type", "bearer")
        expiry = data.get("expires_in")
        if (not isinstance(access, str) or not access
                or not isinstance(refresh, str) or not refresh
                or any(c.isspace() for c in access + refresh)
                or not isinstance(kind, str) or kind.lower() != "bearer"
                or type(expiry) is not int or expiry <= 0):
            return None
        return access, refresh, expiry

    def _forget_saved(self):
        try:
            self.storage.delete_refresh_token()
            return True
        except SessionStorageError:
            return False

    def _authentication_failed(self, kind, *, forget=False):
        waiting = self._logout_waiting
        if forget and not self._forget_saved():
            kind = "storage"
        self.clear()
        if waiting:
            self.logout()
        else:
            self.failed.emit(kind)

    def login(self, email, password):
        if self._operation is not None:
            return False
        self.clear()
        self._refresh_blocked = False
        self.last_operation = "login"
        self._operation = "login"
        self._request_tokens("/auth/login", {"email": email, "password": password})
        return True

    def refresh_session(self):
        if self._operation is not None:
            # Repeated callers receive the same authenticated/failed signal.
            return False
        self.last_operation = "refresh"
        if self._refresh_blocked:
            self.failed.emit("invalid_json")
            return False
        try:
            token = self.refresh_token
            if not token:
                with auth_timing.span("credential_read"):
                    token = self.storage.load_refresh_token()
        except SessionStorageError:
            self._authentication_failed("storage")
            return False
        if not token:
            self._authentication_failed("no_session")
            return False
        self._operation = "refresh"
        self._request_tokens("/auth/refresh", {"refresh_token": token})
        return True

    def _request_tokens(self, path, body):
        generation = self._generation
        operation = self._operation
        previous_refresh = body.get("refresh_token")

        def completed(result):
            if generation != self._generation or self._operation != operation:
                return
            if result.error or result.status != 200:
                if (operation == "refresh" and result.status in {401, 422}
                        and result.error not in {"network", "timeout"}):
                    self._authentication_failed("unauthorized", forget=True)
                else:
                    if operation == "refresh" and result.status == 200:
                        # A 200 may have rotated A even when B cannot be decoded.
                        self._refresh_blocked = True
                    self._authentication_failed(failure_kind(result))
                return
            tokens = self._tokens(result.data)
            if not tokens:
                if operation == "refresh":
                    self._refresh_blocked = True
                self._authentication_failed("invalid_json")
                return
            access, refresh, expiry = tokens
            if operation == "refresh" and refresh == previous_refresh:
                self._refresh_blocked = True
                self._authentication_failed("invalid_json")
                return
            try:
                # Persist B BEFORE publishing a usable session or any license call.
                with auth_timing.span("credential_write"):
                    self.storage.save_refresh_token(refresh)
            except SessionStorageError:
                self._refresh_blocked = True
                self._authentication_failed("storage", forget=True)
                return
            self.access_token, self.refresh_token, self.expires_in = tokens
            self._operation = None
            self._refresh_blocked = False
            self.remote_logout_confirmed = False
            if self._logout_waiting:
                self._logout_waiting = False
                self.logout()
            else:
                self.authenticated.emit()

        self.client.post_json(path, body, completed)

    def logout(self):
        if self._operation == "logout":
            return False
        if self._operation in {"refresh", "login"}:
            # Wait for the latest token instead of revoking A while B is created.
            self._logout_waiting = True
            return False
        if self._operation is not None:
            return False
        self.last_operation = "logout"
        try:
            token = self.refresh_token or self.storage.load_refresh_token()
        except SessionStorageError:
            self.logout_failed.emit("storage")
            return False
        if not token:
            self.logout_locally()
            return True
        self._generation += 1
        generation = self._generation
        self._operation = "logout"
        self.remote_logout_confirmed = False

        def completed(result):
            if generation != self._generation or self._operation != "logout":
                return
            self._operation = None
            if result.error or result.status != 200:
                self.logout_failed.emit(failure_kind(result))
                return
            if not result.data or result.data.get("status") != "ok":
                self.logout_failed.emit("invalid_json")
                return
            self.remote_logout_confirmed = True
            self._end_session(True)

        self.client.post_json("/auth/logout", {"refresh_token": token}, completed)
        return True

    def _end_session(self, remote_confirmed):
        self.clear()
        if not self._forget_saved():
            self.logout_failed.emit("storage")
            return False
        self._refresh_blocked = False
        self.logged_out.emit(remote_confirmed)
        return True

    def logout_locally(self):
        """Explicit local exit; never claims server revocation occurred."""
        self.remote_logout_confirmed = False
        return self._end_session(False)
