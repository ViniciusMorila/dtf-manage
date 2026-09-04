from PySide6.QtCore import QEvent, QTimer, Signal, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from dtf_manager.models.imported_order import LinkedArt
from dtf_manager.ui.widgets.dimension_spinbox import DimensionSpinBox, EditableSpinBox


def _recolor(source: QPixmap, color_mode: str) -> QPixmap:
    if color_mode == "original" or source.isNull():
        return source
    result = source.copy()
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(result.rect(), QColor("#000000" if color_mode == "black" else "#ffffff"))
    painter.end()
    return result


def transparent_preview(path: str, width: int = 180, height: int = 130, color_mode: str = "original") -> QPixmap:
    background = QPixmap(width, height)
    painter = QPainter(background)
    square = 12
    for y in range(0, height, square):
        for x in range(0, width, square):
            painter.fillRect(x, y, square, square, QColor("#2a2627" if (x // square + y // square) % 2 else "#171415"))
    source = _recolor(QPixmap(path), color_mode)
    if not source.isNull():
        scaled = source.scaled(width - 10, height - 10, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap((width - scaled.width()) // 2, (height - scaled.height()) // 2, scaled)
    painter.end()
    return background


class ManualLinkArtCard(QFrame):
    browse_requested = Signal(int)
    remove_requested = Signal(int)
    quantity_changed = Signal(int, int)
    dimensions_changed = Signal(int, float, float)
    color_changed = Signal(int, str)

    def __init__(self, index: int, art: LinkedArt | None, parent=None):
        super().__init__(parent)
        self.setObjectName("manualArtCard")
        self._index = index
        self._updating = False
        self._art = art
        self._ratio = (art.width_cm / art.height_cm) if art and art.width_cm and art.height_cm else 1.0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        preview = QLabel("Nenhum arquivo escolhido")
        preview.setObjectName("manualArtPreview")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFixedSize(180, 130)
        self.preview = preview
        if art and art.file_reference:
            preview.setPixmap(transparent_preview(art.file_reference, color_mode=art.color_mode))
            self.color_button = QPushButton("◐", preview)
            self.color_button.setObjectName("previewColorButton")
            self.color_button.setFixedSize(34, 34)
            self.color_button.move(preview.width() - 42, 8)
            self.color_button.setToolTip("Alternar arte entre preto e branco")
            self.color_button.clicked.connect(self._toggle_color)
            self.color_button.hide()
            preview.installEventFilter(self)
            self.color_button.installEventFilter(self)
        preview_column = QVBoxLayout()
        preview_column.setSpacing(8)
        preview_column.addWidget(preview, 0, Qt.AlignmentFlag.AlignHCenter)
        browse = QPushButton("PROCURAR")
        browse.setFixedWidth(120)
        browse.clicked.connect(lambda: self.browse_requested.emit(index))
        preview_column.addWidget(browse, 0, Qt.AlignmentFlag.AlignHCenter)
        preview_column.addStretch()
        layout.addLayout(preview_column)
        details = QVBoxLayout()

        if art:
            name = QLabel(art.file_name)
            name.setObjectName("artworkName")
            name.setToolTip(art.file_name)
            name.setWordWrap(True)
            details.addWidget(name)
            fields = QGridLayout()
            self.width = self._dimension_input(art.width_cm or 1.0)
            self.height = self._dimension_input(art.height_cm or 1.0)
            self.quantity = EditableSpinBox()
            self.quantity.setRange(1, 999)
            self.quantity.setSingleStep(1)
            self.quantity.setValue(art.copies_per_product)
            fields.addWidget(QLabel("Largura"), 0, 0)
            fields.addWidget(QLabel("Altura"), 0, 1)
            fields.addWidget(QLabel("Quantidade"), 0, 2)
            fields.addWidget(self.width, 1, 0)
            fields.addWidget(self.height, 1, 1)
            fields.addWidget(self.quantity, 1, 2)
            details.addLayout(fields)
            self.proportional = QCheckBox("Manter proporção")
            self.proportional.setChecked(True)
            details.addWidget(self.proportional)
            self.width.valueChanged.connect(self._width_changed)
            self.height.valueChanged.connect(self._height_changed)
            self.quantity.valueChanged.connect(lambda value: self.quantity_changed.emit(index, value))

        if art:
            actions = QHBoxLayout()
            actions.addStretch()
            remove = QPushButton("REMOVER")
            remove.setObjectName("removeButton")
            remove.clicked.connect(lambda: self.remove_requested.emit(index))
            actions.addWidget(remove)
            details.addLayout(actions)
        details.addStretch()
        if art:
            layout.addLayout(details, 1)
        else:
            layout.addStretch()

    def eventFilter(self, watched, event) -> bool:
        if hasattr(self, "color_button"):
            if event.type() == QEvent.Type.Enter:
                self.color_button.show()
                self.color_button.raise_()
            elif event.type() == QEvent.Type.Leave:
                QTimer.singleShot(0, self._hide_color_button_if_outside)
        return super().eventFilter(watched, event)

    def _hide_color_button_if_outside(self) -> None:
        if not self.preview.underMouse() and not self.color_button.underMouse():
            self.color_button.hide()

    def _toggle_color(self) -> None:
        if self._art is None or not self._art.file_reference:
            return
        current = self._art.color_mode
        if current == "black":
            target = "white"
        elif current == "white":
            target = "black"
        else:
            sample = QPixmap(self._art.file_reference).toImage().scaled(32, 32)
            luminance = []
            for y in range(sample.height()):
                for x in range(sample.width()):
                    color = sample.pixelColor(x, y)
                    if color.alpha() >= 32:
                        luminance.append(color.red() * 0.2126 + color.green() * 0.7152 + color.blue() * 0.0722)
            target = "black" if (sum(luminance) / len(luminance) if luminance else 255) >= 128 else "white"
        self._art = LinkedArt(
            self._art.id, self._art.file_name, self._art.file_reference,
            self._art.copies_per_product, self._art.link_method,
            self._art.width_cm, self._art.height_cm, target,
        )
        self.preview.setPixmap(transparent_preview(self._art.file_reference, color_mode=target))
        self.color_changed.emit(self._index, target)

    @staticmethod
    def _dimension_input(value: float) -> DimensionSpinBox:
        field = DimensionSpinBox()
        field.setRange(0.1, 2000)
        field.setDecimals(2)
        field.setSingleStep(0.1)
        field.setSuffix(" cm")
        field.setValue(value)
        return field

    def _width_changed(self, value: float) -> None:
        if self._updating:
            return
        if self.proportional.isChecked() and self._ratio:
            self._updating = True
            self.height.setValue(value / self._ratio)
            self._updating = False
        self.dimensions_changed.emit(self._index, self.width.value(), self.height.value())

    def _height_changed(self, value: float) -> None:
        if self._updating:
            return
        if self.proportional.isChecked():
            self._updating = True
            self.width.setValue(value * self._ratio)
            self._updating = False
        self.dimensions_changed.emit(self._index, self.width.value(), self.height.value())
