"""Authentication state lives only in this process."""
from PySide6.QtCore import QObject, Signal


def failure_kind(result):
    if result.error in {"network", "timeout", "invalid_json"}:
        return result.error
    if result.status == 401:
        return "unauthorized"
    return "server"


class AuthService(QObject):
    authenticated = Signal()
    failed = Signal(str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.access_token = None
        self.refresh_token = None
        self._generation = 0

    def clear(self):
        self._generation += 1
        self.access_token = None
        self.refresh_token = None

    def login(self, email, password):
        self.clear()
        generation = self._generation

        def completed(result):
            if generation != self._generation:
                return
            if result.error or not 200 <= result.status < 300:
                self.failed.emit(failure_kind(result))
                return
            data = result.data or {}
            access = data.get("access_token")
            refresh = data.get("refresh_token")
            token_type = data.get("token_type", "bearer")
            if (not isinstance(access, str) or not access.strip()
                    or not isinstance(refresh, str) or not refresh.strip()
                    or any(c.isspace() for c in access)
                    or not isinstance(token_type, str) or token_type.lower() != "bearer"):
                self.failed.emit("invalid_json")
                return
            self.access_token = access
            self.refresh_token = refresh
            self.authenticated.emit()

        self.client.post_json("/auth/login", {"email": email, "password": password}, completed)
