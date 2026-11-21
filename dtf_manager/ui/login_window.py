from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from dtf_manager.core.constants import APP_NAME
from dtf_manager.core import auth_timing
from dtf_manager.ui.cooldown import Cooldown


class LoginWindow(QWidget):
    login_requested = Signal(str, str)
    retry_requested = Signal()
    refresh_retry_requested = Signal()
    new_login_requested = Signal()
    register_requested = Signal()
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setObjectName("appRoot")
        self.setMinimumWidth(420)
        self._busy = False
        self._cooldown = Cooldown(self)
        self._cooldown.ticked.connect(self._cooldown_ticked)
        self._cooldown.finished.connect(self._cooldown_finished)
        self._license_retry = False
        self._refresh_retry = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        title = QLabel(APP_NAME)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Entre para acessar o DTF Manager"))
        card = QFrame()
        card.setObjectName("sidebar")
        fields = QVBoxLayout(card)
        fields.addWidget(QLabel("E-mail"))
        self.email = QLineEdit()
        self.email.setPlaceholderText("usuario@email.com")
        self.email.setMaxLength(254)
        fields.addWidget(self.email)
        fields.addWidget(QLabel("Senha"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        fields.addWidget(self.password)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        fields.addWidget(self.message)
        self.enter = QPushButton("Entrar")
        self.enter.setObjectName("primaryButton")
        fields.addWidget(self.enter)
        self.register = QPushButton("Criar conta")
        fields.addWidget(self.register)
        self.new_login = QPushButton("Voltar ao login")
        self.new_login.hide()
        fields.addWidget(self.new_login)
        self.exit = QPushButton("Sair")
        self.exit.hide()
        fields.addWidget(self.exit)
        layout.addWidget(card)
        self.enter.clicked.connect(self._submit)
        self.email.returnPressed.connect(self._submit)
        self.password.returnPressed.connect(self._submit)
        self.exit.clicked.connect(self.close)
        self.new_login.clicked.connect(self.new_login_requested)
        self.register.clicked.connect(self.register_requested)

    def _submit(self):
        if self._busy or self._cooldown.active:
            return
        if not self._refresh_retry and not self._license_retry:
            auth_timing.start_login()
        if self._refresh_retry:
            self.set_busy(True, "Restaurando sessão...")
            self.refresh_retry_requested.emit()
            return
        if self._license_retry:
            self.set_busy(True, "Consultando licença...")
            self.retry_requested.emit()
            return
        email, password = self.email.text().strip(), self.password.text()
        if not email or not password:
            self.message.setText("Informe seu e-mail e sua senha.")
            return
        self.set_busy(True)
        self.password.clear()
        self.login_requested.emit(email, password)

    def hold_retry(self, seconds):
        """Keep the retry button disabled during the server Retry-After."""
        self._cooldown.start(seconds)
        self.enter.setEnabled(False)

    def _cooldown_ticked(self, left):
        self.enter.setText(f"Aguarde {left} s")

    def _cooldown_finished(self):
        self.enter.setEnabled(not self._busy)
        self.enter.setText("Tentar novamente" if self._license_retry or self._refresh_retry else "Entrar")

    def set_busy(self, busy, text="Entrando..."):
        self._busy = busy
        self.enter.setEnabled(not busy and not self._cooldown.active)
        retry = self._license_retry or self._refresh_retry
        self.email.setEnabled(not busy and not retry)
        self.password.setEnabled(not busy and not retry)
        self.new_login.setEnabled(not busy)
        self.register.setEnabled(not busy)
        if busy or not self._cooldown.active:
            self.enter.setText(text if busy else ("Tentar novamente" if retry else "Entrar"))
        if busy:
            self.message.clear()

    def show_failure(self, message, *, retry_license=False, retry_refresh=False, allow_new_login=False):
        self._cooldown.stop()     # a new outcome replaces any previous wait
        self._license_retry = retry_license
        self._refresh_retry = retry_refresh
        self.exit.setVisible(retry_license or retry_refresh)
        self.new_login.setVisible(allow_new_login)
        self.set_busy(False)
        self.message.setText(message)

    def reset_for_login(self, message=""):
        self.password.clear()
        self.show_failure(message)

    def show_locked(self, message=None):
        self.reset_for_login(message or "O DTF Manager já está aberto. Feche a outra janela para usar esta sessão.")
        self.enter.setEnabled(False)
        self.email.setEnabled(False)
        self.password.setEnabled(False)
        self.register.setEnabled(False)
        self.exit.show()

    def closeEvent(self, event):
        self.password.clear()
        self._cooldown.stop()
        self.closed.emit()
        super().closeEvent(event)
