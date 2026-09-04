from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from dtf_manager.models.link_memory import ArtLinkMemory
from dtf_manager.services.link_memory_repository import (
    LinkMemoryStorageError, ProductLinkMemoryRepository,
)


class LinkMemoryPage(QWidget):
    back_requested = Signal()

    def __init__(self, repository: ProductLinkMemoryRepository, parent=None):
        super().__init__(parent)
        self.setObjectName("linkMemoryPage")
        self._repository = repository
        self._visible_memories: tuple[ArtLinkMemory, ...] = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        header = QHBoxLayout()
        back = QPushButton("← VOLTAR")
        back.clicked.connect(self.back_requested)
        header.addWidget(back)
        title = QLabel("MEMÓRIA DE VÍNCULOS")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        clear = QPushButton("LIMPAR MEMÓRIA DE VÍNCULOS")
        clear.setObjectName("removeButton")
        clear.clicked.connect(self._clear_all)
        header.addWidget(clear)
        layout.addLayout(header)
        subtitle = QLabel("Associações confirmadas localmente para futuras importações.")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar SKU, produto ou arte...")
        self.search.setAccessibleName("Buscar memória de vínculos")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.table = QTableWidget()
        self.table.setObjectName("linkMemoryTable")
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ("PRODUTO", "SKU", "VARIAÇÃO", "ARTES", "ORIGEM", "")
        )
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.empty = QLabel("Nenhuma memória de vínculo registrada.")
        self.empty.setObjectName("emptyState")
        layout.addWidget(self.empty)
        self.refresh()

    def refresh(self) -> None:
        query = self.search.text().casefold().strip()
        memories = self._repository.list_all()
        self._visible_memories = tuple(
            memory for memory in memories
            if not query or query in " ".join((
                memory.product_name,
                memory.identity.sku,
                memory.identity.variation_raw,
                *(art.file_name for art in memory.arts),
            )).casefold()
        )
        self.table.setRowCount(0)
        for row, memory in enumerate(self._visible_memories):
            self.table.insertRow(row)
            arts = ", ".join(
                f"{art.file_name} ×{art.copies_per_product}" for art in memory.arts
            )
            values = (
                memory.product_name or memory.identity.listing_id,
                memory.identity.sku,
                memory.identity.variation_raw,
                arts,
                "Manual" if memory.source == "manual" else "Automático confirmado",
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(row, column, cell)
            delete = QPushButton("EXCLUIR")
            delete.setObjectName("removeButton")
            delete.clicked.connect(lambda _checked=False, memory_id=memory.id: self._delete(memory_id))
            self.table.setCellWidget(row, 5, delete)
        self.table.setVisible(bool(self._visible_memories))
        self.empty.setVisible(not self._visible_memories)

    def _delete(self, memory_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "Excluir memória",
            "Deseja excluir esta associação? Os arquivos das artes não serão alterados.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._repository.delete(memory_id)
        except LinkMemoryStorageError as error:
            QMessageBox.warning(self, "Memória de vínculos", str(error))
        self.refresh()

    def _clear_all(self) -> None:
        if not self._repository.list_all():
            return
        answer = QMessageBox.warning(
            self,
            "Limpar memória de vínculos",
            "Isso removerá todos os vínculos aprendidos pelo sistema. Os arquivos das artes não serão excluídos.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._repository.clear()
        except LinkMemoryStorageError as error:
            QMessageBox.warning(self, "Memória de vínculos", str(error))
        self.refresh()
