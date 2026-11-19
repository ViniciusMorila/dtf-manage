"""Small Qt bootstrap; operational UI is imported only after startup mode is selected."""
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from dtf_manager.ui.styles import APP_STYLE


def run_application(*, development_no_auth=False) -> int:
    from dtf_manager.core.application_controller import ApplicationController
    app = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("DTF Manager")
    QCoreApplication.setApplicationName("DTF Manager")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    app.setFont(QFont("Segoe UI", 10))
    controller = ApplicationController(app, development_no_auth=development_no_auth)
    controller.start()
    return app.exec()
