from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget
from PIL import Image

from dtf_manager.ui.widgets.artwork_card import ArtworkCard
from dtf_manager.ui.widgets.summary_widget import SummaryWidget


class ArtworkPanel(QFrame):
    artwork_added = Signal(str, float, float, int)
    artwork_dimensions_changed = Signal(str, float, float)
    artwork_quantity_changed = Signal(str, int)
    artwork_removed = Signal(str)
    artwork_selection_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rightPanel")
        self._film_width_mm = 570.0
        self._cost_per_meter = 19.90
        self._used_meters = 0.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QLabel("ARTES")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.subtitle = QLabel("0 artes vinculadas ao projeto")
        self.subtitle.setObjectName("muted")
        layout.addWidget(self.subtitle)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.cards = QVBoxLayout(content)
        self.cards.setContentsMargins(0, 2, 4, 2)
        self.cards.setSpacing(8)
        self._artwork_cards: list[ArtworkCard] = []
        self.cards.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.summary = SummaryWidget()
        layout.addWidget(self.summary)
        self._update_summary()

    def set_roll_settings(self, film_width_mm: float, cost_per_meter: float) -> None:
        self._film_width_mm = film_width_mm
        self._cost_per_meter = cost_per_meter
        self._update_summary()

    def add_artwork(self, file_path: Path) -> None:
        """Adds a selected file to the visual list for this project."""
        roll_key = str(file_path)
        existing_card = self._find_card(roll_key)
        if existing_card is not None:
            existing_card.quantity_input.setValue(existing_card.quantity_input.value() + 1)
            return
        self.cards.takeAt(self.cards.count() - 1)
        width_cm, height_cm = self.physical_size_cm(file_path)
        card = ArtworkCard(file_path.name, "SEM SKU", width_cm, height_cm, 1, file_path)
        card.setProperty("rollKey", roll_key)
        card.dimensions_changed.connect(
            lambda width, height: self._dimensions_changed(roll_key, width, height)
        )
        card.quantity_changed.connect(
            lambda quantity: self._quantity_changed(roll_key, quantity)
        )
        card.remove_requested.connect(self._remove_card)
        card.selection_requested.connect(self._select_card)
        self.cards.addWidget(card)
        self._artwork_cards.append(card)
        self.cards.addStretch()
        self.artwork_added.emit(
            roll_key, card.width_input.value(), card.height_input.value(), card.quantity_input.value()
        )
        self._update_summary()

    def add_configured_artwork(
        self, file_path: Path, width_cm: float, height_cm: float, quantity: int,
        color_mode: str = "original",
    ) -> str:
        roll_key = self._sized_roll_key(file_path, width_cm, height_cm, color_mode)
        existing_card = self._find_card(roll_key)
        if existing_card is not None:
            existing_card.width_input.setValue(width_cm)
            existing_card.height_input.setValue(height_cm)
            existing_card.quantity_input.setValue(existing_card.quantity_input.value() + quantity)
            return roll_key
        self.cards.takeAt(self.cards.count() - 1)
        card = ArtworkCard(file_path.name, "SEM SKU", width_cm, height_cm, quantity, file_path)
        card.setProperty("rollKey", roll_key)
        card.dimensions_changed.connect(
            lambda width, height: self._dimensions_changed(roll_key, width, height)
        )
        card.quantity_changed.connect(
            lambda quantity: self._quantity_changed(roll_key, quantity)
        )
        card.remove_requested.connect(self._remove_card)
        card.selection_requested.connect(self._select_card)
        self.cards.addWidget(card)
        self._artwork_cards.append(card)
        self.cards.addStretch()
        self.artwork_added.emit(roll_key, width_cm, height_cm, quantity)
        self._update_summary()
        return roll_key

    def _remove_card(self, card: ArtworkCard) -> None:
        self.cards.removeWidget(card)
        self._artwork_cards.remove(card)
        card.deleteLater()
        if card.file_path:
            self.artwork_removed.emit(str(card.property("rollKey")))
        self._update_summary()

    def _dimensions_changed(self, roll_key: str, width: float, height: float) -> None:
        self.artwork_dimensions_changed.emit(roll_key, width, height)
        self._update_summary()

    def set_used_meters(self, used_meters: float) -> None:
        self._used_meters = max(0.0, used_meters)
        self._update_summary()

    def _quantity_changed(self, roll_key: str, quantity: int) -> None:
        self.artwork_quantity_changed.emit(roll_key, quantity)
        self._update_summary()

    def _find_card(self, roll_key: str) -> ArtworkCard | None:
        return next(
            (card for card in self._artwork_cards if card.property("rollKey") == roll_key),
            None,
        )

    @staticmethod
    def _sized_roll_key(
        file_path: Path, width_cm: float, height_cm: float, color_mode: str = "original"
    ) -> str:
        return (
            f"{file_path}|dtf-size={width_cm:.4f}x{height_cm:.4f}"
            f"|dtf-color={color_mode}"
        )

    def _select_card(self, selected_card: ArtworkCard) -> None:
        for card in self._artwork_cards:
            card.setProperty("selected", card is selected_card)
            card.style().unpolish(card)
            card.style().polish(card)
        if selected_card.file_path:
            self.artwork_selection_requested.emit(str(selected_card.property("rollKey")))

    def set_quantity_from_roll(self, file_path: Path, quantity: int) -> None:
        card = self._find_card(str(file_path))
        if card is None:
            return
        if quantity <= 0:
            self.cards.removeWidget(card)
            self._artwork_cards.remove(card)
            card.deleteLater()
        else:
            card.quantity_input.blockSignals(True)
            card.quantity_input.setValue(quantity)
            card.quantity_input.blockSignals(False)
        self._update_summary()

    def clear_artworks(self) -> None:
        for card in self._artwork_cards:
            self.cards.removeWidget(card)
            card.deleteLater()
        self._artwork_cards.clear()
        self._update_summary()

    def artwork_entries(self) -> tuple[tuple[Path, float, float, int], ...]:
        return tuple(
            (
                card.file_path,
                card.width_input.value(),
                card.height_input.value(),
                card.quantity_input.value(),
            )
            for card in self._artwork_cards
            if card.file_path is not None
        )

    def _update_summary(self) -> None:
        total_copies = sum(card.quantity_input.value() for card in self._artwork_cards)
        self.summary.update_values(
            len(self._artwork_cards), total_copies, self._used_meters, self._cost_per_meter
        )
        self.subtitle.setText(f"{len(self._artwork_cards)} artes vinculadas ao projeto")

    @staticmethod
    def physical_size_cm(file_path: Path) -> tuple[float, float]:
        with Image.open(file_path) as image:
            dpi_x, dpi_y = image.info.get("dpi", (300, 300))
            dpi_x = dpi_x or 300
            dpi_y = dpi_y or 300
            return image.width / dpi_x * 2.54, image.height / dpi_y * 2.54

    _physical_size_cm = physical_size_cm
