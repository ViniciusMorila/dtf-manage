"""Small Qt bootstrap; operational UI is imported only after startup mode is selected."""
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
import sys

from dtf_manager.core import app_mutex
from dtf_manager.core.constants import APP_NAME, ICON_FILE
from dtf_manager.core.config import ConfigError, no_auth_allowed
from dtf_manager.core.version import APP_VERSION
from dtf_manager.ui.styles import APP_STYLE


def _set_app_user_model_id() -> None:
    """Windows: own taskbar identity, so the taskbar shows the app icon and not the Python one."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Layera.App")
    except Exception:
        pass


def run_application(*, development_no_auth=False) -> int:
    from dtf_manager.core.application_controller import ApplicationController
    # Defense in depth: never skip authentication in a frozen build or without the opt-in.
    development_no_auth = (development_no_auth and not getattr(sys, "frozen", False)
                           and no_auth_allowed())
    _set_app_user_model_id()
    app = QApplication.instance() or QApplication([])
    app.setWindowIcon(QIcon(str(ICON_FILE)))
    QCoreApplication.setOrganizationName("DTF Manager")
    QCoreApplication.setApplicationName("DTF Manager")
    QCoreApplication.setApplicationVersion(APP_VERSION)
    app_mutex.acquire()           # lets the installer detect (and close) a running app
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    app.setFont(QFont("Segoe UI", 10))
    try:
        controller = ApplicationController(app, development_no_auth=development_no_auth)
    except ConfigError as error:
        QMessageBox.critical(None, APP_NAME, str(error))
        return 2
    controller.start()
    return app.exec()
