"""Aba "Estoque de camisetas": summary cards on top, stock / futuro / saldo on the left and
"Separação" on the right.

Only shows data and emits signals; the StockController decides everything."""
from PySide6.QtCore import QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemDelegate, QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from dtf_manager.utils.stock_names import normalize_name

NEGATIVE = QColor("#ff5a75")
WARNING = QColor("#e69b45")            # amber: futuro greater than zero
OK_GREEN = QColor("#54c98a")
ZERO = QColor("#5b5154")               # weak gray for zeros
NORMAL = QColor("#f4eef0")
NEGATIVE_BG = QColor("#3a0d17")
HOVER_BG = QColor("#2e0f18")
TOTAL_BG = QColor("#191217")
HEADER_ROWS = 2                 # row 0: COR | TAM. | ESTOQUE | FUTURO | SALDO, row 1: gap
GAP_HEIGHT = 10                 # blank row between two color boxes
CARD_RADIUS = 10
CARD_BORDER = QColor("#33232b")
PAGE_BG = QColor("#08060a")
COLUMNS = ("COR", "TAM.", "ESTOQUE", "FUTURO", "SALDO")
STOCK_COLUMN = 2
ROW_DARK = QColor("#110c10")
ROW_LIGHT = QColor("#191217")
HEADER_BG = QColor("#191217")
HEADER_FG = QColor("#a89aa1")
BASE_ROLE = Qt.ItemDataRole.UserRole + 1     # the background an item has without hover

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


class StockMatrix(QTableWidget):
    """The stock table: hover highlight on editable cells and keyboard navigation.

    Tab goes to the next editable cell, Shift+Tab to the previous one, Enter confirms and goes
    down, Esc cancels. Only the Estoque column is editable, so "next" is the next Estoque cell
    (color by color, size by size). In quick-count mode the same keys walk the whole table and
    Esc (or the end of the table) leaves the mode."""
    quick_count_ended = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("stockTable")
        self.setMouseTracking(True)
        self.quick_mode = False
        self._stock_rows: list[int] = []
        self._hover: tuple[int, int] | None = None
        self._blocks: list[tuple[int, int]] = []
        self.setShowGrid(False)

    # ---- editable cells ------------------------------------------------------------
    def set_stock_rows(self, rows) -> None:
        self._stock_rows = sorted(rows)
        self._hover = None

    @property
    def stock_rows(self) -> list[int]:
        return list(self._stock_rows)

    def _neighbor(self, row: int, step: int) -> int | None:
        if row in self._stock_rows:
            position = self._stock_rows.index(row) + step
            if 0 <= position < len(self._stock_rows):
                return self._stock_rows[position]
        return None

    def edit_stock_row(self, row: int) -> None:
        item = self.item(row, STOCK_COLUMN)
        if item is not None:
            self.setCurrentCell(row, STOCK_COLUMN)
            self.editItem(item)

    def closeEditor(self, editor, hint) -> None:
        row = self.currentRow()
        if hint in (QAbstractItemDelegate.EndEditHint.SubmitModelCache,
                    QAbstractItemDelegate.EndEditHint.EditNextItem,
                    QAbstractItemDelegate.EndEditHint.EditPreviousItem):
            super().closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
            step = -1 if hint == QAbstractItemDelegate.EndEditHint.EditPreviousItem else 1
            target = self._neighbor(row, step)
            if target is not None:
                self.edit_stock_row(target)
            elif self.quick_mode:
                self._end_quick()
            return
        super().closeEditor(editor, hint)
        if self.quick_mode and hint == QAbstractItemDelegate.EndEditHint.RevertModelCache:
            self._end_quick()                                   # Esc

    def _end_quick(self) -> None:
        self.quick_mode = False
        self.quick_count_ended.emit()

    # ---- hover -----------------------------------------------------------------------
    def _paint(self, position, hovered: bool) -> None:
        item = self.item(*position) if position is not None else None
        if item is None:
            return
        base = item.data(BASE_ROLE)
        item.setBackground(QBrush(HOVER_BG if hovered else (base or ROW_DARK)))

    def set_hover(self, position) -> None:
        if position == self._hover:
            return
        self._paint(self._hover, False)
        self._hover = position
        self._paint(position, True)

    def set_blocks(self, blocks) -> None:
        """(first row, last row) of each rounded box: one per color and the Total geral."""
        self._blocks = list(blocks)
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._blocks or self.columnCount() == 0:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        model, last_column = self.model(), self.columnCount() - 1
        for first, last in self._blocks:
            area = self.visualRect(model.index(first, 0)).united(
                self.visualRect(model.index(last, last_column)))
            rect = QRectF(area).adjusted(0.75, 0.75, -0.75, -0.75)
            outside = QPainterPath()
            outside.addRect(rect.adjusted(-3, -3, 3, 3))
            inside = QPainterPath()
            inside.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
            painter.fillPath(outside.subtracted(inside), PAGE_BG)    # round the square corners
            painter.setPen(QPen(CARD_BORDER, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        painter.end()

    def reapply_hover(self) -> None:
        self._paint(self._hover, True)

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        item = self.itemAt(event.position().toPoint())
        editable = (item is not None and item.column() == STOCK_COLUMN
                    and item.row() in self._stock_rows)
        self.set_hover((item.row(), item.column()) if editable else None)

    def leaveEvent(self, event) -> None:
        self.set_hover(None)
        super().leaveEvent(event)


class StockTab(QWidget):
    new_color_requested = Signal()
    new_size_requested = Signal()
    delete_color_requested = Signal(int)             # color id, or -1 = ask which one
    bulk_requested = Signal()
    history_requested = Signal()
    stock_edit_requested = Signal(int, int, str)     # color id, size id, typed text
    separated_changed = Signal(int, int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stockTab")
        self._rendering = False
        self._color_ids: list[int] = []
        self._size_ids: list[int] = []
        self._structure = None
        self._total_row = -1
        self._separation_keys: list[tuple[int, int]] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(14)
        outer.addLayout(self._build_cards())
        content = QHBoxLayout()
        content.setSpacing(18)
        content.addLayout(self._build_left(), 3)
        content.addLayout(self._build_right(), 2)
        outer.addLayout(content, 1)

    # ---- layout ------------------------------------------------------------------
    def _build_cards(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)
        for attribute, title in (("stock_card", "Em estoque"),
                                 ("order_card", "Total no pedido"),
                                 ("missing_card", "Faltam comprar")):
            frame = QFrame()
            frame.setObjectName("summaryCard")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(18, 12, 18, 12)
            layout.setSpacing(2)
            caption = QLabel(title.upper())
            caption.setObjectName("summaryTitle")
            value = QLabel("0")
            value.setObjectName("summaryValue")
            value.setProperty("tone", "normal")
            layout.addWidget(caption)
            layout.addWidget(value)
            frame.title_label, frame.value_label = caption, value
            setattr(self, attribute, frame)
            row.addWidget(frame, 1)
        return row

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
            ("delete_color_button", "Excluir cor", None),
            ("bulk_button", "Adicionar estoque em massa", self.bulk_requested),
        ):
            button = QPushButton(text)
            if signal is None:
                button.clicked.connect(lambda: self.delete_color_requested.emit(-1))
            else:
                button.clicked.connect(signal)
            setattr(self, attribute, button)
            buttons.addWidget(button)
        self.quick_button = QPushButton("Contagem rápida")
        self.quick_button.setObjectName("quickCountButton")
        self.quick_button.setCheckable(True)
        self.quick_button.setToolTip(
            "Percorre as células de Estoque uma a uma: Enter grava e avança, Esc sai.")
        self.quick_button.clicked.connect(self._quick_clicked)
        buttons.addWidget(self.quick_button)
        buttons.addStretch()
        left.addLayout(buttons)
        self.note_label = QLabel()
        self.note_label.setObjectName("muted")
        self.note_label.setWordWrap(True)
        left.addWidget(self.note_label)
        self.quick_banner = QLabel(
            "CONTAGEM RÁPIDA — digite a quantidade e tecle Enter para gravar e avançar. "
            "Esc para sair.")
        self.quick_banner.setObjectName("quickBanner")
        self.quick_banner.setWordWrap(True)
        self.quick_banner.hide()
        left.addWidget(self.quick_banner)
        self.matrix = StockMatrix()
        self.stock_table = self.matrix
        self.matrix.horizontalHeader().hide()
        self.matrix.verticalHeader().hide()
        self.matrix.setAlternatingRowColors(False)
        self.matrix.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.matrix.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.matrix.itemChanged.connect(self._stock_item_changed)
        self.matrix.quick_count_ended.connect(self._quick_ended)
        left.addWidget(self.matrix, 1)
        self.hint_label = QLabel(
            "Editar o Estoque: dois cliques na célula  ·  Tab avança  ·  Enter grava e desce  ·  "
            "Esc cancela.   Futuro = o que os pedidos importados vão consumir; "
            "Saldo = Estoque − Futuro.")
        self.hint_label.setObjectName("stockHint")
        self.hint_label.setWordWrap(True)
        left.addWidget(self.hint_label)
        return left

    def _build_right(self) -> QVBoxLayout:
        right = QVBoxLayout()
        right.setSpacing(10)
        title = QLabel("SEPARAÇÃO")
        title.setObjectName("sectionTitle")
        right.addWidget(title)
        self.separation_stack = QStackedWidget()
        self.empty_label = QLabel("Importe uma planilha na aba DTF para ver o que separar.")
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.separation_table = _table("separationTable", 0, 5)
        self.separation_table.setHorizontalHeaderLabels(
            ("COR", "TAM.", "PRECISA", "ESTOQUE", "SEPARADO"))
        self.separation_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.separation_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.separation_table.verticalHeader().hide()
        self.separation_table.itemChanged.connect(self._separated_item_changed)
        self.separation_stack.addWidget(self.empty_label)
        self.separation_stack.addWidget(self.separation_table)
        right.addWidget(self.separation_stack, 1)
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
            self._fill_cards(snapshot)
            self._fill_matrix(snapshot)
            self._fill_separation(snapshot)
            self._fill_pending(snapshot)
            self.note_label.setText(snapshot.note)
            self.note_label.setVisible(bool(snapshot.note))
        finally:
            self._rendering = False

    def _fill_cards(self, snapshot) -> None:
        in_stock = sum(snapshot.stock.values())
        in_order = sum(snapshot.future.values())
        missing = sum(max(0, quantity - snapshot.stock.get(key, 0))
                      for key, quantity in snapshot.future.items())
        self.stock_card.value_label.setText(str(in_stock))
        self.order_card.value_label.setText(str(in_order))
        self.missing_card.value_label.setText(f"{missing} de {in_order}")
        label = self.missing_card.value_label
        label.setProperty("tone", "alert" if missing > 0 else "normal")
        label.style().unpolish(label)
        label.style().polish(label)

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

    @staticmethod
    def _style_value(item, kind: int, value: int, base: QColor) -> None:
        """Zero in weak gray, positive in normal emphasis, Futuro > 0 amber, Saldo < 0 red."""
        if value == 0:
            color = ZERO
        elif kind == 1:
            color = WARNING
        elif kind == 2 and value < 0:
            color = NEGATIVE
        else:
            color = NORMAL
        if kind == 2 and value < 0:
            base = NEGATIVE_BG
            item.setToolTip("Saldo negativo: faltam camisetas para os pedidos.")
        else:
            item.setToolTip("")
        item.setText(str(value))
        item.setForeground(QBrush(color))
        item.setData(BASE_ROLE, base)
        item.setBackground(QBrush(base))
        font = item.font()
        font.setBold(value != 0)
        item.setFont(font)

    def _fill_matrix(self, snapshot) -> None:
        """One block per color (the color box spans one row per size; each size row shows
        Estoque | Futuro | Saldo) and a single "Total geral" row at the end."""
        table = self.matrix
        sizes, colors = snapshot.sizes, snapshot.colors
        structure = (tuple((c.id, c.name) for c in colors), tuple((s.id, s.name) for s in sizes))
        step = len(sizes) + 1                       # one box of sizes + one gap row
        total_row = HEADER_ROWS + len(colors) * step
        editing = table.state() == QAbstractItemView.State.EditingState
        blocker = QSignalBlocker(table)
        if structure != self._structure:
            table.set_hover(None)
            table.clear()
            table.clearSpans()
            table.verticalHeader().setMinimumSectionSize(4)    # lets the gap rows be thin
            table.setRowCount(total_row + 1)
            blocks = []
            table.setColumnCount(len(COLUMNS))
            for column, text in enumerate(COLUMNS):
                table.setItem(0, column, self._header_item(text))
            for block, color in enumerate(colors):
                first = HEADER_ROWS + block * step
                blocks.append((first, first + len(sizes) - 1))
                table.setRowHeight(first + len(sizes), GAP_HEIGHT)
                background, text = shirt_colors(color.name)
                label = self._header_item(color.name.upper())
                label.setBackground(QBrush(background))
                label.setForeground(QBrush(text))
                label.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                table.setItem(first, 0, label)
                table.setSpan(first, 0, len(sizes), 1)
                for offset, size in enumerate(sizes):
                    row = first + offset
                    band = ROW_LIGHT if offset % 2 else ROW_DARK     # P dark, M light, G dark...
                    name = self._header_item(size.name)
                    name.setBackground(QBrush(band))
                    table.setItem(row, 1, name)
                    for kind in range(3):
                        item = QTableWidgetItem("0")
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        if kind > 0:
                            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setData(BASE_ROLE, band)
                        table.setItem(row, STOCK_COLUMN + kind, item)
                    table.setRowHeight(row, 26)
            total_label = self._header_item("TOTAL GERAL")
            total_label.setBackground(QBrush(TOTAL_BG))
            table.setItem(total_row, 0, total_label)
            table.setSpan(total_row, 0, 1, 2)
            for kind in range(3):
                item = QTableWidgetItem("0")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(total_row, STOCK_COLUMN + kind, item)
            header = table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(0, 170)
            table.setColumnWidth(1, 70)
            table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            table.setRowHeight(0, 28)
            table.setRowHeight(1, GAP_HEIGHT)
            table.setRowHeight(total_row, 32)
            blocks.append((total_row, total_row))
            table.set_blocks(blocks)
            table.set_stock_rows(row for first, last in blocks[:-1]
                                 for row in range(first, last + 1))
            self._structure, self._total_row = structure, total_row
        # values: updated in place, so an open editor survives the refresh
        totals = [0, 0, 0]
        for block, color in enumerate(colors):
            for offset, size in enumerate(sizes):
                row = HEADER_ROWS + block * step + offset
                key = (color.id, size.id)
                stock, future = snapshot.stock.get(key, 0), snapshot.future.get(key, 0)
                for kind, value in enumerate((stock, future, stock - future)):
                    totals[kind] += value
                    item = table.item(row, STOCK_COLUMN + kind)
                    if kind == 0 and editing and item is table.currentItem():
                        continue                         # do not overwrite what is being typed
                    base = item.data(BASE_ROLE) or ROW_DARK
                    self._style_value(item, kind, value, base)
        for kind, value in enumerate(totals):
            item = table.item(total_row, STOCK_COLUMN + kind)
            self._style_value(item, kind, value, TOTAL_BG)
        table.reapply_hover()
        del blocker

    def _fill_separation(self, snapshot) -> None:
        table = self.separation_table
        blocker = QSignalBlocker(table)
        table.setRowCount(len(snapshot.separation))
        self._separation_keys = []
        for row, entry in enumerate(snapshot.separation):
            self._separation_keys.append((entry.color_id, entry.size_id))
            for column, text in enumerate((entry.color, entry.size, str(entry.needed))):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if column >= 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, column, item)
            covered = entry.available >= entry.needed
            mark = QTableWidgetItem("✓" if covered else "✗")
            mark.setFlags(Qt.ItemFlag.ItemIsEnabled)
            mark.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            mark.setForeground(QBrush(OK_GREEN if covered else NEGATIVE))
            font = mark.font()
            font.setBold(True)
            font.setPointSize(14)
            mark.setFont(font)
            mark.setToolTip("O estoque cobre a quantidade." if covered
                            else f"Faltam {entry.missing}")
            table.setItem(row, 3, mark)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked if entry.separated
                                else Qt.CheckState.Unchecked)
            check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 4, check)
        del blocker
        self.separation_stack.setCurrentWidget(
            self.separation_table if snapshot.separation else self.empty_label)

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

    # ---- quick count --------------------------------------------------------------------
    def _quick_clicked(self, checked: bool) -> None:
        if checked:
            self.start_quick_count()
        else:
            self.matrix.quick_mode = False
            self._quick_ended()

    def start_quick_count(self) -> None:
        rows = self.matrix.stock_rows
        if not rows:
            self.quick_button.setChecked(False)
            return
        self.matrix.quick_mode = True
        self.quick_button.setChecked(True)
        self.quick_banner.show()
        self.matrix.setFocus()
        self.matrix.edit_stock_row(rows[0])

    def _quick_ended(self) -> None:
        self.matrix.quick_mode = False
        self.quick_button.setChecked(False)
        self.quick_banner.hide()

    # ---- user edits ------------------------------------------------------------------
    def _stock_item_changed(self, item) -> None:
        if (self._rendering or item.column() != STOCK_COLUMN
                or item.row() not in self.matrix.stock_rows):
            return                          # only the Estoque cells are editable
        color_index, size_index = divmod(item.row() - HEADER_ROWS, len(self._size_ids) + 1)
        self.stock_edit_requested.emit(
            self._color_ids[color_index], self._size_ids[size_index], item.text())

    def _separated_item_changed(self, item) -> None:
        if self._rendering or item.column() != 4:
            return
        color_id, size_id = self._separation_keys[item.row()]
        self.separated_changed.emit(color_id, size_id,
                                    item.checkState() == Qt.CheckState.Checked)
