from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox
from dtf_manager.core import auth_timing, config

from dtf_manager.services.api_client import ApiClient
from dtf_manager.services.api_failure import ApiFailure
from dtf_manager.services.auth_service import AuthService
from dtf_manager.services.error_messages import describe
from dtf_manager.services.license_service import LicenseService
from dtf_manager.services.license_store import LicenseStore
from dtf_manager.models.license import LicenseInfo
from dtf_manager.services.offline_grace import OfflineGrace
from dtf_manager.services.plans import PlansError, load_plans
from dtf_manager.services.whatsapp import build_message, build_url
from dtf_manager.services.session_storage import SessionStorage, SessionStorageError

LICENSE_CHECK_INTERVAL_MS = 60 * 60 * 1000   # periodic validation while the app is open
NEEDS_ACTIVATION = {"LICENCA_EXPIRADA", "LICENCA_NAO_ENCONTRADA"}
REFUSED = {"LICENCA_BLOQUEADA", "MAQUINA_DIFERENTE", "MAQUINA_EM_USO", "ID_MAQUINA_INVALIDO"}
WHATSAPP_MISSING = ("O número de WhatsApp para assinatura não está configurado "
                    "(DTF_WHATSAPP_NUMBER). Entre em contato com o suporte.")
GRACE_MESSAGES = {
    "clock_rolled_back": ("O relógio do computador parece ter sido atrasado, então a carência offline "
                          "não é contada. Ajuste a data e a hora do Windows e conecte-se à internet "
                          "para validar a licença."),
    "grace_exhausted": "Sem conexão há mais de 72 horas. Conecte-se à internet para validar sua licença.",
    "expired": "A licença salva neste computador já venceu. Conecte-se à internet para validar sua licença.",
}
LOCAL_MESSAGES = {
    "storage": ("Não foi possível acessar ou atualizar a sessão protegida do Windows. "
                "A sessão não foi liberada. Tente entrar novamente."),
    "no_session": "",
}


def create_main_window():
    with auth_timing.span("main_ui_import"):
        from dtf_manager.ui.main_window import MainWindow
    return MainWindow()


def _open_url(url):
    return QDesktopServices.openUrl(QUrl(url))


class ApplicationController(QObject):
    def __init__(self, app, *, client=None, main_window_factory=None, storage=None,
                 development_no_auth=False, machine_id=None, license_store=None, grace=None,
                 license_interval_ms=LICENSE_CHECK_INTERVAL_MS, url_opener=None,
                 plans_loader=None):
        super().__init__(app)
        self.app = app
        self.client = client if client is not None else ApiClient(self)
        self.storage = storage if storage is not None else SessionStorage()
        self._machine_id_source = machine_id
        self.auth = AuthService(self.client, self, storage=self.storage,
                                machine_id=self._get_machine_id)
        self.license = LicenseService(self.client, self, machine_id=self._get_machine_id)
        self.grace = grace if grace is not None else OfflineGrace(
            license_store if license_store is not None else LicenseStore(self._get_machine_id))
        self._open_url = url_opener or _open_url
        self._plans_loader = plans_loader or load_plans
        self._subscribe_window = None
        self._subscribe_return = None
        self._subscribe_plans = ()
        self._expired_reason = ""
        self._last_message = ""
        self._contact = {}                    # name/email/phone known in this session
        self._login_window = None
        self._register_window = None
        self._activation_window = None
        self.main_window = None
        self._factory = main_window_factory or create_main_window
        self._development_no_auth = development_no_auth
        self._busy = False
        self._stopped = False
        self._transitioning = False
        self._session_locked = False
        self._logout_pending = False
        self._in_grace = False
        self._license_status = None
        self._license_refreshed = False       # one refresh+retry after a 401 on the status call
        self._pending_credentials = None      # e-mail/password between two chained API calls
        self._last_email = ""
        self._last_activation_key = None
        self._activation_retry_key = None
        self._renewal = False
        self._license_timer = QTimer(self)
        self._license_timer.setInterval(license_interval_ms)
        self._license_timer.timeout.connect(self._periodic_check)
        self.auth.authenticated.connect(self._authenticated)
        self.auth.failed.connect(self._auth_failed)
        self.auth.logged_out.connect(self._logged_out)
        self.auth.logout_failed.connect(self._logout_failed)
        self.auth.registered.connect(self._registered)
        self.auth.register_failed.connect(self._register_failed)
        self.license.failed.connect(self._license_failed)
        self.license.checked.connect(self._license_checked)
        self.license.activated.connect(self._activated)
        self.license.activation_failed.connect(self._activation_failed)
        app.aboutToQuit.connect(self.stop)

    def _get_machine_id(self):
        source = self._machine_id_source
        if callable(source):
            return source()
        if source is not None:
            return source
        from dtf_manager.services.machine_id import get_machine_id
        return get_machine_id()

    # ---- windows -------------------------------------------------------------------

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
            self._login_window.register_requested.connect(self.show_register)
            self._login_window.activate_requested.connect(self.show_activation)
            self._login_window.closed.connect(self._login_closed)
        return self._login_window

    @property
    def register_window(self):
        if self._register_window is None:
            from dtf_manager.ui.register_window import RegisterWindow
            self._register_window = RegisterWindow()
            self._register_window.submitted.connect(self.register)
            self._register_window.back_requested.connect(self.show_login)
            self._register_window.closed.connect(self._login_closed)
        return self._register_window

    @property
    def activation_window(self):
        if self._activation_window is None:
            from dtf_manager.ui.activation_window import ActivationWindow
            self._activation_window = ActivationWindow()
            self._activation_window.activate_requested.connect(self.activate)
            self._activation_window.subscribe_requested.connect(self._subscribe_from_expired)
            self._activation_window.plans_requested.connect(self.open_plans)
            self._activation_window.set_payment_site(config.payment_url() is not None)
            self._activation_window.back_requested.connect(self.show_login)
            self._activation_window.cancel_requested.connect(self._cancel_renewal)
            self._activation_window.closed.connect(self._activation_closed)
        return self._activation_window

    def _show(self, window):
        for other in (self._login_window, self._register_window, self._activation_window,
                      self._subscribe_window):
            if other is not None and other is not window:
                other.hide()
        window.show()

    def show_login(self):
        if self._stopped or self._session_locked:
            return
        self._pending_credentials = None
        self._show(self.login_window)

    def show_register(self):
        if self._busy or self._stopped or self._session_locked:
            return
        self.register_window.reset()
        self._show(self.register_window)

    def show_activation(self):
        """'Tenho uma chave': activation with e-mail and password (no session)."""
        if self._busy or self._stopped or self._session_locked:
            return
        self._renewal = False
        window = self.activation_window
        window.set_mode(session=False, email=self.login_window.email.text().strip() or self._last_email)
        window.show_failure("")
        self._show(window)

    def open_plans(self):
        """Optional secondary purchase page (only when DTF_PAYMENT_URL is configured)."""
        url = config.payment_url()
        if url:
            self._open_url(url)

    # ---- manual subscription through WhatsApp --------------------------------------

    def _subscribe_from_expired(self):
        self.show_subscribe(self._expired_reason)

    def show_menu_subscribe(self):
        """Entry from the Conta menu and the status bar button."""
        info = self._license_status.info if self._license_status is not None else None
        reason = ("Você está no período de teste. Assine para continuar usando depois dele."
                  if info is not None and info.plano == "TESTE" else "")
        self.show_subscribe(reason)

    def show_subscribe(self, reason=""):
        if self._stopped or self._session_locked or self._logout_pending:
            return
        window = self._subscribe_window
        if window is None:
            try:
                self._subscribe_plans = self._plans_loader()
            except PlansError as error:
                QMessageBox.warning(self.main_window, "Assinar", str(error))
                return
            from dtf_manager.ui.subscribe_window import SubscribeWindow
            window = self._subscribe_window = SubscribeWindow(self._subscribe_plans)
            window.plan_chosen.connect(self.choose_plan)
            window.copy_requested.connect(self.copy_message)
            window.have_key_requested.connect(self._subscribe_have_key)
            window.back_requested.connect(self._subscribe_back)
            window.closed.connect(self._subscribe_closed)
        visible = [w for w in (self._login_window, self._register_window, self._activation_window)
                   if w is not None and w.isVisible()]
        self._subscribe_return = visible[0] if visible else None
        window.reset()
        window.set_reason(reason)
        window.show_notice("" if config.whatsapp_number() else WHATSAPP_MISSING)
        self._last_message = ""
        self._show(window)

    def _contact_for_message(self):
        contact = dict(self.grace.contact())
        contact.update({k: v for k, v in self._contact.items() if v})
        return contact

    def choose_plan(self, code):
        window = self._subscribe_window
        plan = next((p for p in self._subscribe_plans if p.code == code), None)
        if window is None or plan is None:
            return
        number = config.whatsapp_number()
        if not number:
            window.show_notice(WHATSAPP_MISSING)
            return
        window.set_busy(True)
        # Plan and contact only: never a password, token or machine id.
        contact = self._contact_for_message()
        self._last_message = build_message(plan, name=contact.get("name", ""),
                                           email=contact.get("email", ""),
                                           phone=contact.get("phone", ""))
        opened = self._open_url(build_url(number, self._last_message))
        window.show_guidance()
        window.show_notice(
            "Não foi possível abrir o WhatsApp. Use o botão Copiar mensagem e envie para "
            f"+{number}." if opened is False else "")

    def copy_message(self):
        if self._last_message and self._subscribe_window is not None:
            self.app.clipboard().setText(self._last_message)
            self._subscribe_window.show_notice("Mensagem copiada.")

    def _subscribe_have_key(self):
        origin = self._subscribe_return
        if origin is not None and origin is self._activation_window:
            self._show(origin)
        elif self.main_window is not None and self.main_window.isEnabled():
            self._subscribe_window.hide()
            self.show_renewal()
        else:
            self.show_activation()

    def _subscribe_back(self):
        origin = self._subscribe_return
        if origin is not None:
            self._show(origin)
        else:
            self._subscribe_window.hide()

    def _subscribe_closed(self):
        if self._transitioning:
            return
        if self.main_window is not None and self.main_window.isEnabled():
            return  # closed the plan screen of a working session
        self.stop()
        self.app.quit()

    # ---- startup -------------------------------------------------------------------

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
        if self._development_no_auth:
            self._open_main_window()
            return
        try:
            self._get_machine_id()
        except Exception:
            self.login_window.show_locked(self._machine_message())
            self.login_window.show()
            return
        self.refresh_session()

    @staticmethod
    def _machine_message():
        return describe(ApiFailure("api", "ID_MAQUINA_INVALIDO"))

    # ---- authentication ------------------------------------------------------------

    def refresh_session(self):
        """One central refresh, available to future authenticated consumers."""
        if self._stopped or self._session_locked or self._logout_pending:
            return
        self._busy = True
        if self.main_window is None and self._login_window is not None:
            self.login_window.set_busy(True, "Restaurando sessão...")
            self._show(self.login_window)
        self.auth.refresh_session()

    def login(self, email, password):
        if (self._busy or self._stopped or self._session_locked
                or (self.main_window is not None and self.main_window.isEnabled())):
            return
        self._busy = True
        self._last_email = email
        self._contact["email"] = email.strip()
        self.login_window.set_busy(True)
        self.auth.login(email, password)

    def show_new_login(self):
        if self._busy or self._stopped or self._session_locked:
            return
        self.auth.clear()
        self.license.cancel()
        self.login_window.reset_for_login("Entrar novamente criará uma nova sessão. A sessão anterior não será revogada por esta ação.")

    def register(self, name, phone, email, password):
        if self._busy or self._stopped or self._session_locked:
            return
        self._busy = True
        self._last_email = email
        self._contact.update({"name": name, "email": email.strip(), "phone": phone})
        self._pending_credentials = (email, password)
        self.auth.register(name, phone, email, password)

    def _registered(self, _license):
        if self._stopped:
            return
        credentials, self._pending_credentials = self._pending_credentials, None
        self._busy = False
        if not credentials:
            return
        # The API returns no tokens after the registration: log in right away.
        self._busy = True
        self.register_window.set_busy(True, "Entrando...")
        self.auth.login(*credentials)

    def _register_failed(self, kind):
        if self._stopped:
            return
        self._busy = False
        self._pending_credentials = None
        text = (self._machine_message() if kind == "machine_id"
                else describe(self.auth.last_failure))
        self.register_window.show_failure(text)

    def _authenticated(self):
        if self._stopped or self._logout_pending:
            return
        if self._activation_retry_key:
            key, self._activation_retry_key = self._activation_retry_key, None
            self.license.activate_key(key, access_token=self.auth.access_token)
            return
        self.check_license()

    def _auth_failed(self, kind):
        if self._stopped:
            return
        self._busy = False
        self._license_refreshed = False
        failure = self.auth.last_failure
        operation = self.auth.last_operation
        if self._activation_retry_key:
            # Renewal with an expired access token whose refresh also failed.
            self._activation_retry_key = None
            self.activation_window.set_mode(session=False, cancelable=self._renewal,
                                            email=self._last_email)
            self.activation_window.show_failure("Sua sessão expirou. Informe e-mail e senha para continuar.")
            return
        self._pending_credentials = None
        restoring = operation == "refresh"
        if restoring and kind == "unauthorized":
            # INVALID_REFRESH_TOKEN: ended by a login elsewhere, a block or a reset.
            failure = replace(failure, code="INVALID_REFRESH_TOKEN")
            self.grace.clear()
        if failure.code in NEEDS_ACTIVATION and kind != "storage":
            self._show_expired(failure)
            return
        if restoring and failure.unreachable:
            self._try_grace(failure, retry="refresh")
            return
        if kind in LOCAL_MESSAGES:
            message = LOCAL_MESSAGES[kind]
        elif kind == "machine_id":
            message = self._machine_message()
        elif kind == "invalid_json" and restoring:
            message = "Não foi possível validar a resposta do servidor. Entre novamente para criar uma nova sessão."
        else:
            message = describe(failure)
        preserved = restoring and (failure.unreachable or kind in {"rate_limited", "api"})
        retry_refresh = preserved
        if restoring and failure.unreachable:
            message += "\nO refresh salvo foi preservado. A renovação pode ter sido processada pelo servidor; a nova tentativa será manual."
        self._lock_main(message)
        self.login_window.show_failure(message, retry_refresh=retry_refresh,
                                       allow_new_login=retry_refresh)
        self._show(self.login_window)

    # ---- license validation --------------------------------------------------------

    def check_license(self):
        if self._stopped or self._logout_pending:
            return
        if not self.auth.access_token:
            # No access token yet (after an offline start, for instance): renew it first.
            self.refresh_session()
            return
        self._busy = True
        if self.main_window is None and self._login_window is not None:
            self.login_window.set_busy(True, "Consultando licença...")
        self.license.check(self.auth.access_token)

    def _periodic_check(self):
        if (self._stopped or self._busy or self._logout_pending or self._development_no_auth
                or self.main_window is None or not self.main_window.isEnabled()):
            return
        self.check_license()

    def _license_checked(self, status):
        license_checked = auth_timing.start_clock()
        if self._stopped or self._logout_pending:
            return
        self._busy = False
        self._license_refreshed = False
        if not status.info.active:
            code = "LICENCA_BLOQUEADA" if status.info.status == "BLOQUEADA" else "LICENCA_EXPIRADA"
            failure = ApiFailure("api", code, status=403, license=status.info.to_dict())
            if code in NEEDS_ACTIVATION:
                self._show_expired(failure)
            else:
                self._license_refused(failure)
            return
        self.grace.record_success(status, self._contact)
        self._in_grace = False
        self._license_status = status
        auth_timing.emit("license_to_main_window", license_checked)
        self._open_main_window()

    def _license_failed(self, kind):
        if self._stopped:
            return
        self._busy = False
        failure = self.license.last_failure
        if failure.kind == "unauthorized":
            if not self._license_refreshed:
                # Access token expired: renew it with the machine id and retry once.
                self._license_refreshed = True
                self._busy = True
                self.auth.access_token = None
                self.auth.refresh_session()
                return
            self._license_refreshed = False
            self.auth.clear()
            self._lock_main(describe(ApiFailure("unauthorized", "INVALID_ACCESS_TOKEN")))
            self.login_window.show_failure(describe(ApiFailure("unauthorized", "INVALID_ACCESS_TOKEN")))
            self._show(self.login_window)
            return
        if failure.code in NEEDS_ACTIVATION:
            self._show_expired(failure)
        elif failure.code in REFUSED:
            self._license_refused(failure)
        elif failure.unreachable:
            self._try_grace(failure, retry="license")
        else:
            message = (self._machine_message() if kind == "machine_id" else describe(failure))
            self._lock_main(message)
            self.login_window.show_failure(message, retry_license=kind != "machine_id",
                                           allow_new_login=True)
            self._show(self.login_window)

    def _show_expired(self, failure):
        """License expired or missing: open the key screen (the API refused the login)."""
        for key, value in self.grace.contact().items():   # keep it for the WhatsApp message
            self._contact.setdefault(key, value)
        self.grace.clear()
        self._in_grace = False
        message = describe(failure)
        self._lock_main(message)
        expired = LicenseInfo.from_dict(failure.license)
        trial_ended = expired is not None and expired.plano == "TESTE"
        self._expired_reason = ("Seu período de teste terminou." if trial_ended
                                else "Sua licença venceu.")
        window = self.activation_window
        self._renewal = False
        window.set_mode(session=bool(self.auth.access_token), email=self._last_email,
                        trial_ended=trial_ended)
        window.show_failure(message)
        self._show(window)

    def _license_refused(self, failure):
        """Blocked license or other machine: definite refusal, never the grace."""
        self.grace.clear()
        self._in_grace = False
        message = describe(failure)
        self._lock_main(message)
        self.login_window.show_failure(message, retry_license=bool(self.auth.access_token),
                                       allow_new_login=True)
        self._show(self.login_window)

    def _try_grace(self, failure, *, retry):
        decision = self.grace.evaluate()
        if decision.allowed:
            self._in_grace = True
            self._license_refreshed = False
            self._license_status = None
            self._open_main_window(offline=decision)
            return
        message = describe(failure)
        if decision.reason in GRACE_MESSAGES:
            message += "\n" + GRACE_MESSAGES[decision.reason]
        if retry == "refresh":
            message += "\nO refresh salvo foi preservado. A renovação pode ter sido processada pelo servidor; a nova tentativa será manual."
        self._lock_main(message)
        self.login_window.show_failure(message, retry_license=retry == "license",
                                       retry_refresh=retry == "refresh", allow_new_login=True)
        self._show(self.login_window)

    def _lock_main(self, reason):
        """Save the active operation, warn, then block the main window."""
        self._license_timer.stop()
        window = self.main_window
        if window is None or not window.isEnabled():
            return
        if hasattr(window, "save_for_license_lock"):
            window.save_for_license_lock()
        QMessageBox.warning(window, "Licença",
                            reason + "\nSeu trabalho foi salvo automaticamente.")
        window.setEnabled(False)

    # ---- activation ----------------------------------------------------------------

    def show_renewal(self):
        """Early renewal from the account menu."""
        if self._busy or self._stopped or self._logout_pending or self.main_window is None:
            return
        self._renewal = True
        window = self.activation_window
        window.set_mode(session=bool(self.auth.access_token), cancelable=True,
                        email=self._last_email)
        window.show_failure("")
        window.show()

    def _cancel_renewal(self):
        if self._activation_window is not None:
            self._activation_window.hide()

    def activate(self, key, email, password):
        if self._busy or self._stopped or self._session_locked:
            return
        self._busy = True
        self._last_activation_key = key
        window = self.activation_window
        if window.session_mode and self.auth.access_token:
            self.license.activate_key(key, access_token=self.auth.access_token)
        else:
            self._last_email = email
            self._contact["email"] = email.strip()
            self._pending_credentials = (email, password)
            self.license.activate_key(key, email=email, password=password)

    def _activated(self, status, plan):
        if self._stopped:
            return
        self._busy = False
        self._last_activation_key = None
        self.grace.record_success(status, self._contact)
        credentials, self._pending_credentials = self._pending_credentials, None
        if credentials and not self.auth.access_token:
            # The key was applied with e-mail and password: sign in to get the session.
            self._busy = True
            self.activation_window.set_busy(True, "Entrando...")
            self.auth.login(*credentials)
            return
        self._in_grace = False
        self._license_status = status
        QMessageBox.information(self.main_window or self.activation_window, "Licença ativada",
                                f"Licença ativada: plano {status.info.plan_name}.")
        self._open_main_window()

    def _activation_failed(self, kind):
        if self._stopped:
            return
        self._busy = False
        failure = self.license.last_failure
        key, self._last_activation_key = self._last_activation_key, None
        window = self.activation_window
        if kind == "unauthorized" and window.session_mode and key:
            # Expired access token while renewing: refresh and retry once.
            self._activation_retry_key = key
            self._busy = True
            self.auth.refresh_session()
            return
        self._pending_credentials = None
        message = self._machine_message() if kind == "machine_id" else describe(failure)
        window.show_failure(message)

    # ---- main window ---------------------------------------------------------------

    def _open_main_window(self, *, offline=None):
        if self.main_window is None:
            with auth_timing.span("main_window_init"):
                self.main_window = self._factory()
            if hasattr(self.main_window, "logout_requested"):
                self.main_window.logout_requested.connect(self.logout)
            if hasattr(self.main_window, "renew_requested"):
                self.main_window.renew_requested.connect(self.show_renewal)
                self.main_window.subscribe_requested.connect(self.show_menu_subscribe)
                self.main_window.plans_requested.connect(self.open_plans)
                self.main_window.set_payment_site(config.payment_url() is not None)
            if self._development_no_auth:
                self.main_window.setWindowTitle(
                    self.main_window.windowTitle() + " [DEV - SEM AUTENTICACAO]"
                )
                logout_button = getattr(self.main_window, "logout_button", None)
                if logout_button is not None:
                    logout_button.setText("Sair do aplicativo")
        self.main_window.setEnabled(True)
        self._apply_license_state(offline)
        if not self.main_window.isVisible():
            auth_timing.observe_first_paint(self.main_window)
            self.main_window.showMaximized()
        self._transitioning = True
        for window in (self._login_window, self._register_window, self._activation_window,
                       self._subscribe_window):
            if window is not None:
                window.close()
        self._transitioning = False
        if not self._development_no_auth:
            self._license_timer.start()

    def _apply_license_state(self, offline=None):
        if not hasattr(self.main_window, "set_license_state"):
            return
        if offline is not None:
            self.main_window.set_license_state(offline.info, offline.remaining)
        elif self._license_status is not None:
            self.main_window.set_license_state(self._license_status.info)

    def logout(self):
        if self._logout_pending or self._stopped:
            return
        if self._development_no_auth:
            if (self.main_window is not None
                    and hasattr(self.main_window, "prepare_logout")
                    and not self.main_window.prepare_logout()):
                return
            if self.main_window is not None:
                self.main_window.close()
            return
        if self.main_window is not None:
            if hasattr(self.main_window, "prepare_logout") and not self.main_window.prepare_logout():
                return
            self.main_window.setEnabled(False)
        self._logout_pending = True
        self._license_timer.stop()
        self.license.cancel()
        self.auth.logout()

    def _logout_failed(self, kind):
        if self._stopped:
            return
        self._logout_pending = False
        if self.main_window is not None:
            self.main_window.setEnabled(True)
            self._license_timer.start()
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
            self._license_timer.stop()
            self.auth.logout_locally()

    def _logged_out(self, remote_confirmed):
        if self._stopped:
            return
        self._logout_pending = False
        self._busy = False
        self._in_grace = False
        self._license_status = None
        self._license_timer.stop()
        # Sign out removes the token and the license cache; the machine id is derived
        # from the hardware and is never stored, so it simply stays the same.
        self.grace.clear()
        self.license.cancel()
        self.client.cancel_all()
        self.login_window.reset_for_login(
            "Você saiu da conta." if remote_confirmed
            else "Sessão encerrada neste computador. A revogação no servidor não foi confirmada.")
        # Show login first so Qt does not quit when the main window closes.
        self._show(self.login_window)
        if self.main_window is not None:
            self.main_window.close()
            self.main_window.deleteLater()
            self.main_window = None

    def _login_closed(self):
        if not self._transitioning:
            self.stop()
            self.app.quit()

    def _activation_closed(self):
        if self._transitioning:
            return
        if self._renewal and self.main_window is not None and self.main_window.isEnabled():
            return  # closed an early renewal: keep working
        self.stop()
        self.app.quit()

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._license_timer.stop()
        self.license.cancel()
        self.auth.clear()
        self.client.cancel_all()
        self.storage.release_session_lock()
