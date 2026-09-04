from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from dtf_manager.ui.widgets.dimension_spinbox import DimensionSpinBox, EditableSpinBox


class ArtworkCard(QFrame):
    dimensions_changed = Signal(float, float)
    quantity_changed = Signal(int)
    remove_requested = Signal(object)
    selection_requested = Signal(object)

    def __init__(self, name: str, sku: str, width_cm: float, height_cm: float, quantity: int, file_path: Path | None = None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setObjectName("artCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        thumb = QLabel("ART")
        thumb.setObjectName("artworkThumb")
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setFixedSize(44, 44)
        if file_path:
            pixmap = QPixmap(str(file_path))
            if not pixmap.isNull():
                thumb.setPixmap(pixmap.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(thumb)
        content = QVBoxLayout()
        name_label = QLabel(name)
        name_label.setObjectName("artworkName")
        name_label.setWordWrap(True)
        content.addWidget(name_label)
        sku_label = QLabel(f"SKU: {sku}")
        sku_label.setObjectName("muted")
        content.addWidget(sku_label)
        details = QGridLayout()
        details.setHorizontalSpacing(7)
        details.setVerticalSpacing(4)
        details.addWidget(QLabel("Largura"), 0, 0)
        details.addWidget(QLabel("Altura"), 0, 1)
        details.addWidget(QLabel("Quantidade"), 0, 2)
        self.width_input = self._dimension_input(width_cm)
        self.height_input = self._dimension_input(height_cm)
        details.addLayout(self._dimension_field(self.width_input), 1, 0)
        details.addLayout(self._dimension_field(self.height_input), 1, 1)
        self.quantity_input = EditableSpinBox()
        self.quantity_input.setRange(1, 9999)
        self.quantity_input.setValue(quantity)
        self.quantity_input.setFixedWidth(62)
        self.quantity_input.setButtonSymbols(EditableSpinBox.ButtonSymbols.UpDownArrows)
        details.addWidget(self.quantity_input, 1, 2)
        details.addWidget(QLabel("DPI: 300"), 2, 0)
        details.addWidget(QLabel("Rotacao: 0 graus"), 2, 1, 1, 2)
        for index in range(details.count()):
            widget = details.itemAt(index).widget()
            if isinstance(widget, QLabel):
                widget.setObjectName("muted")
        content.addLayout(details)
        keep_ratio = QCheckBox("Manter proporcao")
        keep_ratio.setChecked(True)
        content.addWidget(keep_ratio)
        layout.addLayout(content, 1)
        remove = QPushButton("x")
        remove.setObjectName("removeButton")
        remove.setToolTip("Excluir arte")
        remove.setFixedSize(32, 32)
        remove.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)

        self.width_input.valueChanged.connect(self._emit_dimensions)
        self.height_input.valueChanged.connect(self._emit_dimensions)
        self.quantity_input.valueChanged.connect(self.quantity_changed)

    @staticmethod
    def _dimension_field(field: DimensionSpinBox) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        row.addWidget(field)
        unit = QLabel("cm")
        unit.setObjectName("unitLabel")
        row.addWidget(unit)
        row.addStretch()
        return row

    @staticmethod
    def _dimension_input(value: float) -> DimensionSpinBox:
        input_field = DimensionSpinBox()
        input_field.setRange(0.1, 570.0)
        input_field.setDecimals(2)
        input_field.setValue(value)
        input_field.setFixedWidth(58)
        input_field.setButtonSymbols(DimensionSpinBox.ButtonSymbols.UpDownArrows)
        return input_field

    def _emit_dimensions(self) -> None:
        self.dimensions_changed.emit(self.width_input.value(), self.height_input.value())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.file_path:
            self.selection_requested.emit(self)
        super().mousePressEvent(event)
