from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox
from dtf_manager.core import auth_timing

from dtf_manager.services.api_client import ApiClient
from dtf_manager.services.auth_service import AuthService
from dtf_manager.services.license_service import LicenseService
from dtf_manager.services.session_storage import SessionStorage, SessionStorageError


def create_main_window():
    with auth_timing.span("main_ui_import"):
        from dtf_manager.ui.main_window import MainWindow
    return MainWindow()


class ApplicationController(QObject):
    def __init__(self, app, *, client=None, main_window_factory=None, storage=None):
        super().__init__(app)
        self.app = app
        self.client = client if client is not None else ApiClient(self)
        self.storage = storage if storage is not None else SessionStorage()
        self.auth = AuthService(self.client, self, storage=self.storage)
        self.license = LicenseService(self.client, self)
        self._login_window = None
        self.main_window = None
        self._factory = main_window_factory or create_main_window
        self._busy = False
        self._stopped = False
        self._transitioning = False
        self._session_locked = False
        self._logout_pending = False
        self.auth.authenticated.connect(self._authenticated)
        self.auth.failed.connect(lambda kind: self._failed(kind, False))
        self.auth.logged_out.connect(self._logged_out)
        self.auth.logout_failed.connect(self._logout_failed)
        self.license.failed.connect(lambda kind: self._failed(kind, True))
        self.license.checked.connect(self._license_checked)
        app.aboutToQuit.connect(self.stop)

    @property
    def login_window(self):
        # Compatibility for consumers that explicitly need the login window.
        if self._login_window is None:
            with auth_timing.span("controller_login_ui"):
                from dtf_manager.ui.login_window import LoginWindow
                self._login_window = LoginWindow()
            self._login_window.login_requested.connect(self.login)
            self._login_window.retry_requested.connect(self.check_license)
            self._login_window.refresh_retry_requested.connect(self.refresh_session)
            self._login_window.new_login_requested.connect(self.show_new_login)
            self._login_window.closed.connect(self._login_closed)
        return self._login_window

    def start(self):
        auth_timing.bootstrap_complete()
        try:
            with auth_timing.span("session_lock"):
                self._session_locked = not self.storage.acquire_session_lock()
        except SessionStorageError:
            self._session_locked = True
            self.login_window.show_locked("Não foi possível proteger o uso da sessão neste computador. Feche o aplicativo e tente novamente.")
            self.login_window.show()
            return
        if self._session_locked:
            self.login_window.show_locked()
            self.login_window.show()
            return
        self.refresh_session()

    def refresh_session(self):
        """One central refresh, available to future authenticated consumers."""
        if self._stopped or self._session_locked or self._logout_pending:
            return
        self._busy = True
        if self.main_window is None and self._login_window is not None:
            self.login_window.set_busy(True, "Restaurando sessão...")
            self.login_window.show()
        self.auth.refresh_session()

    def login(self, email, password):
        if (self._busy or self._stopped or self._session_locked
                or (self.main_window is not None and self.main_window.isEnabled())):
            return
        self._busy = True
        self.login_window.set_busy(True)
        self.auth.login(email, password)

    def show_new_login(self):
        if self._busy or self._stopped or self._session_locked:
            return
        self.auth.clear()
        self.license.cancel()
        self.login_window.reset_for_login("Entrar novamente criará uma nova sessão. A sessão anterior não será revogada por esta ação.")

    def _authenticated(self):
        if not self._stopped and not self._logout_pending:
            self.check_license()

    def check_license(self):
        if self._stopped or not self.auth.access_token or self._logout_pending:
            return
        self._busy = True
        if self.main_window is None and self._login_window is not None:
            self.login_window.set_busy(True, "Consultando licença...")
        self.license.check(self.auth.access_token)

    def _failed(self, kind, license_stage):
        if self._stopped:
            return
        self._busy = False
        restoring = not license_stage and self.auth.last_operation == "refresh"
        messages = {
            "network": "Não foi possível conectar ao servidor. Verifique sua conexão e tente novamente.",
            "timeout": "O servidor demorou para responder. Tente novamente.",
            "invalid_json": ("Não foi possível validar a resposta do servidor. Entre novamente para criar uma nova sessão."
                             if restoring else "Não foi possível validar a resposta do servidor. Tente novamente."),
            "server": "O serviço está indisponível no momento. Tente novamente.",
            "storage": "Não foi possível acessar ou atualizar a sessão protegida do Windows. A sessão não foi liberada. Tente entrar novamente.",
            "unauthorized": ("Sua sessão é inválida. Entre novamente." if license_stage or restoring
                             else "E-mail ou senha inválidos."),
            "no_session": "",
        }
        retry_license = license_stage and kind != "unauthorized"
        retry_refresh = restoring and kind in {"network", "timeout", "server"}
        message = messages.get(kind, messages["server"])
        if retry_refresh:
            message += "\nO refresh salvo foi preservado. A renovação pode ter sido processada pelo servidor; a nova tentativa será manual."
        if not retry_license:
            self.auth.clear()
        if self.main_window is not None:
            # A future runtime refresh failure must not silently leave an invalid
            # session usable. Existing work stays visible but locked until login.
            self.main_window.setEnabled(False)
        self.login_window.show_failure(message, retry_license=retry_license,
                                       retry_refresh=retry_refresh,
                                       allow_new_login=retry_refresh or retry_license)
        self.login_window.show()

    def _license_checked(self, allowed, status, plan):
        license_checked = auth_timing.start_clock()
        if self._stopped or self._logout_pending:
            return
        self._busy = False
        if not allowed:
            message = "Sua licença não está ativa.\nStatus: " + status[:80]
            if plan:
                message += "\nPlano: " + plan[:120]
            if self.main_window is not None:
                self.main_window.setEnabled(False)
            self.login_window.show_failure(message, retry_license=True, allow_new_login=True)
            self.login_window.show()
            return
        if self.main_window is None:
            auth_timing.emit("license_to_main_window", license_checked)
            with auth_timing.span("main_window_init"):
                self.main_window = self._factory()
            if hasattr(self.main_window, "logout_requested"):
                self.main_window.logout_requested.connect(self.logout)
        self.main_window.setEnabled(True)
        auth_timing.observe_first_paint(self.main_window)
        self.main_window.showMaximized()
        self._transitioning = True
        if self._login_window is not None:
            self._login_window.close()
        self._transitioning = False

    def logout(self):
        if self._logout_pending or self._stopped:
            return
        if self.main_window is not None:
            if hasattr(self.main_window, "prepare_logout") and not self.main_window.prepare_logout():
                return
            self.main_window.setEnabled(False)
        self._logout_pending = True
        self.license.cancel()
        self.auth.logout()

    def _logout_failed(self, kind):
        if self._stopped:
            return
        self._logout_pending = False
        if self.main_window is not None:
            self.main_window.setEnabled(True)
            if hasattr(self.main_window, "cancel_logout"):
                self.main_window.cancel_logout()
        parent = self.main_window or self.login_window
        if kind == "storage":
            message = "Não foi possível apagar ou acessar a sessão protegida do Windows. Tente sair da conta novamente."
            if self.auth.remote_logout_confirmed:
                message += "\nA revogação no servidor foi confirmada, mas a exclusão local não foi concluída."
            QMessageBox.warning(parent, "Sair da conta", message)
            return
        answer = QMessageBox.question(
            parent, "Logout remoto não confirmado",
            "Não foi possível confirmar a revogação da sessão no servidor.\n"
            "Deseja sair apenas neste computador? O refresh local será apagado, "
            "mas a revogação no servidor não estará confirmada.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            if self.main_window is not None:
                if hasattr(self.main_window, "prepare_logout") and not self.main_window.prepare_logout():
                    return
            self._logout_pending = True
            self.auth.logout_locally()

    def _logged_out(self, remote_confirmed):
        if self._stopped:
            return
        self._logout_pending = False
        self._busy = False
        self.license.cancel()
        self.client.cancel_all()
        self.login_window.reset_for_login(
            "Você saiu da conta." if remote_confirmed
            else "Sessão encerrada neste computador. A revogação no servidor não foi confirmada.")
        # Show login first so Qt does not quit when the main window closes.
        self.login_window.show()
        if self.main_window is not None:
            self.main_window.close()
            self.main_window.deleteLater()
            self.main_window = None

    def _login_closed(self):
        if not self._transitioning:
            self.stop()
            self.app.quit()

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self.license.cancel()
        self.auth.clear()
        self.client.cancel_all()
        self.storage.release_session_lock()
