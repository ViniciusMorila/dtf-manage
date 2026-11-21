"""Aba "Estoque de camisetas": stock / futuro / saldo on the left, "Separação" on the right.

Only shows data and emits signals; the StockController decides everything."""
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

NEGATIVE = QColor("#ff5a75")
WARNING = QColor("#e69b45")
VIEWS = (("Estoque", "stockView"), ("Futuro", "futureView"), ("Saldo total", "balanceView"))


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
        views = QHBoxLayout()
        views.setSpacing(6)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_buttons = []
        for index, (text, name) in enumerate(VIEWS):
            button = QPushButton(text)
            button.setObjectName("stockViewButton")
            button.setCheckable(True)
            self.view_group.addButton(button, index)
            self.view_buttons.append(button)
            views.addWidget(button)
        views.addStretch()
        left.addLayout(views)
        self.note_label = QLabel()
        self.note_label.setObjectName("muted")
        self.note_label.setWordWrap(True)
        left.addWidget(self.note_label)
        self.pages = QStackedWidget()
        self.stock_table = _table("stockTable")
        self.future_table = _table("futureTable")
        self.balance_table = _table("balanceTable")
        for table in (self.future_table, self.balance_table, self.stock_table):
            table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for table in (self.future_table, self.balance_table):
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stock_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.stock_table.itemChanged.connect(self._stock_item_changed)
        for table in (self.stock_table, self.future_table, self.balance_table):
            self.pages.addWidget(table)
        left.addWidget(self.pages, 1)
        self.hint_label = QLabel(
            "Estoque: dê dois cliques numa célula para editar. Futuro: o que os pedidos "
            "importados vão consumir. Saldo total = Estoque − Futuro. "
            "Cada nova importação substitui o futuro atual.")
        self.hint_label.setObjectName("muted")
        self.hint_label.setWordWrap(True)
        left.addWidget(self.hint_label)
        self.view_group.idClicked.connect(self.pages.setCurrentIndex)
        self.view_buttons[0].setChecked(True)
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

    def _fill_matrix(self, snapshot) -> None:
        for kind, table in (("stock", self.stock_table), ("future", self.future_table),
                            ("balance", self.balance_table)):
            blocker = QSignalBlocker(table)
            table.clear()
            table.setRowCount(len(snapshot.colors))
            table.setColumnCount(len(snapshot.sizes))
            table.setHorizontalHeaderLabels([s.name for s in snapshot.sizes])
            table.setVerticalHeaderLabels([c.name for c in snapshot.colors])
            for row, color in enumerate(snapshot.colors):
                for column, size in enumerate(snapshot.sizes):
                    key = (color.id, size.id)
                    stock, future = snapshot.stock.get(key, 0), snapshot.future.get(key, 0)
                    value = {"stock": stock, "future": future, "balance": stock - future}[kind]
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if kind != "stock":
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if kind == "balance" and value < 0:
                        item.setForeground(QBrush(NEGATIVE))
                        item.setBackground(QBrush(QColor("#3a0d17")))
                        item.setToolTip("Saldo negativo: faltam camisetas para os pedidos.")
                    table.setItem(row, column, item)
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
        if self._rendering:
            return
        self.stock_edit_requested.emit(
            self._color_ids[item.row()], self._size_ids[item.column()], item.text())

    def _separated_item_changed(self, item) -> None:
        if self._rendering or item.column() != 5:
            return
        color_id, size_id = self._separation_keys[item.row()]
        self.separated_changed.emit(color_id, size_id,
                                    item.checkState() == Qt.CheckState.Checked)
