"""Shared fakes and payload builders for the authentication and license tests."""
from PySide6.QtCore import QByteArray, QObject, Signal
from PySide6.QtNetwork import QNetworkReply

from dtf_manager.core.application_controller import ApplicationController
from dtf_manager.services.api_client import ApiResult
from tests.session_fakes import MACHINE_ID, FakeLicenseStore, FakeSessionStorage

NOW = "2026-11-20T12:00:00Z"
TOKENS = {"access_token": "private-access", "refresh_token": "private-refresh",
          "token_type": "bearer", "expires_in": 900}
ROTATED = {"access_token": "fake-new-access", "refresh_token": "fake-refresh-B",
           "token_type": "bearer", "expires_in": 900}


def license_data(**changes):
    data = {"plano": "MENSAL", "status": "ATIVA", "data_ativacao": "2026-11-19T18:00:00Z",
            "data_expiracao": "2026-12-26T18:00:00Z", "dias_restantes": 37, "vitalicia": False}
    data.update(changes)
    return data


def status_body(server_now=NOW, **changes):
    return {"licenca": license_data(**changes), "servidor_agora": server_now}


def active(**changes):
    return ApiResult(200, status_body(**changes))


def http_error(status, code=None, message=None, retry_after=None, license=None):
    return ApiResult(status, error="http", error_code=code, error_message=message,
                     retry_after=retry_after, error_license=license)


class FakeClient:
    """Records calls; ``respond`` answers the most recent one."""

    def __init__(self):
        self.calls = []
        self.headers = []
        self.bearers = []

    def post_json(self, path, payload, callback, *, access_token=None):
        self.calls.append((path, payload, callback))
        self.headers.append({})
        self.bearers.append(access_token)

    def get(self, path, callback, *, access_token, headers=None):
        self.calls.append((path, access_token, callback))
        self.headers.append(headers or {})
        self.bearers.append(access_token)

    def respond(self, result):
        self.calls[-1][-1](result)

    def paths(self):
        return [call[0] for call in self.calls]

    def cancel_all(self):
        pass


class FakeReply(QObject):
    finished = Signal()

    def __init__(self, status=200, body=b"{}", error=QNetworkReply.NetworkError.NoError, headers=None):
        super().__init__()
        self.status, self.body, self.network_error = status, body, error
        self.headers = headers or {}
        self.deleted = False

    def attribute(self, attr):
        return self.status

    def error(self):
        return self.network_error

    def readAll(self):
        return QByteArray(self.body)

    def rawHeader(self, name):
        return QByteArray(self.headers.get(bytes(name).decode(), "").encode())

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


def build_controller(app, client, *, storage=None, factory=None, store=None, **kwargs):
    """Controller wired only to in-memory fakes (no Credential Manager, DPAPI or hardware)."""
    kwargs.setdefault("machine_id", MACHINE_ID)
    return ApplicationController(
        app, client=client, storage=storage if storage is not None else FakeSessionStorage(),
        main_window_factory=factory,
        license_store=store if store is not None else FakeLicenseStore(), **kwargs)


def dispose_controller(app, controller, *windows):
    controller.stop()
    controller._transitioning = True
    for window in (controller._login_window, controller._register_window,
                   controller._activation_window):
        if window is not None:
            window.close()
            window.deleteLater()
    for window in windows:
        window.close()
        window.deleteLater()
    controller.deleteLater()
    app.processEvents()
