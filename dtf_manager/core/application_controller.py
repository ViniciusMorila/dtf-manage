from PySide6.QtCore import QObject

from dtf_manager.services.api_client import ApiClient
from dtf_manager.services.auth_service import AuthService
from dtf_manager.services.license_service import LicenseService
from dtf_manager.ui.login_window import LoginWindow


def create_main_window():
    from dtf_manager.ui.main_window import MainWindow
    return MainWindow()


class ApplicationController(QObject):
    def __init__(self, app, *, client=None, main_window_factory=None):
        super().__init__(app)
        self.app = app
        self.client = client if client is not None else ApiClient(self)
        self.auth = AuthService(self.client, self)
        self.license = LicenseService(self.client, self)
        self.login_window = LoginWindow()
        self.main_window = None
        self._factory = main_window_factory or create_main_window
        self._busy = False
        self._stopped = False
        self._transitioning = False
        self.login_window.login_requested.connect(self.login)
        self.login_window.retry_requested.connect(self.check_license)
        self.login_window.closed.connect(self._login_closed)
        self.auth.authenticated.connect(self._authenticated)
        self.auth.failed.connect(lambda kind: self._failed(kind, False))
        self.license.failed.connect(lambda kind: self._failed(kind, True))
        self.license.checked.connect(self._license_checked)
        app.aboutToQuit.connect(self.stop)

    def start(self):
        self.login_window.show()

    def login(self, email, password):
        if self._busy or self._stopped or self.main_window is not None:
            return
        self._busy = True
        self.login_window.set_busy(True)
        self.auth.login(email, password)

    def _authenticated(self):
        if not self._stopped:
            self.check_license()

    def check_license(self):
        if self._stopped or not self.auth.access_token or self.main_window is not None:
            return
        self._busy = True
        self.login_window.set_busy(True, "Consultando licença...")
        self.license.check(self.auth.access_token)

    def _failed(self, kind, license_stage):
        if self._stopped:
            return
        self._busy = False
        messages = {
            "network": "Não foi possível conectar ao servidor. Verifique sua conexão e tente novamente.",
            "timeout": "O servidor demorou para responder. Tente novamente.",
            "invalid_json": "Não foi possível validar a resposta do servidor. Tente novamente.",
            "server": "O serviço está indisponível no momento. Tente novamente.",
            "unauthorized": ("Sua sessão é inválida. Entre novamente." if license_stage
                             else "E-mail ou senha inválidos."),
        }
        retry = license_stage and kind != "unauthorized"
        if not retry:
            self.auth.clear()
        self.login_window.show_failure(messages.get(kind, messages["server"]), retry_license=retry)

    def _license_checked(self, allowed, status, plan):
        if self._stopped or self.main_window is not None:
            return
        self._busy = False
        if not allowed:
            message = "Sua licença não está ativa.\nStatus: " + status[:80]
            if plan:
                message += "\nPlano: " + plan[:120]
            self.login_window.show_failure(message, retry_license=True)
            return
        self.main_window = self._factory()
        # Show the replacement first, preserving Qt's normal last-window exit.
        self.main_window.showMaximized()
        self._transitioning = True
        self.login_window.close()
        self._transitioning = False

    def _login_closed(self):
        if not self._transitioning:
            self.stop()
            self.app.quit()

    def stop(self):
        self._stopped = True
        self.license.cancel()
        self.auth.clear()
        self.client.cancel_all()
