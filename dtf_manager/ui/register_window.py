from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from dtf_manager.core.constants import APP_NAME
from dtf_manager.utils.forms import (
    format_phone_mask, normalize_phone, validate_email, validate_name, validate_password)


class RegisterWindow(QWidget):
    """Account creation. Starts the 7 day trial on this computer."""

    submitted = Signal(str, str, str, str)   # name, phone (digits), e-mail, password
    back_requested = Signal()
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME + " - Criar conta")
        self.setObjectName("appRoot")
        self.setMinimumWidth(460)
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        title = QLabel("Criar conta")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        intro = QLabel("Crie sua conta para iniciar o teste gratuito de 7 dias neste computador.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
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
        hint = QLabel("A senha precisa ter no mínimo 8 caracteres, com letras e números. "
                      "O telefone e este computador ficam vinculados ao teste.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        fields.addWidget(hint)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        fields.addWidget(self.message)
        self.create = QPushButton("Criar conta e iniciar teste")
        self.create.setObjectName("primaryButton")
        fields.addWidget(self.create)
        self.back = QPushButton("Já tenho conta")
        fields.addWidget(self.back)
        layout.addWidget(card)
        self.phone.textEdited.connect(self._mask_phone)
        for field in (self.name, self.phone, self.email, self.password, self.confirm):
            field.returnPressed.connect(self._submit)
        self.create.clicked.connect(self._submit)
        self.back.clicked.connect(self.back_requested)

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
        if error:
            self.message.setText(error)
            return
        self.set_busy(True)
        phone = normalize_phone(self.phone.text())
        password = self.password.text()
        self.password.clear()
        self.confirm.clear()
        self.submitted.emit(self.name.text().strip(), phone, self.email.text().strip(), password)

    def set_busy(self, busy, text="Criando conta..."):
        self._busy = busy
        for widget in (self.name, self.phone, self.email, self.password, self.confirm,
                       self.create, self.back):
            widget.setEnabled(not busy)
        self.create.setText(text if busy else "Criar conta e iniciar teste")
        if busy:
            self.message.clear()

    def show_failure(self, message):
        self.set_busy(False)
        self.message.setText(message)

    def reset(self):
        self.password.clear()
        self.confirm.clear()
        self.show_failure("")

    def closeEvent(self, event):
        self.password.clear()
        self.confirm.clear()
        self.closed.emit()
        super().closeEvent(event)
