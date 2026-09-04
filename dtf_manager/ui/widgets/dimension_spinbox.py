from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox


class _SelectAllOnClickMixin:
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lineEdit().installEventFilter(self)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            QTimer.singleShot(0, self.selectAll)

    def mouseDoubleClickEvent(self, event) -> None:
        self.setFocus()
        editor = self.lineEdit()
        editor_position = editor.mapFrom(self, event.position().toPoint())
        editor.deselect()
        editor.setCursorPosition(editor.cursorPositionAt(editor_position))
        event.accept()

    def eventFilter(self, watched, event) -> bool:
        editor = self.lineEdit()
        if watched is editor and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                QTimer.singleShot(0, self.selectAll)
        elif watched is editor and event.type() == QEvent.Type.MouseButtonDblClick:
            editor.deselect()
            editor.setCursorPosition(editor.cursorPositionAt(event.position().toPoint()))
            return True
        return super().eventFilter(watched, event)


class EditableSpinBox(_SelectAllOnClickMixin, QSpinBox):
    """Integer input with one-click replacement and double-click editing."""


class EditableDoubleSpinBox(_SelectAllOnClickMixin, QDoubleSpinBox):
    """Decimal input with one-click replacement and double-click editing."""


class DimensionSpinBox(EditableDoubleSpinBox):
    """Dimension input that hides unnecessary trailing decimal zeroes."""

    def textFromValue(self, value: float) -> str:
        text = self.locale().toString(value, "f", self.decimals())
        decimal_separator = self.locale().decimalPoint()
        return text.rstrip("0").rstrip(decimal_separator)
