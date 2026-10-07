"""Opt-in aggregate timings. Never accept request, credential, or path data."""
from contextlib import contextmanager
import os
from time import perf_counter


_STAGES = frozenset({
    "app_start", "app_bootstrap", "bootstrap_ui_import", "controller_login_ui",
    "session_lock", "login_dispatch", "login_http", "refresh_http",
    "credential_read", "credential_write", "license_http", "license_to_main_window",
    "main_ui_import", "main_window_init", "main_window_first_paint", "main_window_usable",
    "total", "main_build_ui", "main_restore_roll", "main_folder_catalog",
})
_origin = None
_login_origin = None


def enabled():
    return os.environ.get("DTF_AUTH_TIMING") == "1"


def start_clock():
    return perf_counter() if enabled() else None


def emit_duration(stage, seconds):
    if enabled() and stage in _STAGES:
        try:
            print(f"[AUTH TIMING] {stage}: {seconds * 1000:.1f} ms", flush=True)
        except (OSError, ValueError):
            pass


def emit(stage, started):
    if enabled() and stage in _STAGES and started is not None:
        emit_duration(stage, perf_counter() - started)


def start_application():
    global _origin, _login_origin
    _origin = start_clock()
    _login_origin = None
    emit("app_start", _origin)


def start_login():
    global _origin, _login_origin
    _origin = _login_origin = start_clock()


def login_dispatch():
    emit("login_dispatch", _login_origin)


def bootstrap_complete():
    emit("app_bootstrap", _origin)


@contextmanager
def span(stage):
    started = start_clock()
    try:
        yield
    finally:
        emit(stage, started)


def observe_first_paint(window):
    """Observe a single paint and event-loop return; no periodic monitoring."""
    if not enabled():
        return
    from PySide6.QtCore import QEvent, QObject, QTimer

    origin = _origin
    shown = perf_counter()

    class FirstPaint(QObject):
        def usable(self):
            emit("main_window_usable", origin)
            self.deleteLater()

        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Paint:
                emit("main_window_first_paint", shown)
                emit("total", origin)
                watched.removeEventFilter(self)
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self.usable)
                timer.start(0)
            return False

    observer = FirstPaint(window)
    window.installEventFilter(observer)
    window._auth_timing_observer = observer
