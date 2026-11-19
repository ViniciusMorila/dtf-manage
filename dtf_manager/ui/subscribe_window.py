from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dtf_manager.core.constants import APP_NAME

GUIDANCE = ("Finalize o pagamento pelo WhatsApp. "
            "Quando receber a chave, clique em 'Tenho uma chave'.")


class SubscribeWindow(QWidget):
    """Plan choice. It only emits signals: it never calls the API or opens links."""

    plan_chosen = Signal(str)        # plan code
    copy_requested = Signal()
    have_key_requested = Signal()
    back_requested = Signal()
    closed = Signal()

    def __init__(self, plans):
        super().__init__()
        self.setWindowTitle(APP_NAME + " - Assinar")
        self.setObjectName("appRoot")
        self.setMinimumWidth(560)
        self._busy = False
        self.choose_buttons = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        title = QLabel("Assinar o DTF Manager")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.reason = QLabel()
        self.reason.setWordWrap(True)
        self.reason.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.reason)
        self.example_note = QLabel("VALORES DE EXEMPLO: configure os preços reais em planos.json.")
        self.example_note.setObjectName("fieldLabel")
        self.example_note.setVisible(any(p.example for p in plans))
        layout.addWidget(self.example_note)
        for plan in plans:
            layout.addWidget(self._card(plan))
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.hide()
        layout.addWidget(self.notice)
        self.guidance = QLabel(GUIDANCE)
        self.guidance.setObjectName("panelTitle")
        self.guidance.setWordWrap(True)
        self.guidance.hide()
        layout.addWidget(self.guidance)
        actions = QHBoxLayout()
        self.copy = QPushButton("Copiar mensagem")
        self.copy.hide()
        self.have_key = QPushButton("Tenho uma chave")
        self.back = QPushButton("Voltar")
        actions.addWidget(self.copy)
        actions.addStretch(1)
        actions.addWidget(self.have_key)
        actions.addWidget(self.back)
        layout.addLayout(actions)
        self.copy.clicked.connect(self.copy_requested)
        self.have_key.clicked.connect(self.have_key_requested)
        self.back.clicked.connect(self.back_requested)

    def _card(self, plan):
        card = QFrame()
        card.setObjectName("widthCard" if plan.highlight else "previewCard")
        row = QHBoxLayout(card)
        text = QVBoxLayout()
        if plan.highlight:
            badge = QLabel(plan.highlight.upper())
            badge.setObjectName("eyebrow")
            text.addWidget(badge)
        name = QLabel(plan.name)
        name.setObjectName("panelTitle")
        duration = QLabel(plan.duration)
        duration.setObjectName("muted")
        text.addWidget(name)
        text.addWidget(duration)
        row.addLayout(text, 1)
        price = QLabel(plan.price + (" (EXEMPLO)" if plan.example else ""))
        price.setObjectName("metricValue")
        row.addWidget(price)
        button = QPushButton("Escolher")
        if plan.highlight:
            button.setObjectName("primaryButton")
        button.clicked.connect(lambda _=False, code=plan.code: self._choose(code))
        row.addWidget(button)
        self.choose_buttons[plan.code] = button
        return card

    def _choose(self, code):
        if not self._busy:
            self.plan_chosen.emit(code)

    def set_reason(self, text):
        self.reason.setText(text)
        self.reason.setVisible(bool(text))

    def set_busy(self, busy):
        self._busy = busy
        for button in (*self.choose_buttons.values(), self.copy, self.have_key, self.back):
            button.setEnabled(not busy)

    def show_notice(self, text):
        self.set_busy(False)
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def show_guidance(self):
        """After the WhatsApp link was opened (or could not be)."""
        self.set_busy(False)
        self.guidance.show()
        self.copy.show()

    def reset(self):
        self.set_busy(False)
        self.notice.hide()
        self.guidance.hide()
        self.copy.hide()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
