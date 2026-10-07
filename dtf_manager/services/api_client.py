"""Asynchronous HTTP transport. Response bodies and credentials are never logged."""
from dataclasses import dataclass
import json
from typing import Callable
from dtf_manager.core import auth_timing

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


BASE_URL = "https://dtf-manager-api-production.up.railway.app"


@dataclass(frozen=True, repr=False)
class ApiResult:
    status: int = 0
    data: dict | None = None
    error: str | None = None
    error_code: str | None = None


class ApiClient(QObject):
    def __init__(self, parent=None, *, manager=None, timeout_ms=15000):
        super().__init__(parent)
        self._manager = manager if manager is not None else QNetworkAccessManager(self)
        self._timeout_ms = timeout_ms
        self._pending = set()

    def post_json(self, path: str, payload: dict, callback: Callable):
        return self._request("POST", path, callback, payload=payload)

    def get(self, path: str, callback: Callable, *, access_token: str):
        return self._request("GET", path, callback, access_token=access_token)

    def _request(self, method, path, callback, *, payload=None, access_token=None):
        request = QNetworkRequest(QUrl(BASE_URL + path))
        request.setRawHeader(b"Content-Type", b"application/json")
        request.setRawHeader(b"Accept", b"application/json")
        # Never forward credentials to a redirected host or endpoint.
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(self._timeout_ms)
        request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute,
                             QNetworkRequest.LoadControl.Manual)
        request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute,
                             QNetworkRequest.LoadControl.Manual)
        if access_token:
            request.setRawHeader(b"Authorization", ("Bearer " + access_token).encode("utf-8"))
        timing_stage = {"/auth/login": "login_http", "/auth/refresh": "refresh_http",
                        "/license/status": "license_http"}.get(path)
        if path == "/auth/login":
            auth_timing.login_dispatch()
        http_started = auth_timing.start_clock()
        reply = (self._manager.post(request, json.dumps(payload).encode("utf-8"))
                 if method == "POST" else self._manager.get(request))
        self._pending.add(reply)
        timer = QTimer(reply)
        timer.setSingleShot(True)
        expired = [False]

        def timeout():
            expired[0] = True
            reply.abort()

        def finished():
            if timing_stage:
                auth_timing.emit(timing_stage, http_started)
            timer.stop()
            self._pending.discard(reply)
            try:
                status = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
                if expired[0] or reply.error() == QNetworkReply.NetworkError.TimeoutError:
                    result = ApiResult(status, error="timeout")
                elif not status or (reply.error() != QNetworkReply.NetworkError.NoError
                                    and 200 <= status < 300):
                    result = ApiResult(status, error="network")
                elif not 200 <= status < 300:
                    code = None
                    try:
                        body = json.loads(bytes(reply.readAll()))
                        error_body = body.get("error") if isinstance(body, dict) else None
                        candidate = error_body.get("code") if isinstance(error_body, dict) else None
                        if (isinstance(candidate, str) and len(candidate) <= 80
                                and candidate.replace("_", "").isalnum()):
                            code = candidate
                    except (ValueError, UnicodeError):
                        pass
                    result = ApiResult(status, error="http", error_code=code)
                else:
                    try:
                        data = json.loads(bytes(reply.readAll()))
                        if not isinstance(data, dict):
                            raise ValueError("Expected object")
                        result = ApiResult(status, data=data)
                    except (ValueError, UnicodeError):
                        result = ApiResult(status, error="invalid_json")
            finally:
                reply.deleteLater()
            callback(result)

        timer.timeout.connect(timeout)
        reply.finished.connect(finished)
        timer.start(self._timeout_ms)
        return reply

    def cancel_all(self):
        for reply in tuple(self._pending):
            reply.abort()
