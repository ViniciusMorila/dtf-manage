"""Dialogs of the stock tabs and `StockPrompts`, the object the StockController talks to.

Tests replace StockPrompts with a fake, so no dialog ever blocks a test."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from dtf_manager.models.stock import (
    MOVEMENT_LABELS, LineDecision, NoticeChoice,
)
from dtf_manager.utils.stock_format import at_time, date_time, short_date

NEW_COLOR = "__new_color__"


def _read_only_table(name: str, headers) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setObjectName(name)
    table.setHorizontalHeaderLabels(list(headers))
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return table


def _item(text) -> QTableWidgetItem:
    return QTableWidgetItem("" if text is None else str(text))


class BulkAddDialog(QDialog):
    """Quantity to add, color (all/one) and sizes (all/selected), with a confirmation."""

    def __init__(self, colors, sizes, preview, parent=None):
        super().__init__(parent)
        self.setObjectName("bulkAddDialog")
        self.setWindowTitle("Adicionar estoque em massa")
        self._preview = preview
        self._colors, self._sizes = colors, sizes
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Quantidade a adicionar em cada combinação:"))
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 100000)
        self.quantity.setValue(1)
        layout.addWidget(self.quantity)
        layout.addWidget(QLabel("Cor:"))
        self.color = QComboBox()
        self.color.addItem("Todas as cores", None)
        for color in colors:
            self.color.addItem(color.name, color.id)
        layout.addWidget(self.color)
        layout.addWidget(QLabel("Tamanhos:"))
        self.all_sizes = QCheckBox("Todos os tamanhos")
        self.all_sizes.setChecked(True)
        layout.addWidget(self.all_sizes)
        row = QHBoxLayout()
        self.size_boxes = []
        for size in sizes:
            box = QCheckBox(size.name)
            box.setChecked(True)
            box.toggled.connect(self._sync_all)
            self.size_boxes.append((size, box))
            row.addWidget(box)
        layout.addLayout(row)
        self.all_sizes.toggled.connect(
            lambda on: [box.setChecked(on) for _, box in self.size_boxes])
        buttons = QDialogButtonBox()
        self.ok_button = buttons.addButton("Continuar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok_button.setObjectName("primaryButton")
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._confirm)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync_all(self) -> None:
        self.all_sizes.blockSignals(True)
        self.all_sizes.setChecked(all(box.isChecked() for _, box in self.size_boxes))
        self.all_sizes.blockSignals(False)

    def request(self):
        sizes = [size.id for size, box in self.size_boxes if box.isChecked()]
        return self.quantity.value(), self.color.currentData(), sizes

    def summary(self) -> str:
        quantity, color_id, sizes = self.request()
        changes = self._preview(quantity, color_id, sizes)
        lines = [f"{c.name} {s.name}: {before} → {after}" for c, s, before, after in changes[:12]]
        if len(changes) > 12:
            lines.append(f"... e mais {len(changes) - 12} combinações")
        return (f"Serão adicionadas {quantity} unidade(s) em {len(changes)} combinação(ões):\n\n"
                + "\n".join(lines))

    def _confirm(self) -> None:
        if not self.request()[2]:
            QMessageBox.warning(self, "Estoque em massa", "Selecione ao menos um tamanho.")
            return
        answer = QMessageBox.question(self, "Confirmar adição em massa", self.summary())
        if answer == QMessageBox.StandardButton.Yes:
            self.accept()


class ImportNoticeDialog(QDialog):
    """Shown BEFORE processing a spreadsheet: repeated file, finalized and already mounted orders."""

    def __init__(self, notice, parent=None):
        super().__init__(parent)
        self.setObjectName("importNoticeDialog")
        self.setWindowTitle("Antes de importar")
        self.choice = NoticeChoice("cancel")
        layout = QVBoxLayout(self)
        duplicate = notice.duplicate
        if duplicate is not None:
            previous = duplicate.previous
            state = "finalizada no estoque" if duplicate.finalized else "ainda não finalizada"
            text = (f"Esta planilha parece já ter sido importada em "
                    f"{at_time(previous.at)} ({previous.order_count} pedidos).\n"
                    f"Estado: {state}.")
            label = QLabel(text)
            label.setObjectName("importWarning")
            label.setWordWrap(True)
            layout.addWidget(label)
        if notice.finalized_count:
            label = QLabel(f"{notice.finalized_count} pedidos já foram finalizados no estoque em "
                           f"{notice.finalized_date}. Por padrão eles ficam fora do futuro.")
            label.setWordWrap(True)
            layout.addWidget(label)
            self.include_finalized = QCheckBox("Incluir esses pedidos de novo no futuro")
            layout.addWidget(self.include_finalized)
        else:
            self.include_finalized = None
        if notice.mounted_count:
            label = QLabel(f"{notice.mounted_count} pedidos já foram montados antes no rolo "
                           "(eles continuam sendo contados no futuro).")
            label.setObjectName("muted")
            label.setWordWrap(True)
            layout.addWidget(label)
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton("Cancelar importação")
        self.cancel_button.clicked.connect(lambda: self._finish("cancel"))
        buttons.addWidget(self.cancel_button)
        self.only_new_button = None
        if duplicate is not None and duplicate.mixed:
            self.only_new_button = QPushButton("Importar só os pedidos novos")
            self.only_new_button.clicked.connect(lambda: self._finish("only_new"))
            buttons.addWidget(self.only_new_button)
        self.import_button = QPushButton("Importar mesmo assim" if duplicate else "Continuar")
        self.import_button.setObjectName("primaryButton")
        self.import_button.clicked.connect(lambda: self._finish("import"))
        buttons.addWidget(self.import_button)
        layout.addLayout(buttons)
        # the safe choice is the default whenever the file was already finalized
        default = self.cancel_button if duplicate is not None and duplicate.finalized \
            else self.import_button
        default.setDefault(True)
        default.setFocus()

    def _finish(self, action: str) -> None:
        include = bool(self.include_finalized and self.include_finalized.isChecked())
        self.choice = NoticeChoice(action, include)
        self.accept() if action != "cancel" else self.reject()


class ValidationDialog(QDialog):
    """Items without a recognizable color/size, grouped by SKU, before the futuro is computed."""

    def __init__(self, lines, colors, sizes, parent=None):
        super().__init__(parent)
        self.setObjectName("stockValidationDialog")
        self.setWindowTitle("Validar itens da planilha")
        self.resize(1100, 520)
        self.lines = list(lines)
        self._colors, self._sizes = list(colors), list(sizes)
        layout = QVBoxLayout(self)
        intro = QLabel("Alguns itens não tiveram a cor (ou o tamanho) identificada. Escolha "
                       "abaixo; o que ficar pendente fica fora da conta do futuro.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        headers = ("ANÚNCIO", "SKU", "VARIAÇÃO", "TAM.", "CAMISETAS", "COR", "TAMANHO 1",
                   "TAMANHO 2 (KIT)", "LEMBRAR SKU", "")
        self.table = QTableWidget(len(self.lines), len(headers))
        self.table.setObjectName("validationTable")
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.color_boxes, self.size_boxes, self.remember_boxes, self.apply_buttons = [], [], [], []
        for row, line in enumerate(self.lines):
            for column, text in enumerate((line.product_name, line.sku or "(sem SKU)",
                                           line.variation or "—", line.sizes_text or "—",
                                           line.shirts)):
                self.table.setItem(row, column, _item(text))
            color = self._combo(self._color_items(), enabled=line.needs_color)
            color.activated.connect(lambda _i, r=row: self._color_chosen(r))
            self.color_boxes.append(color)
            self.table.setCellWidget(row, 5, color)
            pair = []
            for column in (6, 7):
                box = self._combo(self._size_items(), enabled=line.needs_size)
                box.currentIndexChanged.connect(self._update_buttons)
                pair.append(box)
                self.table.setCellWidget(row, column, box)
            self.size_boxes.append(pair)
            color.currentIndexChanged.connect(self._update_buttons)
            remember = QCheckBox()
            remember.setChecked(bool(line.sku))
            remember.setEnabled(bool(line.sku) and line.needs_color)
            remember.setToolTip("Guarda SKU → cor para as próximas importações."
                                if line.sku else "Sem SKU: vale só para esta importação.")
            self.remember_boxes.append(remember)
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            holder_layout.addWidget(remember)
            self.table.setCellWidget(row, 8, holder)
            apply_button = QPushButton("Aplicar a todos os iguais")
            apply_button.clicked.connect(lambda _c=False, r=row: self.apply_to_equals(r))
            self.apply_buttons.append(apply_button)
            self.table.setCellWidget(row, 9, apply_button)
            self.table.setRowHeight(row, 40)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton("Cancelar")
        self.pending_button = QPushButton("Deixar pendentes")
        self.confirm_button = QPushButton("Confirmar")
        self.confirm_button.setObjectName("primaryButton")
        self.cancel_button.clicked.connect(self.reject)
        self.pending_button.clicked.connect(self.accept)
        self.confirm_button.clicked.connect(self.accept)
        for button in (self.cancel_button, self.pending_button, self.confirm_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._update_buttons()

    # ---- combos ------------------------------------------------------------------
    def _combo(self, items, enabled: bool) -> QComboBox:
        box = QComboBox()
        for text, data in items:
            box.addItem(text, data)
        box.setEnabled(enabled)
        return box

    def _color_items(self):
        return ([("— escolher —", None)] + [(c.name, c.id) for c in self._colors]
                + [("Nova cor...", NEW_COLOR)])

    def _size_items(self):
        return [("—", None)] + [(s.name, s.id) for s in self._sizes]

    def _color_chosen(self, row: int) -> None:
        box = self.color_boxes[row]
        if box.currentData() != NEW_COLOR:
            return
        name, ok = QInputDialog.getText(self, "Nova cor", "Nome da nova cor:")
        name = " ".join(name.split()) if ok else ""
        if not name:
            box.setCurrentIndex(0)
            return
        self.add_color_choice(name, select_row=row)

    def add_color_choice(self, name: str, select_row: int) -> None:
        """Adds a new color name (created only when the user confirms) to every selector."""
        for box in self.color_boxes:
            existing = box.findData(name)
            if existing < 0:
                box.insertItem(box.count() - 1, f"{name} (nova)", name)
        box = self.color_boxes[select_row]
        box.setCurrentIndex(box.findData(name))

    # ---- state ---------------------------------------------------------------------
    def _decision(self, row: int) -> LineDecision | None:
        """The user's choice for a row when it is complete, else None."""
        line = self.lines[row]
        color = self.color_boxes[row].currentData()
        sizes = tuple(box.currentData() for box in self.size_boxes[row]
                      if box.currentData() is not None)
        if line.needs_color and color in (None, NEW_COLOR):
            return None
        if line.needs_size and not sizes:
            return None
        return LineDecision(
            color=color if line.needs_color else None,
            sizes=sizes if line.needs_size else (),
            remember=self.remember_boxes[row].isChecked())

    def _update_buttons(self) -> None:
        filled = sum(1 for row in range(len(self.lines)) if self._decision(row) is not None)
        self.confirm_button.setEnabled(filled == len(self.lines))
        self.status.setText(f"{filled} de {len(self.lines)} linhas preenchidas.")

    def apply_to_equals(self, row: int) -> None:
        """Copies this row's color (same SKU, or same product when there is no SKU) and sizes
        (same Variação) to the equal rows."""
        source = self.lines[row]
        color, sizes = self.color_boxes[row].currentData(), [
            box.currentData() for box in self.size_boxes[row]]
        for other, line in enumerate(self.lines):
            if other == row:
                continue
            same_item = (source.sku and line.sku == source.sku) or (
                not source.sku and not line.sku and line.product_name == source.product_name)
            if same_item and line.needs_color and color not in (None, NEW_COLOR):
                box = self.color_boxes[other]
                index = box.findData(color)
                if index >= 0:
                    box.setCurrentIndex(index)
            if same_item and line.needs_size and line.variation == source.variation:
                for box, value in zip(self.size_boxes[other], sizes):
                    box.setCurrentIndex(max(0, box.findData(value)))
        self._update_buttons()

    def decisions(self) -> dict:
        """line key -> LineDecision, only for the rows the user completed."""
        result = {}
        for row, line in enumerate(self.lines):
            decision = self._decision(row)
            if decision is not None:
                result[line.key] = decision
        return result


class FinalizeDialog(QDialog):
    def __init__(self, summary, parent=None):
        super().__init__(parent)
        self.setObjectName("finalizeDialog")
        self.setWindowTitle("Finalizar pedido")
        self.resize(640, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Isto desconta do estoque as camisetas do futuro e zera o futuro:"))
        table = _read_only_table("finalizeTable",
                                 ("COR", "TAM.", "FUTURO", "ESTOQUE", "DEPOIS", "FALTAM"))
        table.setRowCount(len(summary.rows))
        for row, entry in enumerate(summary.rows):
            for column, value in enumerate((entry.color, entry.size, entry.future, entry.stock,
                                            entry.after, entry.shortage)):
                table.setItem(row, column, _item(value))
        layout.addWidget(table, 1)
        self.acknowledge = None
        if summary.shortages:
            names = ", ".join(f"{r.color} {r.size} (faltam {r.shortage})"
                              for r in summary.shortages)
            label = QLabel(f"Estoque insuficiente em: {names}. O estoque ficará em 0 nesses itens "
                           "e a falta será registrada no histórico.")
            label.setObjectName("pendingWarning")
            label.setWordWrap(True)
            layout.addWidget(label)
        if summary.pending:
            label = QLabel(f"{summary.pending} camiseta(s) pendentes NÃO foram contadas e não "
                           "serão abatidas.")
            label.setObjectName("pendingWarning")
            label.setWordWrap(True)
            layout.addWidget(label)
        if summary.needs_acknowledgement:
            self.acknowledge = QCheckBox("Entendo e quero finalizar mesmo assim")
            layout.addWidget(self.acknowledge)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        self.confirm_button = QPushButton("Finalizar pedido")
        self.confirm_button.setObjectName("primaryButton")
        self.confirm_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm_button)
        layout.addLayout(buttons)
        if self.acknowledge is not None:
            self.confirm_button.setEnabled(False)
            self.acknowledge.toggled.connect(self.confirm_button.setEnabled)


class StockHistoryDialog(QDialog):
    """Movements (with a type filter) and the list of imported spreadsheets."""

    def __init__(self, movements, imports, parent=None):
        super().__init__(parent)
        self.setObjectName("stockHistoryDialog")
        self.setWindowTitle("Histórico do estoque")
        self.resize(980, 560)
        self._movements = list(movements)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        page = QWidget()
        page_layout = QVBoxLayout(page)
        self.filter = QComboBox()
        self.filter.addItem("Todos os tipos", None)
        for kind, label in MOVEMENT_LABELS.items():
            self.filter.addItem(label, kind)
        self.filter.currentIndexChanged.connect(self._fill_movements)
        page_layout.addWidget(self.filter)
        self.movements_table = _read_only_table(
            "movementsTable", ("DATA", "TIPO", "COR", "TAM.", "QTD.", "ANTES", "DEPOIS", "OBS."))
        page_layout.addWidget(self.movements_table)
        tabs.addTab(page, "Movimentos")
        self.imports_table = _read_only_table(
            "importsTable", ("DATA", "ARQUIVO", "PEDIDOS", "FINALIZADA"))
        self.imports_table.setRowCount(len(imports))
        for row, record in enumerate(imports):
            finalized = f"Sim, em {at_time(record.finalized_at)}" if record.finalized_at else "Não"
            for column, value in enumerate((date_time(record.at), record.file_name,
                                            record.order_count, finalized)):
                self.imports_table.setItem(row, column, _item(value))
        tabs.addTab(self.imports_table, "Importações")
        close = QPushButton("Fechar")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self._fill_movements()

    def _fill_movements(self) -> None:
        kind = self.filter.currentData()
        rows = [m for m in self._movements if kind is None or m.kind == kind]
        table = self.movements_table
        table.setRowCount(len(rows))
        for row, move in enumerate(rows):
            quantity = f"{move.quantity:+d}"
            kind_text = MOVEMENT_LABELS.get(move.kind, move.kind)
            if move.scope == "futuro":
                kind_text += " (futuro)"
            for column, value in enumerate((date_time(move.at), kind_text, move.color, move.size,
                                            quantity, move.before, move.after, move.note)):
                table.setItem(row, column, _item(value))


class AliasesDialog(QDialog):
    """Editable equivalence table: text found in the spreadsheet -> color/size."""

    def __init__(self, colors, sizes, aliases, parent=None):
        super().__init__(parent)
        self.setObjectName("aliasesDialog")
        self.setWindowTitle("Equivalências de nomes")
        self.resize(560, 460)
        self._colors, self._sizes = list(colors), list(sizes)
        layout = QVBoxLayout(self)
        note = QLabel("Nomes escritos de outra forma na planilha (ex.: \"preto\" = Preta). "
                      "Maiúsculas, acentos e espaços extras são ignorados.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setObjectName("aliasesTable")
        self.table.setHorizontalHeaderLabels(("TIPO", "TEXTO NA PLANILHA", "EQUIVALE A"))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table, 1)
        for kind, text, target in aliases:
            self.add_row(kind, text, target)
        row = QHBoxLayout()
        add = QPushButton("Adicionar")
        add.clicked.connect(lambda: self.add_row("color", "", None))
        remove = QPushButton("Remover selecionada")
        remove.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_row(self, kind: str, text: str, target) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        kind_box = QComboBox()
        kind_box.addItem("Cor", "color")
        kind_box.addItem("Tamanho", "size")
        kind_box.setCurrentIndex(0 if kind == "color" else 1)
        self.table.setCellWidget(row, 0, kind_box)
        self.table.setItem(row, 1, _item(text))
        target_box = QComboBox()
        self.table.setCellWidget(row, 2, target_box)
        kind_box.currentIndexChanged.connect(lambda _i, b=kind_box, t=target_box: self._targets(b, t))
        self._targets(kind_box, target_box, target)

    def _targets(self, kind_box, target_box, selected=None) -> None:
        target_box.clear()
        options = self._colors if kind_box.currentData() == "color" else self._sizes
        for option in options:
            target_box.addItem(option.name, option.id)
        if selected is not None:
            target_box.setCurrentIndex(max(0, target_box.findData(selected)))

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def rows(self):
        result = []
        for row in range(self.table.rowCount()):
            text = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
            result.append((self.table.cellWidget(row, 0).currentData(), text,
                           self.table.cellWidget(row, 2).currentData()))
        return result


class StockPrompts:
    """Everything the controller asks the user. One method per question."""

    def __init__(self, parent=None):
        self.parent = parent

    def ask_name(self, title: str, label: str) -> str | None:
        text, ok = QInputDialog.getText(self.parent, title, label)
        return text if ok else None

    def choose_color(self, colors):
        names = [c.name for c in colors]
        if not names:
            return None
        name, ok = QInputDialog.getItem(self.parent, "Excluir cor", "Qual cor excluir?",
                                        names, 0, False)
        return colors[names.index(name)].id if ok else None

    def confirm_delete_color(self, name: str, stock: int, future: int) -> bool:
        text = f"Excluir a cor \"{name}\"?"
        if stock or future:
            text += (f"\n\nEla tem {stock} camiseta(s) em estoque e {future} no futuro. "
                     "Esses números serão descartados (ficam registrados no histórico).")
        text += "\n\nVocê pode cadastrar a cor de novo depois."
        answer = QMessageBox.question(self.parent, "Excluir cor", text)
        return answer == QMessageBox.StandardButton.Yes

    def info(self, title: str, text: str) -> None:
        QMessageBox.information(self.parent, title, text)

    def warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self.parent, title, text)

    def bulk(self, colors, sizes, preview):
        dialog = BulkAddDialog(colors, sizes, preview, self.parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.request()

    def import_notice(self, notice) -> NoticeChoice:
        dialog = ImportNoticeDialog(notice, self.parent)
        dialog.exec()
        return dialog.choice

    def validate(self, lines, colors, sizes):
        dialog = ValidationDialog(lines, colors, sizes, self.parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.decisions()

    def confirm_finalize(self, summary) -> bool:
        return FinalizeDialog(summary, self.parent).exec() == QDialog.DialogCode.Accepted

    def show_history(self, movements, imports) -> None:
        StockHistoryDialog(movements, imports, self.parent).exec()

    def edit_aliases(self, colors, sizes, aliases):
        dialog = AliasesDialog(colors, sizes, aliases, self.parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.rows()
