from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from dtf_manager.ui.widgets.dimension_spinbox import DimensionSpinBox, EditableSpinBox


class ArtworkSetupDialog(QDialog):
    def __init__(self, file_path: Path, width_cm: float, height_cm: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar arte")
        self.setObjectName("artworkSetupDialog")
        self.setModal(True)
        self.setFixedSize(560, 350)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(16)

        heading = QLabel("CONFIGURAR ARTE")
        heading.setObjectName("eyebrow")
        layout.addWidget(heading)

        title = QLabel("Revise antes de adicionar ao rolo")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        content = QHBoxLayout()
        content.setSpacing(18)

        preview_card = QFrame()
        preview_card.setObjectName("previewCard")
        preview_card.setFixedWidth(185)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(12, 12, 12, 10)
        preview_layout.setSpacing(9)

        preview = QLabel()
        preview.setObjectName("artworkPreview")
        preview.setFixedSize(161, 148)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(file_path))
        if not pixmap.isNull():
            preview.setPixmap(
                pixmap.scaled(
                    141,
                    128,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        preview_layout.addWidget(preview)

        name = QLabel(file_path.name)
        name.setObjectName("dialogFileName")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setToolTip(str(file_path))
        preview_layout.addWidget(name)
        content.addWidget(preview_card)

        form_card = QFrame()
        form_card.setObjectName("setupFormCard")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(16, 14, 16, 14)
        form_layout.setSpacing(10)

        form_title = QLabel("Tamanho e quantidade")
        form_title.setObjectName("panelTitle")
        form_layout.addWidget(form_title)

        form_hint = QLabel("Informe o tamanho final da estampa.")
        form_hint.setObjectName("muted")
        form_layout.addWidget(form_hint)

        fields = QGridLayout()
        fields.setHorizontalSpacing(10)
        fields.setVerticalSpacing(6)
        self.width_input = self._dimension_input(width_cm)
        self.height_input = self._dimension_input(height_cm)
        self.quantity_input = EditableSpinBox()
        self.quantity_input.setRange(1, 9999)
        self.quantity_input.setValue(1)
        self.quantity_input.setFixedWidth(90)
        self.quantity_input.setButtonSymbols(EditableSpinBox.ButtonSymbols.UpDownArrows)
        fields.addWidget(self._field_label("Largura"), 0, 0)
        fields.addWidget(self._field_label("Altura"), 0, 1)
        fields.addLayout(self._dimension_field(self.width_input), 1, 0)
        fields.addLayout(self._dimension_field(self.height_input), 1, 1)
        fields.addWidget(self._field_label("Quantidade"), 2, 0, 1, 2)
        fields.addWidget(self.quantity_input, 3, 0, 1, 2)
        form_layout.addLayout(fields)
        form_layout.addStretch()
        content.addWidget(form_card, 1)
        layout.addLayout(content, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        confirm_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        confirm_button.setText("Adicionar ao rolo")
        confirm_button.setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    @staticmethod
    def _dimension_field(field: DimensionSpinBox) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(field)
        unit = QLabel("cm")
        unit.setObjectName("unitLabel")
        row.addWidget(unit)
        row.addStretch()
        return row

    @staticmethod
    def _dimension_input(value: float) -> DimensionSpinBox:
        field = DimensionSpinBox()
        field.setRange(0.1, 570.0)
        field.setDecimals(2)
        field.setValue(value)
        field.setFixedWidth(90)
        field.setButtonSymbols(DimensionSpinBox.ButtonSymbols.UpDownArrows)
        return field

    @property
    def dimensions(self) -> tuple[float, float, int]:
        return self.width_input.value(), self.height_input.value(), self.quantity_input.value()
