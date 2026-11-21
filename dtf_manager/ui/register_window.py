from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from dtf_manager.core.constants import APP_NAME
from dtf_manager.ui.cooldown import Cooldown
from dtf_manager.utils.forms import (
    format_key_mask, format_phone_mask, normalize_phone, validate_email, validate_key,
    validate_name, validate_password)

TRIAL_TEXT = "Criar conta e iniciar teste"
KEY_TEXT = "Criar conta e ativar chave"


class RegisterWindow(QWidget):
    """Account creation. Starts the 7 day trial, or the plan of an activation key."""

    # name, phone (digits), e-mail, password, activation key ("" for the trial)
    submitted = Signal(str, str, str, str, str)
    subscribe_requested = Signal()
    back_requested = Signal()
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME + " - Criar conta")
        self.setObjectName("appRoot")
        self.setMinimumWidth(460)
        self._busy = False
        self._cooldown = Cooldown(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        title = QLabel("Criar conta")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        card = QFrame()
        card.setObjectName("sidebar")
        fields = QVBoxLayout(card)
        self.name = QLineEdit()
        self.name.setMaxLength(200)
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("(11) 91234-5678")
        self.phone.setMaxLength(20)
        self.email = QLineEdit()
        self.email.setMaxLength(254)
        self.email.setPlaceholderText("usuario@email.com")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        for label, widget in [("Nome", self.name), ("Telefone com DDD", self.phone),
                              ("E-mail", self.email), ("Senha", self.password),
                              ("Confirmar senha", self.confirm)]:
            caption = QLabel(label)
            caption.setObjectName("fieldLabel")
            fields.addWidget(caption)
            fields.addWidget(widget)
        self.has_key = QCheckBox("Já tenho uma chave de ativação")
        fields.addWidget(self.has_key)
        self.key_label = QLabel("Chave de ativação")
        self.key_label.setObjectName("fieldLabel")
        self.key = QLineEdit()
        self.key.setMaxLength(19)
        self.key.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        for widget in (self.key_label, self.key):
            fields.addWidget(widget)
        hint = QLabel("A senha precisa ter no mínimo 8 caracteres, com letras e números. "
                      "O telefone e este computador ficam vinculados ao teste.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        fields.addWidget(hint)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        fields.addWidget(self.message)
        self.create = QPushButton(TRIAL_TEXT)
        self.create.setObjectName("primaryButton")
        fields.addWidget(self.create)
        self.subscribe = QPushButton("Assinar")
        self.subscribe.hide()
        fields.addWidget(self.subscribe)
        self.back = QPushButton("Já tenho conta")
        fields.addWidget(self.back)
        layout.addWidget(card)
        self.phone.textEdited.connect(self._mask_phone)
        self.key.textEdited.connect(self._mask_key)
        for field in (self.name, self.phone, self.email, self.password, self.confirm, self.key):
            field.returnPressed.connect(self._submit)
        self.has_key.toggled.connect(self._key_toggled)
        self.create.clicked.connect(self._submit)
        self.subscribe.clicked.connect(self.subscribe_requested)
        self.back.clicked.connect(self.back_requested)
        self._cooldown.ticked.connect(self._cooldown_ticked)
        self._cooldown.finished.connect(self._cooldown_finished)
        self._key_toggled(False)

    def _create_text(self):
        return KEY_TEXT if self.has_key.isChecked() else TRIAL_TEXT

    def _key_toggled(self, checked):
        for widget in (self.key_label, self.key):
            widget.setVisible(checked)
        self.intro.setText(
            "Crie sua conta com a sua chave de ativação. O plano da chave começa a valer agora, "
            "neste computador." if checked else
            "Crie sua conta para iniciar o teste gratuito de 7 dias neste computador.")
        if not self._busy and not self._cooldown.active:
            self.create.setText(self._create_text())

    def _mask_key(self, text):
        masked = format_key_mask(text)
        if masked != text:
            self.key.setText(masked)

    def _mask_phone(self, text):
        masked = format_phone_mask(text)
        if masked != text:
            self.phone.setText(masked)

    def _submit(self):
        if self._busy:
            return
        error = (validate_name(self.name.text()) or
                 (None if normalize_phone(self.phone.text())
                  else "Telefone inválido. Informe um telefone brasileiro com DDD.") or
                 validate_email(self.email.text()) or validate_password(self.password.text()) or
                 (None if self.password.text() == self.confirm.text()
                  else "As senhas não conferem."))
        if not error and self.has_key.isChecked():
            error = validate_key(self.key.text())
            if error:
                self.message.setText(error)
                self.key.setFocus()
                return
        if error:
            self.message.setText(error)
            return
        if self._cooldown.active:
            return
        self.set_busy(True)
        phone = normalize_phone(self.phone.text())
        password = self.password.text()
        key = format_key_mask(self.key.text()) if self.has_key.isChecked() else ""
        self.password.clear()
        self.confirm.clear()
        self.submitted.emit(self.name.text().strip(), phone, self.email.text().strip(),
                            password, key)

    def set_busy(self, busy, text="Criando conta..."):
        self._busy = busy
        for widget in (self.name, self.phone, self.email, self.password, self.confirm,
                       self.has_key, self.key, self.subscribe, self.back):
            widget.setEnabled(not busy)
        self.create.setEnabled(not busy and not self._cooldown.active)
        if busy:
            self.create.setText(text)
            self.message.clear()
        elif not self._cooldown.active:
            self.create.setText(self._create_text())

    def show_failure(self, message):
        self.set_busy(False)
        self.message.setText(message)

    def require_key(self, message):
        """The trial was already used here: ask for a key instead (or offer to subscribe)."""
        self.has_key.setChecked(True)
        self.subscribe.show()
        self.show_failure(message)
        self.key.setFocus()

    def hold(self, seconds):
        """Keep the create button disabled during the server Retry-After."""
        self._cooldown.start(seconds)
        self.create.setEnabled(False)

    def _cooldown_ticked(self, left):
        self.create.setText(f"Aguarde {left} s")

    def _cooldown_finished(self):
        self.create.setEnabled(not self._busy)
        self.create.setText(self._create_text())

    def reset(self):
        self.password.clear()
        self.confirm.clear()
        self.key.clear()
        self.has_key.setChecked(False)
        self.subscribe.hide()
        self.show_failure("")

    def closeEvent(self, event):
        self.password.clear()
        self.confirm.clear()
        self._cooldown.stop()
        self.closed.emit()
        super().closeEvent(event)
