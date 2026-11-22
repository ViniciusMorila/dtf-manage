"""Aba "Estoque de estampas": summary cards on top, the art list (stock / futuro / saldo) on the
left and "Separação" on the right. Only shows data and emits signals; the ArtStockController
decides everything. Thumbnails come lazily from a ThumbnailCache: only the rows on screen (plus a
margin) are requested, so a folder with hundreds of images never freezes the window."""
from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from dtf_manager.ui.pages.stock_tab import (
    BASE_ROLE, NEGATIVE, NORMAL, OK_GREEN, ROW_DARK, ROW_LIGHT, STOCK_COLUMN, WARNING,
    StockMatrix, StockTab,
)
from dtf_manager.utils.stock_names import normalize_name

THUMB_SIZE = 44
ROW_HEIGHT = 52
VISIBLE_MARGIN = 6                      # extra rows loaded above/below the visible ones
IMAGE_COLUMN = 0
NAME_COLUMN = 1


def _table(name: str, columns: int) -> QTableWidget:
    table = QTableWidget(0, columns)
    table.setObjectName(name)
    table.setAlternatingRowColors(False)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().hide()
    table.setIconSize(QSize(THUMB_SIZE, THUMB_SIZE))
    return table


class ArtStockTab(QWidget):
    stock_edit_requested = Signal(int, str)          # art id, typed text
    separated_changed = Signal(int, bool)
    move_requested = Signal()
    suggest_requested = Signal()
    copy_missing_requested = Signal()
    history_requested = Signal()
    manual_link_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("artStockTab")
        self._rendering = False
        self._thumbs = None
        self._snapshot = None
        self._folder_text = ""
        self._structure = None
        self._row_ids: list[int] = []
        self._paths = {"main": [], "sep": []}        # row -> image path, per table
        self._path_rows: dict[str, list] = {}        # image path -> [(table key, row)]
        self._separation_ids: list[int] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)
        outer.addLayout(self._build_cards())
        outer.addLayout(self._build_notices())
        content = QHBoxLayout()
        content.setSpacing(18)
        content.addLayout(self._build_left(), 3)
        content.addLayout(self._build_right(), 2)
        outer.addLayout(content, 1)
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(40)
        self._visible_timer.timeout.connect(self.request_visible_thumbnails)

    # ---- layout ------------------------------------------------------------------
    def _build_cards(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)
        for attribute, title in (("stock_card", "Total em estoque"),
                                 ("order_card", "Total no pedido"),
                                 ("missing_card", "Faltam")):
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

    def _build_notices(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        link_row = QHBoxLayout()
        self.unlinked_label = QLabel()
        self.unlinked_label.setObjectName("pendingWarning")
        self.link_button = QPushButton("Abrir vinculação manual")
        self.link_button.clicked.connect(self.manual_link_requested)
        link_row.addWidget(self.unlinked_label)
        link_row.addWidget(self.link_button)
        link_row.addStretch()
        box.addLayout(link_row)
        self.unlinked_label.hide()
        self.link_button.hide()
        self.identical_label = QLabel()
        self.identical_label.setObjectName("muted")
        self.identical_label.setWordWrap(True)
        self.identical_label.hide()
        box.addWidget(self.identical_label)
        self.thumb_notice = QLabel()
        self.thumb_notice.setObjectName("muted")
        self.thumb_notice.hide()
        box.addWidget(self.thumb_notice)
        return box

    def _build_left(self) -> QVBoxLayout:
        left = QVBoxLayout()
        left.setSpacing(10)
        title = QLabel("ESTOQUE DE ESTAMPAS")
        title.setObjectName("sectionTitle")
        left.addWidget(title)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar pelo nome do arquivo...")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Buscar estampa")
        self.search.textChanged.connect(self._refilter)
        tools.addWidget(self.search, 1)
        self.only_future = QPushButton("Só com futuro")
        self.only_short = QPushButton("Só com falta")
        for button in (self.only_future, self.only_short):
            button.setObjectName("stockViewButton")
            button.setCheckable(True)
            button.toggled.connect(self._refilter)
            tools.addWidget(button)
        left.addLayout(tools)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.move_button = QPushButton("Mover estoque para outro arquivo")
        self.move_button.clicked.connect(self.move_requested)
        self.suggest_button = QPushButton("Sugerir correspondências")
        self.suggest_button.clicked.connect(self.suggest_requested)
        self.suggest_button.hide()
        for button in (self.move_button, self.suggest_button):
            buttons.addWidget(button)
        buttons.addStretch()
        left.addLayout(buttons)
        self.matrix = StockMatrix()
        self.matrix.setObjectName("artStockTable")
        self.matrix.setColumnCount(5)
        self.matrix.setHorizontalHeaderLabels(("IMAGEM", "ARQUIVO", "ESTOQUE", "FUTURO", "SALDO"))
        self.matrix.verticalHeader().hide()
        self.matrix.setIconSize(QSize(THUMB_SIZE, THUMB_SIZE))
        self.matrix.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.matrix.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.matrix.itemChanged.connect(self._stock_item_changed)
        self.matrix.verticalScrollBar().valueChanged.connect(self._schedule_visible)
        self.list_empty = QLabel()
        self.list_empty.setObjectName("emptyState")
        self.list_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_empty.setWordWrap(True)
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.list_empty)
        self.list_stack.addWidget(self.matrix)
        left.addWidget(self.list_stack, 1)
        self.hint_label = QLabel(
            "Editar o Estoque: dois cliques na célula  ·  Tab avança  ·  Enter grava e desce  ·  "
            "Esc cancela.   Futuro = cópias que o pedido importado vai usar; Saldo = Estoque − Futuro.")
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
        self.separation_table = _table("artSeparationTable", 5)
        self.separation_table.setHorizontalHeaderLabels(
            ("IMAGEM", "ARQUIVO", "USADA", "ESTOQUE", "SEPARADO"))
        self.separation_table.itemChanged.connect(self._separated_item_changed)
        self.separation_table.verticalScrollBar().valueChanged.connect(self._schedule_visible)
        self.separation_stack.addWidget(self.empty_label)
        self.separation_stack.addWidget(self.separation_table)
        right.addWidget(self.separation_stack, 1)
        self.copy_button = QPushButton("Copiar lista do que falta")
        self.copy_button.clicked.connect(self.copy_missing_requested)
        right.addWidget(self.copy_button)
        return right

    # ---- public ---------------------------------------------------------------------
    def set_thumbnails(self, thumbs) -> None:
        self._thumbs = thumbs
        thumbs.ready.connect(self._thumbnail_ready)

    def render(self, snapshot, folder_text: str = "", has_missing_with_stock: bool = False) -> None:
        self._rendering = True
        try:
            self._snapshot, self._folder_text = snapshot, folder_text
            self._fill_cards(snapshot)
            self._fill_notices(snapshot)
            self._fill_list()
            self._fill_separation(snapshot)
            self.suggest_button.setVisible(has_missing_with_stock)
        finally:
            self._rendering = False
        self._schedule_visible()

    def set_identical(self, groups) -> None:
        if not groups:
            self.identical_label.hide()
            return
        shown = ["  =  ".join(path.replace("\\", "/").rsplit("/", 1)[-1] for path in group)
                 for group in groups[:3]]
        more = f"  (+{len(groups) - 3})" if len(groups) > 3 else ""
        self.identical_label.setText(
            "Arquivos com conteúdo idêntico (não foram unidos): " + ";  ".join(shown) + more)
        self.identical_label.show()

    # ---- cards and notices --------------------------------------------------------------
    def _fill_cards(self, snapshot) -> None:
        self.stock_card.value_label.setText(str(snapshot.total_stock))
        self.order_card.value_label.setText(str(snapshot.total_future))
        missing = snapshot.total_shortage
        label = self.missing_card.value_label
        label.setText(f"{missing} de {snapshot.total_future}")
        label.setProperty("tone", "alert" if missing > 0 else "normal")
        label.style().unpolish(label)
        label.style().polish(label)

    def _fill_notices(self, snapshot) -> None:
        count = snapshot.unlinked_items
        self.unlinked_label.setText(f"{count} itens sem arte vinculada" if count != 1
                                    else "1 item sem arte vinculada")
        self.unlinked_label.setVisible(count > 0)
        self.link_button.setVisible(count > 0)

    # ---- the list --------------------------------------------------------------------------
    def _matches(self, row) -> bool:
        text = normalize_name(self.search.text())
        if text and text not in normalize_name(row.relative_path):
            return False
        if self.only_future.isChecked() and row.future <= 0:
            return False
        if self.only_short.isChecked() and row.shortage <= 0:
            return False
        return True

    def _refilter(self, *_args) -> None:
        if self._snapshot is not None:
            self._rendering = True
            try:
                self._fill_list()
            finally:
                self._rendering = False
            self._schedule_visible()

    def _fill_list(self) -> None:
        snapshot = self._snapshot
        rows = [r for r in snapshot.rows if self._matches(r)]
        if not rows:
            if not self._folder_text and not snapshot.rows:
                self.list_empty.setText("Selecione a pasta das artes na aba DTF para ver as artes.")
            elif not snapshot.rows:
                self.list_empty.setText("Nenhuma arte encontrada na pasta selecionada.")
            else:
                self.list_empty.setText("Nenhuma arte corresponde à busca ou aos filtros.")
        self.list_stack.setCurrentWidget(self.matrix if rows else self.list_empty)
        table = self.matrix
        structure = tuple((r.art_id, r.relative_path, r.missing, r.outside_folder) for r in rows)
        editing = table.state() == QAbstractItemView.State.EditingState
        blocker = QSignalBlocker(table)
        if structure != self._structure:
            table.set_hover(None)
            table.setRowCount(0)
            table.setRowCount(len(rows))
            self._row_ids = [r.art_id for r in rows]
            self._paths["main"] = [r.absolute_path for r in rows]
            for index, row in enumerate(rows):
                base = ROW_LIGHT if index % 2 else ROW_DARK
                image = QTableWidgetItem()
                image.setFlags(Qt.ItemFlag.ItemIsEnabled)
                image.setBackground(QBrush(base))
                image.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(index, IMAGE_COLUMN, image)
                name = QTableWidgetItem(row.relative_path)
                name.setFlags(Qt.ItemFlag.ItemIsEnabled)
                name.setBackground(QBrush(base))
                tooltip = row.absolute_path
                if row.missing:
                    name.setText(row.relative_path + "  ·  arquivo não encontrado")
                    name.setForeground(QBrush(WARNING))
                    tooltip += "\nO arquivo não está mais na pasta; o estoque foi mantido."
                elif row.outside_folder:
                    name.setText(row.relative_path + "  ·  fora da pasta")
                    name.setForeground(QBrush(WARNING))
                    tooltip += "\nArte vinculada de fora da pasta selecionada."
                else:
                    name.setForeground(QBrush(NORMAL))
                name.setToolTip(tooltip)
                table.setItem(index, NAME_COLUMN, name)
                for kind in range(3):
                    item = QTableWidgetItem("0")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if kind > 0:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setData(BASE_ROLE, base)
                    table.setItem(index, STOCK_COLUMN + kind, item)
                table.setRowHeight(index, ROW_HEIGHT)
            header = table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(IMAGE_COLUMN, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(IMAGE_COLUMN, THUMB_SIZE + 22)
            header.setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
            table.set_stock_rows(range(len(rows)))
            self._structure = structure
            self._rebuild_path_rows()
        for index, row in enumerate(rows):                    # values: in place (keeps an editor)
            for kind, value in enumerate((row.stock, row.future, row.balance)):
                item = table.item(index, STOCK_COLUMN + kind)
                if kind == 0 and editing and item is table.currentItem():
                    continue
                StockTab._style_value(item, kind, value, item.data(BASE_ROLE) or ROW_DARK)
        table.reapply_hover()
        del blocker

    def _fill_separation(self, snapshot) -> None:
        table = self.separation_table
        blocker = QSignalBlocker(table)
        table.setRowCount(len(snapshot.separation))
        self._separation_ids = []
        self._paths["sep"] = []
        for index, entry in enumerate(snapshot.separation):
            self._separation_ids.append(entry.art_id)
            self._paths["sep"].append(entry.absolute_path)
            image = QTableWidgetItem()
            image.setFlags(Qt.ItemFlag.ItemIsEnabled)
            image.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(index, IMAGE_COLUMN, image)
            name = QTableWidgetItem(entry.name)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name.setToolTip(entry.absolute_path)
            table.setItem(index, NAME_COLUMN, name)
            used = QTableWidgetItem(str(entry.needed))
            used.setFlags(Qt.ItemFlag.ItemIsEnabled)
            used.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(index, 2, used)
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
                            else f"Faltam {entry.shortage}")
            table.setItem(index, 3, mark)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked if entry.separated
                                else Qt.CheckState.Unchecked)
            check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(index, 4, check)
            table.setRowHeight(index, ROW_HEIGHT)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(IMAGE_COLUMN, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(IMAGE_COLUMN, THUMB_SIZE + 22)
        del blocker
        self.separation_stack.setCurrentWidget(
            self.separation_table if snapshot.separation else self.empty_label)
        self.copy_button.setEnabled(any(e.shortage > 0 for e in snapshot.separation))
        self._rebuild_path_rows()

    # ---- thumbnails (lazy) -------------------------------------------------------------------
    def _rebuild_path_rows(self) -> None:
        self._path_rows = {}
        for key in ("main", "sep"):
            for row, path in enumerate(self._paths[key]):
                self._path_rows.setdefault(path, []).append((key, row))

    def _table_for(self, key):
        return self.matrix if key == "main" else self.separation_table

    def _schedule_visible(self, *_args) -> None:
        if self._thumbs is not None:
            self._visible_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_visible()

    def _visible_range(self, table, count: int) -> range:
        if count == 0:
            return range(0)
        first = table.rowAt(0)
        last = table.rowAt(max(0, table.viewport().height() - 1))
        first = 0 if first < 0 else first
        last = min(count - 1, first + 14) if last < 0 else last
        return range(max(0, first - VISIBLE_MARGIN), min(count, last + VISIBLE_MARGIN + 1))

    def request_visible_thumbnails(self) -> None:
        """Asks only for the rows on screen (plus a margin); cached ones are shown at once."""
        if self._thumbs is None:
            return
        for key in ("main", "sep"):
            paths = self._paths[key]
            table = self._table_for(key)
            for row in self._visible_range(table, len(paths)):
                path = paths[row]
                if self._thumbs.pixmap(path) is None:
                    self._thumbs.request(path)
                self._apply_thumbnail(key, row, path)
        self._update_thumb_notice()

    def _apply_thumbnail(self, key: str, row: int, path: str) -> None:
        item = self._table_for(key).item(row, IMAGE_COLUMN)
        if item is None:
            return
        pixmap = self._thumbs.pixmap(path)
        if pixmap is not None:
            item.setIcon(QIcon(pixmap))
            item.setText("")
        elif self._thumbs.has_failed(path):
            item.setIcon(QIcon())
            item.setText("sem miniatura")
            item.setToolTip("Não foi possível ler esta imagem.")

    def _thumbnail_ready(self, path: str) -> None:
        for key, row in self._path_rows.get(path, ()):
            self._apply_thumbnail(key, row, path)
        self._update_thumb_notice()

    def _update_thumb_notice(self) -> None:
        if self._thumbs is None:
            return
        bad = sum(1 for path in set(self._paths["main"]) if self._thumbs.has_failed(path))
        self.thumb_notice.setText(f"{bad} arquivo(s) sem miniatura (imagem ilegível)")
        self.thumb_notice.setVisible(bad > 0)

    # ---- user edits ------------------------------------------------------------------------
    def _stock_item_changed(self, item) -> None:
        if (self._rendering or item.column() != STOCK_COLUMN
                or item.row() >= len(self._row_ids)):
            return
        self.stock_edit_requested.emit(self._row_ids[item.row()], item.text())

    def _separated_item_changed(self, item) -> None:
        if self._rendering or item.column() != 4 or item.row() >= len(self._separation_ids):
            return
        self.separated_changed.emit(self._separation_ids[item.row()],
                                    item.checkState() == Qt.CheckState.Checked)
