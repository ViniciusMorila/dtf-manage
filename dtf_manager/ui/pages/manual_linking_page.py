from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEvent, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from dtf_manager.models.imported_order import ImportedOrderItem, LinkedArt
from dtf_manager.models.active_operation import ManualLinkingSessionSnapshot
from dtf_manager.services.manual_link_service import (
    ManualLinkQueue, ManualLinkValidationError, create_manual_linked_art,
)
from dtf_manager.state.order_import_state import OrderImportState
from dtf_manager.ui.widgets.manual_link_art_card import ManualLinkArtCard
from dtf_manager.ui.widgets.manual_link_art_card import transparent_preview
from dtf_manager.services.link_memory_service import ArtLinkMemoryService
from dtf_manager.services.link_memory_repository import LinkMemoryStorageError


class ManualLinkingPage(QWidget):
    back_requested = Signal()
    session_completed = Signal(int)
    checkpoint_requested = Signal()

    def __init__(self, state: OrderImportState, memory_service: ArtLinkMemoryService, parent=None):
        super().__init__(parent)
        self.setObjectName("manualLinkingPage")
        self._state = state
        self._memory_service = memory_service
        self._queue = ManualLinkQueue(())
        self._single_mode = False
        self._session_active = False
        self._draft: list[LinkedArt | None] = []
        self._saved_draft: list[LinkedArt] = []
        self._last_saved_arts: list[LinkedArt] = []
        self._linked_in_session: set[str] = set()
        self._skipped_item_ids: set[str] = set()
        self._image_reply: QNetworkReply | None = None
        self._artwork_folder: Path | None = None
        self._art_files: tuple[Path, ...] | None = None
        self._network = QNetworkAccessManager(self)
        self._build_ui()
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._save)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        header = QHBoxLayout()
        back = QPushButton("← VOLTAR")
        back.clicked.connect(self._back)
        header.addWidget(back)
        title = QLabel("VINCULAÇÃO MANUAL")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        self.position_label = QLabel("")
        self.position_label.setObjectName("panelTitle")
        header.addWidget(self.position_label)
        layout.addLayout(header)
        self.session_progress = QProgressBar()
        self.session_progress.setRange(0, 100)
        layout.addWidget(self.session_progress)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        product_card = QFrame()
        product_card.setObjectName("manualColumn")
        product_layout = QVBoxLayout(product_card)
        product_layout.addWidget(self._column_title("PRODUTO"))
        self.product_image = QLabel("Imagem do produto indisponível")
        self.product_image.setObjectName("manualProductImage")
        self.product_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.product_image.setMinimumSize(300, 360)
        product_layout.addWidget(self.product_image, 1)
        columns.addWidget(product_card, 3)

        info_card = QFrame()
        info_card.setObjectName("manualColumn")
        info_layout = QVBoxLayout(info_card)
        info_layout.addWidget(self._column_title("INFORMAÇÕES"))
        self.info_grid = QGridLayout()
        self.info_values: dict[str, QLabel] = {}
        for row, name in enumerate(("Nome do produto", "SKU", "Variação", "Quantidade do produto")):
            label = QLabel(name.upper())
            label.setObjectName("eyebrow")
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.info_grid.addWidget(label, row * 2, 0)
            self.info_grid.addWidget(value, row * 2 + 1, 0)
            self.info_values[name] = value
        info_layout.addLayout(self.info_grid)
        info_layout.addStretch()
        columns.addWidget(info_card, 3)

        arts_card = QFrame()
        arts_card.setObjectName("manualColumn")
        arts_layout = QVBoxLayout(arts_card)
        arts_layout.addWidget(self._column_title("ARTES"))
        suggestions_title = QLabel("SUGESTÕES")
        suggestions_title.setObjectName("eyebrow")
        arts_layout.addWidget(suggestions_title)
        self.art_search = QLineEdit()
        self.art_search.setPlaceholderText("Pesquisar pelo nome da imagem...")
        self.art_search.setClearButtonEnabled(True)
        self.art_search.installEventFilter(self)
        arts_layout.addWidget(self.art_search)
        self.copy_previous_button = QPushButton("COPIAR ESTAMPA ANTERIOR")
        self.copy_previous_button.setToolTip(
            "Copia todas as artes, tamanhos e quantidades do último produto salvo"
        )
        self.copy_previous_button.clicked.connect(self._copy_previous_arts)
        self.copy_previous_button.setEnabled(False)
        arts_layout.addWidget(self.copy_previous_button)
        self.suggestions_scroll = QScrollArea()
        self.suggestions_scroll.setWidgetResizable(True)
        self.suggestions_scroll.setMaximumHeight(250)
        self.suggestions_content = QWidget()
        self.suggestions_grid = QGridLayout(self.suggestions_content)
        self.suggestions_grid.setContentsMargins(0, 4, 4, 4)
        self.suggestions_grid.setSpacing(8)
        self.suggestions_scroll.setWidget(self.suggestions_content)
        self.suggestions_scroll.hide()
        arts_layout.addWidget(self.suggestions_scroll)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._refresh_suggestions)
        self.art_search.textChanged.connect(self._art_search_changed)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.arts_content = QWidget()
        self.arts_list = QVBoxLayout(self.arts_content)
        self.arts_list.setContentsMargins(0, 0, 4, 0)
        scroll.setWidget(self.arts_content)
        arts_layout.addWidget(scroll, 1)
        columns.addWidget(arts_card, 4)
        layout.addLayout(columns, 1)

        footer = QHBoxLayout()
        self.previous_button = QPushButton("ANTERIOR")
        self.previous_button.clicked.connect(self._previous)
        footer.addWidget(self.previous_button)
        footer.addStretch()
        self.skip_button = QPushButton("PULAR POR ENQUANTO")
        self.skip_button.clicked.connect(self._skip)
        footer.addWidget(self.skip_button)
        self.save_button = QPushButton("SALVAR E AVANÇAR")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)

    @staticmethod
    def _column_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("panelTitle")
        return label

    def start_queue(self, item_ids: tuple[str, ...], start_item_id: str | None = None) -> None:
        self._single_mode = False
        self._session_active = True
        self._queue = ManualLinkQueue(item_ids, start_item_id)
        self._linked_in_session.clear()
        self._skipped_item_ids.clear()
        self._last_saved_arts.clear()
        if self._seek_next_unlinked(include_current=True):
            self._load_current()
        else:
            self._session_active = False
            self.session_completed.emit(0)

    def can_resume_queue(self) -> bool:
        return (
            self._session_active
            and not self._single_mode
            and self._queue.current_item_id is not None
            and self._state.find_item(self._queue.current_item_id) is not None
        )

    def resume_queue(self) -> bool:
        if not self.can_resume_queue():
            return False
        if not self._seek_next_unlinked(include_current=True):
            self._session_active = False
            return False
        self._load_current()
        return True

    def _seek_next_unlinked(self, include_current: bool = False) -> bool:
        if not include_current and not self._queue.advance():
            return False
        while True:
            item = self._current_item()
            if item is not None and item.link_status == "unlinked":
                return True
            if not self._queue.advance():
                return False

    def set_artwork_folder(self, folder: Path | None) -> None:
        self._artwork_folder = Path(folder) if folder else None
        self._art_files = None
        if hasattr(self, "art_search"):
            self.art_search.clear()
            self._clear_suggestions()

    def session_snapshot(self) -> ManualLinkingSessionSnapshot | None:
        if not self._queue.item_ids:
            return None
        return ManualLinkingSessionSnapshot(
            queue_item_ids=tuple(self._queue.item_ids),
            current_item_id=self._queue.current_item_id,
            current_index=self._queue.index,
            skipped_item_ids=tuple(sorted(self._skipped_item_ids)),
            mode="single" if self._single_mode else "queue",
        )

    def restore_session(self, snapshot: ManualLinkingSessionSnapshot) -> bool:
        valid_ids = tuple(item_id for item_id in snapshot.queue_item_ids if self._state.find_item(item_id))
        if not valid_ids:
            return False
        self._single_mode = snapshot.mode == "single"
        self._session_active = not self._single_mode
        self._queue = ManualLinkQueue(valid_ids, snapshot.current_item_id)
        self._skipped_item_ids = set(snapshot.skipped_item_ids)
        if not self._single_mode and not self._seek_next_unlinked(include_current=True):
            return False
        self._load_current()
        return True

    def start_single(self, item_id: str) -> None:
        self._single_mode = True
        self._queue = ManualLinkQueue((item_id,))
        self._linked_in_session.clear()
        self._load_current()

    def _current_item(self) -> ImportedOrderItem | None:
        item_id = self._queue.current_item_id
        return self._state.find_item(item_id) if item_id else None

    def _load_current(self) -> None:
        item = self._current_item()
        if item is None:
            self.back_requested.emit()
            return
        self._saved_draft = list(item.linked_arts)
        self._draft = list(item.linked_arts) or [None]
        values = {
            "Nome do produto": item.product_name,
            "SKU": item.sku,
            "Variação": item.variation_raw,
            "Quantidade do produto": str(item.product_quantity),
        }
        for name, value in values.items():
            self.info_values[name].setText(value)
            self.info_values[name].setToolTip(value)
        total = len(self._queue.item_ids)
        position = self._queue.index + 1
        self.position_label.setText("" if self._single_mode else f"Produto {position} de {total}")
        self.session_progress.setVisible(not self._single_mode)
        self.session_progress.setValue(round(position / total * 100) if total else 0)
        self.previous_button.setVisible(not self._single_mode)
        self.previous_button.setEnabled(self._queue.index > 0)
        self.skip_button.setVisible(not self._single_mode)
        self.save_button.setText(
            "SALVAR ALTERAÇÕES" if self._single_mode else
            "SALVAR E CONCLUIR" if self._queue.is_last else "SALVAR E AVANÇAR"
        )
        self.copy_previous_button.setEnabled(bool(self._last_saved_arts))
        if not self._single_mode:
            self.skip_button.setText("PULAR E CONCLUIR" if self._queue.is_last else "PULAR POR ENQUANTO")
        self._rebuild_arts()
        self._load_product_image(item)

    def _load_product_image(self, item: ImportedOrderItem) -> None:
        if self._image_reply is not None and self._image_reply.isRunning():
            self._image_reply.abort()
        self.product_image.setPixmap(QPixmap())
        self.product_image.setText("Carregando imagem..." if item.product_image_url else "Imagem do produto indisponível")
        if not item.product_image_url:
            return
        request = QNetworkRequest(QUrl(item.product_image_url))
        request.setTransferTimeout(8000)
        reply = self._network.get(request)
        reply.setProperty("item_id", item.id)
        reply.finished.connect(lambda current=reply: self._product_image_finished(current))
        self._image_reply = reply

    def _product_image_finished(self, reply: QNetworkReply) -> None:
        # An aborted request also emits finished(). Only the exact latest reply
        # is allowed to update the preview for the current product.
        if reply is not self._image_reply or reply.property("item_id") != self._queue.current_item_id:
            reply.deleteLater()
            return
        pixmap = QPixmap()
        valid = reply.error() == QNetworkReply.NetworkError.NoError and pixmap.loadFromData(reply.readAll())
        if valid:
            self.product_image.setText("")
            self.product_image.setPixmap(pixmap.scaled(
                360, 460, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self.product_image.setPixmap(QPixmap())
            self.product_image.setText("Imagem do produto indisponível")
        self._image_reply = None
        reply.deleteLater()

    def _rebuild_arts(self) -> None:
        while self.arts_list.count():
            child = self.arts_list.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for index, art in enumerate(self._draft):
            card = ManualLinkArtCard(index, art)
            card.browse_requested.connect(self._browse)
            card.remove_requested.connect(self._remove_art)
            card.quantity_changed.connect(self._change_quantity)
            card.dimensions_changed.connect(self._change_dimensions)
            card.color_changed.connect(self._change_color)
            self.arts_list.addWidget(card)
        self.arts_list.addStretch()

    def _browse(self, index: int) -> None:
        initial = str(self._artwork_folder or Path.home())
        selected, _ = QFileDialog.getOpenFileName(
            self, "Selecionar arte", initial, "Imagens (*.png *.jpg *.jpeg *.webp)"
        )
        if not selected:
            return
        self._select_art_path(index, Path(selected))

    def _select_art_path(self, index: int, selected_path: Path) -> None:
        try:
            new_art = create_manual_linked_art(selected_path)
        except ManualLinkValidationError as error:
            QMessageBox.warning(self, "Selecionar arte", str(error))
            return
        self._state.last_art_folder = str(selected_path.parent)
        self._draft[index] = new_art
        self._rebuild_arts()

    def _ensure_art_index(self) -> None:
        if self._art_files is not None:
            return
        if not self._artwork_folder or not self._artwork_folder.is_dir():
            self._art_files = ()
            return
        supported = {".png", ".jpg", ".jpeg", ".webp"}
        try:
            self._art_files = tuple(sorted(
                (path for path in self._artwork_folder.rglob("*")
                 if path.is_file() and path.suffix.casefold() in supported),
                key=lambda path: path.name.casefold(),
            ))
        except (OSError, PermissionError):
            self._art_files = ()

    def _clear_suggestions(self) -> None:
        while self.suggestions_grid.count():
            child = self.suggestions_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.suggestions_scroll.hide()

    def _art_search_changed(self, text: str) -> None:
        if not text.strip():
            self._search_timer.stop()
            self._clear_suggestions()
        else:
            self._search_timer.start()

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and self.isVisible()
            and self.art_search.text()
            and isinstance(watched, QWidget)
            and not self._is_search_widget(watched)
        ):
            QTimer.singleShot(0, self._close_art_search)
        return super().eventFilter(watched, event)

    def _is_search_widget(self, widget: QWidget) -> bool:
        return (
            widget is self.art_search
            or self.art_search.isAncestorOf(widget)
            or widget is self.suggestions_content
            or self.suggestions_content.isAncestorOf(widget)
            or widget is self.suggestions_scroll
            or self.suggestions_scroll.isAncestorOf(widget)
        )

    def _close_art_search(self) -> None:
        self._search_timer.stop()
        self.art_search.clear()
        self._clear_suggestions()

    def _refresh_suggestions(self) -> None:
        self._clear_suggestions()
        query = self.art_search.text().strip().casefold()
        if not query:
            return
        self._ensure_art_index()
        matches = [path for path in self._art_files or () if query in path.stem.casefold()][:12]
        for position, path in enumerate(matches):
            button = QToolButton()
            button.setObjectName("artSuggestion")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIcon(QIcon(transparent_preview(str(path), 92, 76)))
            button.setIconSize(QSize(92, 76))
            button.setText(path.stem)
            button.setToolTip(str(path))
            button.setFixedSize(118, 116)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda checked=False, selected=path: self._add_suggested_art(selected))
            self.suggestions_grid.addWidget(button, position // 4, position % 4)
        if matches:
            self.suggestions_scroll.show()

    def _add_suggested_art(self, path: Path) -> None:
        index = next((position for position, art in enumerate(self._draft) if art is None), None)
        if index is None:
            self._draft.append(None)
            index = len(self._draft) - 1
        self._select_art_path(index, path)

    def _add_slot(self) -> None:
        self._draft.append(None)
        self._rebuild_arts()

    def _remove_art(self, index: int) -> None:
        self._draft.pop(index)
        if not self._draft:
            self._draft.append(None)
        self._rebuild_arts()

    def _change_quantity(self, index: int, quantity: int) -> None:
        art = self._draft[index]
        if art is not None:
            self._draft[index] = replace(art, copies_per_product=max(1, quantity))

    def _change_dimensions(self, index: int, width_cm: float, height_cm: float) -> None:
        art = self._draft[index]
        if art is not None:
            self._draft[index] = replace(art, width_cm=width_cm, height_cm=height_cm)

    def _change_color(self, index: int, color_mode: str) -> None:
        art = self._draft[index]
        if art is not None:
            self._draft[index] = replace(art, color_mode=color_mode)

    def _copy_previous_arts(self) -> None:
        if not self._last_saved_arts:
            return
        self._draft = [
            replace(art, id=str(uuid4()), link_method="manual")
            for art in self._last_saved_arts
        ]
        self._rebuild_arts()

    def _valid_draft(self) -> list[LinkedArt]:
        return [art for art in self._draft if art is not None]

    def has_unsaved_changes(self) -> bool:
        return self._valid_draft() != self._saved_draft or any(art is None for art in self._draft[1:])

    def confirm_can_leave(self) -> bool:
        if not self.has_unsaved_changes():
            return True
        answer = QMessageBox.question(
            self, "Alterações não salvas",
            "Existem alterações não salvas neste produto. Deseja descartá-las?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def _save(self) -> None:
        item = self._current_item()
        if item is None:
            return
        arts = self._valid_draft()
        if not arts and not self._single_mode and item.link_status == "unlinked":
            QMessageBox.information(
                self, "Vinculação manual",
                "Escolha pelo menos uma arte ou use PULAR POR ENQUANTO.",
            )
            return
        try:
            updated = self._state.update_item_links(item.id, arts)
        except ManualLinkValidationError as error:
            QMessageBox.warning(self, "Vinculação manual", str(error))
            return
        try:
            self._memory_service.remember_item(updated, self._state.last_art_folder)
        except LinkMemoryStorageError:
            QMessageBox.warning(
                self,
                "Memória de vínculos",
                "Vínculo salvo, mas não foi possível adicioná-lo à memória.",
            )
        if item.link_status == "unlinked" and updated.link_status == "linked":
            self._linked_in_session.add(item.id)
            self._skipped_item_ids.discard(item.id)
        elif updated.link_status == "unlinked":
            self._linked_in_session.discard(item.id)
        self._saved_draft = list(updated.linked_arts)
        self._last_saved_arts = list(updated.linked_arts)
        if self._single_mode:
            self.back_requested.emit()
        else:
            self._advance_or_finish()

    def _skip(self) -> None:
        if not self.confirm_can_leave():
            return
        if self._queue.current_item_id:
            self._skipped_item_ids.add(self._queue.current_item_id)
        self._advance_or_finish()

    def _advance_or_finish(self) -> None:
        if self._seek_next_unlinked():
            self._load_current()
            self.checkpoint_requested.emit()
        else:
            self._session_active = False
            self.checkpoint_requested.emit()
            self.session_completed.emit(len(self._linked_in_session))

    def _previous(self) -> None:
        if self.confirm_can_leave() and self._queue.previous():
            self._load_current()

    def _back(self) -> None:
        if self.confirm_can_leave():
            self.back_requested.emit()
