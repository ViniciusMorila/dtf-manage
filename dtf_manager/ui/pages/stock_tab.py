"""Aba "Estoque de camisetas": stock / futuro / saldo on the left, "Separação" on the right.

Only shows data and emits signals; the StockController decides everything."""
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from dtf_manager.utils.stock_names import normalize_name

NEGATIVE = QColor("#ff5a75")
WARNING = QColor("#e69b45")
HEADER_ROWS = 1                 # one header row: COR | TAM. | ESTOQUE | FUTURO | SALDO
COLUMNS = ("COR", "TAM.", "ESTOQUE", "FUTURO", "SALDO")
HEADER_BG = QColor("#100b0d")
HEADER_FG = QColor("#c9bcc0")

# shirt color name -> (background, text). Unknown colors get a neutral box.
SHIRT_COLORS = {
    "preta": ("#16161b", "#f1eaec"), "preto": ("#16161b", "#f1eaec"),
    "marrom": ("#6f4a2f", "#fbf3ee"),
    "bege": ("#dcc7a1", "#2a2118"),
    "branca": ("#f4f1ec", "#1b1b1b"), "branco": ("#f4f1ec", "#1b1b1b"),
    "azul": ("#2a56b8", "#ffffff"), "vermelha": ("#b3202e", "#ffffff"),
    "vermelho": ("#b3202e", "#ffffff"), "verde": ("#2e7d4f", "#ffffff"),
    "cinza": ("#8a8d93", "#101010"), "amarela": ("#e8c53a", "#201a05"),
    "amarelo": ("#e8c53a", "#201a05"), "rosa": ("#e58fb0", "#2a0f19"),
    "laranja": ("#e07b24", "#1f0f02"), "roxa": ("#6b3fa0", "#ffffff"),
    "roxo": ("#6b3fa0", "#ffffff"), "off white": ("#ece6d6", "#1b1b1b"),
}


def shirt_colors(name: str) -> tuple[QColor, QColor]:
    background, text = SHIRT_COLORS.get(normalize_name(name), ("#2a2a30", "#eeeeee"))
    return QColor(background), QColor(text)


def _table(name: str, rows: int = 0, columns: int = 0) -> QTableWidget:
    table = QTableWidget(rows, columns)
    table.setObjectName(name)
    table.setAlternatingRowColors(True)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    return table


class StockTab(QWidget):
    new_color_requested = Signal()
    new_size_requested = Signal()
    bulk_requested = Signal()
    aliases_requested = Signal()
    history_requested = Signal()
    copy_missing_requested = Signal()
    stock_edit_requested = Signal(int, int, str)     # color id, size id, typed text
    separated_changed = Signal(int, int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stockTab")
        self._rendering = False
        self._color_ids: list[int] = []
        self._size_ids: list[int] = []
        self._separation_keys: list[tuple[int, int]] = []
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(18)
        root.addLayout(self._build_left(), 3)
        root.addLayout(self._build_right(), 2)

    # ---- layout ------------------------------------------------------------------
    def _build_left(self) -> QVBoxLayout:
        left = QVBoxLayout()
        left.setSpacing(10)
        title = QLabel("ESTOQUE DE CAMISETAS")
        title.setObjectName("sectionTitle")
        left.addWidget(title)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for attribute, text, signal in (
            ("new_color_button", "Nova cor", self.new_color_requested),
            ("new_size_button", "Novo tamanho", self.new_size_requested),
            ("bulk_button", "Adicionar estoque em massa", self.bulk_requested),
            ("aliases_button", "Equivalências", self.aliases_requested),
            ("history_button", "Histórico", self.history_requested),
        ):
            button = QPushButton(text)
            button.clicked.connect(signal)
            setattr(self, attribute, button)
            buttons.addWidget(button)
        buttons.addStretch()
        left.addLayout(buttons)
        self.note_label = QLabel()
        self.note_label.setObjectName("muted")
        self.note_label.setWordWrap(True)
        left.addWidget(self.note_label)
        self.stock_table = _table("stockTable")
        self.matrix = self.stock_table
        self.matrix.horizontalHeader().hide()
        self.matrix.verticalHeader().hide()
        self.matrix.setAlternatingRowColors(False)
        self.matrix.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.matrix.itemChanged.connect(self._stock_item_changed)
        left.addWidget(self.matrix, 1)
        self.hint_label = QLabel(
            "Estoque: dê dois cliques na célula para editar. Futuro: o que os pedidos importados "
            "vão consumir. Saldo = Estoque − Futuro (vermelho quando negativo). "
            "Cada nova importação substitui o futuro atual.")
        self.hint_label.setObjectName("muted")
        self.hint_label.setWordWrap(True)
        left.addWidget(self.hint_label)
        return left

    def _build_right(self) -> QVBoxLayout:
        right = QVBoxLayout()
        right.setSpacing(10)
        title = QLabel("SEPARAÇÃO")
        title.setObjectName("sectionTitle")
        right.addWidget(title)
        self.separation_table = _table("separationTable", 0, 6)
        self.separation_table.setHorizontalHeaderLabels(
            ("COR", "TAM.", "PRECISA", "EM ESTOQUE", "FALTAM", "SEPARADO"))
        self.separation_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.separation_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.separation_table.verticalHeader().hide()
        self.separation_table.itemChanged.connect(self._separated_item_changed)
        right.addWidget(self.separation_table, 1)
        self.empty_label = QLabel("Importe uma planilha na aba DTF para ver o que separar.")
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setWordWrap(True)
        right.addWidget(self.empty_label)
        self.copy_button = QPushButton("Copiar lista do que falta comprar")
        self.copy_button.clicked.connect(self.copy_missing_requested)
        right.addWidget(self.copy_button)
        self.pending_label = QLabel()
        self.pending_label.setObjectName("pendingWarning")
        self.pending_label.setWordWrap(True)
        right.addWidget(self.pending_label)
        self.pending_table = _table("pendingTable", 0, 5)
        self.pending_table.setHorizontalHeaderLabels(
            ("PRODUTO", "SKU", "VARIAÇÃO", "CAMISETAS", "MOTIVO"))
        self.pending_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pending_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pending_table.verticalHeader().hide()
        self.pending_table.setMaximumHeight(170)
        right.addWidget(self.pending_table)
        return right

    # ---- rendering -----------------------------------------------------------------
    def render(self, snapshot) -> None:
        self._rendering = True
        try:
            self._color_ids = [c.id for c in snapshot.colors]
            self._size_ids = [s.id for s in snapshot.sizes]
            self._fill_matrix(snapshot)
            self._fill_separation(snapshot)
            self._fill_pending(snapshot)
            self.note_label.setText(snapshot.note)
            self.note_label.setVisible(bool(snapshot.note))
        finally:
            self._rendering = False

    @staticmethod
    def _header_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setBackground(QBrush(HEADER_BG))
        item.setForeground(QBrush(HEADER_FG))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        return item

    def _fill_matrix(self, snapshot) -> None:
        """One block per color: the color box on the left spans one row per size, and each
        size row shows Estoque | Futuro | Saldo."""
        table = self.matrix
        blocker = QSignalBlocker(table)
        table.clear()
        table.clearSpans()
        sizes = snapshot.sizes
        table.setRowCount(HEADER_ROWS + len(snapshot.colors) * len(sizes))
        table.setColumnCount(len(COLUMNS))
        for column, text in enumerate(COLUMNS):
            table.setItem(0, column, self._header_item(text))
        for block, color in enumerate(snapshot.colors):
            first = HEADER_ROWS + block * len(sizes)
            background, text = shirt_colors(color.name)
            total = sum(snapshot.stock.get((color.id, size.id), 0) for size in sizes)
            label = self._header_item(f"●  {color.name}\n{total} em estoque")
            label.setBackground(QBrush(background))
            label.setForeground(QBrush(text))
            label.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            table.setItem(first, 0, label)
            table.setSpan(first, 0, len(sizes), 1)
            for offset, size in enumerate(sizes):
                row = first + offset
                key = (color.id, size.id)
                stock, future = snapshot.stock.get(key, 0), snapshot.future.get(key, 0)
                name = self._header_item(size.name)
                table.setItem(row, 1, name)
                for kind, value in enumerate((stock, future, stock - future)):
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if kind > 0:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if kind == 1 and value > 0:
                        item.setForeground(QBrush(WARNING))
                    if kind == 2 and value < 0:
                        item.setForeground(QBrush(NEGATIVE))
                        item.setBackground(QBrush(QColor("#3a0d17")))
                        item.setToolTip("Saldo negativo: faltam camisetas para os pedidos.")
                    table.setItem(row, 2 + kind, item)
                table.setRowHeight(row, 34)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 170)
        table.setColumnWidth(1, 70)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.setRowHeight(0, 28)
        del blocker

    def _fill_separation(self, snapshot) -> None:
        table = self.separation_table
        blocker = QSignalBlocker(table)
        table.setRowCount(len(snapshot.separation))
        self._separation_keys = []
        for row, entry in enumerate(snapshot.separation):
            self._separation_keys.append((entry.color_id, entry.size_id))
            values = (entry.color, entry.size, str(entry.needed), str(entry.available),
                      str(entry.missing))
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column >= 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 4 and entry.missing > 0:
                    item.setForeground(QBrush(NEGATIVE))
                table.setItem(row, column, item)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked if entry.separated
                                else Qt.CheckState.Unchecked)
            check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 5, check)
        del blocker
        empty = not snapshot.separation
        self.empty_label.setVisible(empty)
        self.copy_button.setEnabled(any(e.missing > 0 for e in snapshot.separation))

    def _fill_pending(self, snapshot) -> None:
        table = self.pending_table
        table.setRowCount(len(snapshot.pending))
        for row, entry in enumerate(snapshot.pending):
            for column, text in enumerate((entry.product_name, entry.sku, entry.variation,
                                           str(entry.quantity), entry.reason)):
                item = QTableWidgetItem(text)
                item.setForeground(QBrush(WARNING))
                table.setItem(row, column, item)
        total = sum(entry.quantity for entry in snapshot.pending)
        has = bool(snapshot.pending)
        self.pending_label.setText(
            f"Atenção: {total} camiseta(s) pendentes ficaram FORA da conta (cor ou tamanho "
            "não identificados). Importe de novo e preencha a janela de validação." if has else "")
        self.pending_label.setVisible(has)
        table.setVisible(has)

    # ---- user edits ------------------------------------------------------------------
    def _stock_item_changed(self, item) -> None:
        if self._rendering or item.row() < HEADER_ROWS or item.column() != 2:
            return                          # only the Estoque column is editable
        color_index, size_index = divmod(item.row() - HEADER_ROWS, len(self._size_ids))
        self.stock_edit_requested.emit(
            self._color_ids[color_index], self._size_ids[size_index], item.text())

    def _separated_item_changed(self, item) -> None:
        if self._rendering or item.column() != 5:
            return
        color_id, size_id = self._separation_keys[item.row()]
        self.separated_changed.emit(color_id, size_id,
                                    item.checkState() == Qt.CheckState.Checked)
