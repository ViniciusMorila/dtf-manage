"""Asynchronous HTTP transport. Response bodies and credentials are never logged."""
from dataclasses import dataclass
import json
from typing import Callable
from dtf_manager.core import auth_timing, config

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


_CONTROL = dict.fromkeys(range(32))
_TIMING_STAGES = {"/auth/login": "login_http", "/auth/refresh": "refresh_http",
                  "/licencas/status": "license_http"}


@dataclass(frozen=True, repr=False)
class ApiResult:
    status: int = 0
    data: dict | None = None
    error: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_after: int | None = None
    error_license: dict | None = None
    server_now: str | None = None


def _clean_text(value, limit):
    if not isinstance(value, str):
        return None
    text = value.translate(_CONTROL).strip()[:limit]
    return text or None


def _retry_after(reply):
    try:
        seconds = int(bytes(reply.rawHeader(b"Retry-After")).decode("ascii").strip())
    except (AttributeError, TypeError, ValueError, UnicodeError):
        return None
    return seconds if 0 < seconds <= 86400 else None


def _http_error(reply, status):
    """Keep only the documented error fields; never retain the raw body."""
    code = message = license_data = server_now = None
    try:
        body = json.loads(bytes(reply.readAll()))
        if isinstance(body, dict):
            error_body = body.get("error")
            if isinstance(error_body, dict):
                candidate = error_body.get("code")
                if (isinstance(candidate, str) and len(candidate) <= 80
                        and candidate.replace("_", "").isalnum()):
                    code = candidate
                message = _clean_text(error_body.get("message"), 300)
            if isinstance(body.get("licenca"), dict):
                license_data = body["licenca"]
            server_now = _clean_text(body.get("servidor_agora"), 40)
    except (ValueError, UnicodeError):
        pass
    return ApiResult(status, error="http", error_code=code, error_message=message,
                     retry_after=_retry_after(reply) if status == 429 else None,
                     error_license=license_data, server_now=server_now)


class ApiClient(QObject):
    def __init__(self, parent=None, *, manager=None, timeout_ms=15000, base_url=None):
        super().__init__(parent)
        self.base_url = base_url if base_url is not None else config.api_base_url()
        self._manager = manager if manager is not None else QNetworkAccessManager(self)
        self._timeout_ms = timeout_ms
        self._pending = set()

    def post_json(self, path: str, payload: dict, callback: Callable, *, access_token=None):
        return self._request("POST", path, callback, payload=payload, access_token=access_token)

    def get(self, path: str, callback: Callable, *, access_token: str, headers=None):
        return self._request("GET", path, callback, access_token=access_token, headers=headers)

    def _request(self, method, path, callback, *, payload=None, access_token=None, headers=None):
        request = QNetworkRequest(QUrl(self.base_url + path))
        request.setRawHeader(b"Content-Type", b"application/json")
        request.setRawHeader(b"Accept", b"application/json")
        for name, value in (headers or {}).items():
            request.setRawHeader(name.encode("ascii"), str(value).encode("utf-8"))
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
        timing_stage = _TIMING_STAGES.get(path)
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
                    result = _http_error(reply, status)
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
