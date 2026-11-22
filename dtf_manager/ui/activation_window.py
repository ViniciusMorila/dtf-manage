from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from dtf_manager.core.constants import APP_NAME
from dtf_manager.utils.forms import validate_email

PLANS_TEXT = ("Planos: Mensal (1 mês) · Semestral (6 meses) · Anual (12 meses) · Vitalício.\n"
              "Após o pagamento você recebe uma chave de ativação de uso único.")


class ActivationWindow(QWidget):
    """Activation key screen.

    Expired license (no session): asks e-mail, password and key.
    Early renewal (valid session): asks only the key.
    """

    activate_requested = Signal(str, str, str)   # key, e-mail, password ("" in session mode)
    subscribe_requested = Signal()
    plans_requested = Signal()   # optional purchase page (DTF_PAYMENT_URL)
    back_requested = Signal()
    cancel_requested = Signal()
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME + " - Ativar licença")
        self.setObjectName("appRoot")
        self.setMinimumWidth(460)
        self._busy = False
        self._session_mode = False
        self._renewing = False
        self._site_available = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        self.title = QLabel("Licença vencida")
        self.title.setObjectName("sectionTitle")
        layout.addWidget(self.title)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        self.plans_text = QLabel(PLANS_TEXT)
        self.plans_text.setObjectName("muted")
        self.plans_text.setWordWrap(True)
        layout.addWidget(self.plans_text)
        self.subscribe = QPushButton("Assinar")
        self.subscribe.setObjectName("primaryButton")
        layout.addWidget(self.subscribe)
        self.plans = QPushButton("Ver planos no site")
        self.plans.hide()
        layout.addWidget(self.plans)
        card = QFrame()
        card.setObjectName("sidebar")
        fields = QVBoxLayout(card)
        self.email_label = QLabel("E-mail")
        self.email = QLineEdit()
        self.email.setMaxLength(254)
        self.password_label = QLabel("Senha")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        key_label = QLabel("Chave de ativação")
        self.key = QLineEdit()
        self.key.setMaxLength(64)
        self.key.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        for widget in (self.email_label, self.email, self.password_label, self.password,
                       key_label, self.key):
            fields.addWidget(widget)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        fields.addWidget(self.message)
        self.activate = QPushButton("Ativar chave")
        self.activate.setObjectName("primaryButton")
        fields.addWidget(self.activate)
        self.back = QPushButton("Voltar ao login")
        fields.addWidget(self.back)
        self.cancel = QPushButton("Cancelar")
        self.cancel.hide()
        fields.addWidget(self.cancel)
        layout.addWidget(card)
        self.set_mode(session=False)
        for field in (self.email, self.password, self.key):
            field.returnPressed.connect(self._submit)
        self.activate.clicked.connect(self._submit)
        self.subscribe.clicked.connect(self.subscribe_requested)
        self.plans.clicked.connect(self.plans_requested)
        self.back.clicked.connect(self.back_requested)
        self.cancel.clicked.connect(self.cancel_requested)

    @property
    def session_mode(self):
        return self._session_mode

    def set_payment_site(self, available):
        self._site_available = available
        self.plans.setVisible(available and not self._renewing)

    def set_mode(self, *, session, cancelable=False, email="", trial_ended=False):
        self._session_mode = session
        for widget in (self.email_label, self.email, self.password_label, self.password):
            widget.setVisible(not session)
        self.back.setVisible(not session)
        self.cancel.setVisible(cancelable)
        # Renewal from the account menu: only the key, nothing about subscribing.
        self._renewing = cancelable
        for widget in (self.subscribe, self.plans_text):
            widget.setVisible(not cancelable)
        self.plans.setVisible(self._site_available and not cancelable)
        self.title.setText("Renovar licença" if cancelable else
                           "Fim do período de teste" if trial_ended else "Licença vencida")
        self.intro.setText(
            "Informe a chave de ativação para renovar. A validade do plano é somada à atual."
            if cancelable else
            ("Seu período de teste terminou. " if trial_ended else "")
            + f"Para continuar usando o {APP_NAME}, assine um plano ou ative uma chave. "
            + ("" if session else "Informe o e-mail e a senha da sua conta."))
        if email and not self.email.text():
            self.email.setText(email)
        self.set_busy(False)

    def _submit(self):
        if self._busy:
            return
        key = self.key.text().strip()
        if not key:
            self.message.setText("Informe a chave de ativação.")
            return
        email, password = "", ""
        if not self._session_mode:
            email, password = self.email.text().strip(), self.password.text()
            error = validate_email(email) or (None if password else "Informe sua senha.")
            if error:
                self.message.setText(error)
                return
        self.set_busy(True)
        self.password.clear()
        self.activate_requested.emit(key, email, password)

    def set_busy(self, busy, text="Ativando..."):
        self._busy = busy
        for widget in (self.email, self.password, self.key, self.activate, self.back, self.cancel,
                       self.subscribe, self.plans):
            widget.setEnabled(not busy)
        self.activate.setText(text if busy else "Ativar chave")
        if busy:
            self.message.clear()

    def show_failure(self, message):
        self.set_busy(False)
        self.message.setText(message)

    def closeEvent(self, event):
        self.password.clear()
        self.key.clear()
        self.closed.emit()
        super().closeEvent(event)
