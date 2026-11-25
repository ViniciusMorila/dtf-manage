"""Dialog with the history of exported documents (date and weekday, length used, project value)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

HEADERS = ("DIA DA SEMANA", "DATA E HORA", "DOCUMENTO", "COMPRIMENTO USADO", "VALOR DO PROJETO", "")
TRASH_COLUMN = len(HEADERS) - 1
TRASH_WIDTH = 48


def format_number(value: float) -> str:
    return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


class ExportHistoryDialog(QDialog):
    def __init__(self, records, parent=None, clear_callback=None, remove_callback=None):
        """`clear_callback()` deletes the stored history, `remove_callback(record_id)` one record;
        both may raise OSError."""
        super().__init__(parent)
        self._clear_callback = clear_callback
        self._remove_callback = remove_callback
        self._records = []
        self.setObjectName("exportHistoryDialog")
        self.setWindowTitle("Histórico de exportações")
        self.resize(860, 480)
        layout = QVBoxLayout(self)
        title = QLabel("HISTÓRICO DE EXPORTAÇÕES")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.empty_label = QLabel("Nenhuma exportação registrada ainda. "
                                  "Cada vez que você exportar o documento, o resumo aparece aqui.")
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setObjectName("exportHistoryTable")
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(TRASH_COLUMN, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(TRASH_COLUMN, TRASH_WIDTH)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table, 1)
        self.totals_label = QLabel("")
        self.totals_label.setObjectName("muted")
        layout.addWidget(self.totals_label)
        buttons = QHBoxLayout()
        self.clear_button = QPushButton("LIMPAR HISTÓRICO")
        self.clear_button.clicked.connect(self.clear_history)
        self.clear_button.setVisible(clear_callback is not None)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        close = QPushButton("FECHAR")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.set_records(records)

    def clear_history(self) -> bool:
        """Asks first; the history is only emptied when the deletion really worked."""
        if self._clear_callback is None or not self._records:
            return False
        answer = QMessageBox.question(
            self, "Limpar histórico",
            "Apagar todo o histórico de exportações?\n\nIsso não apaga nenhum arquivo exportado, "
            "só o resumo desta lista, e não pode ser desfeito.")
        if answer != QMessageBox.StandardButton.Yes:
            return False
        try:
            self._clear_callback()
        except OSError as error:
            QMessageBox.warning(self, "Limpar histórico", str(error))
            return False
        self.set_records([])
        return True

    def record_rows(self) -> int:
        """Rows holding a record (the table has one more row: the total)."""
        return len(self._records)

    def _show_context_menu(self, position) -> None:
        """Right click on a line: offers to delete it (never on the total row)."""
        row = self.table.rowAt(position.y())
        if self._remove_callback is None or not 0 <= row < len(self._records):
            return
        self.table.selectRow(row)
        menu = QMenu(self.table)
        action = menu.addAction("Excluir esta linha")
        if menu.exec(self.table.viewport().mapToGlobal(position)) is action:
            self.delete_row(row)

    def delete_row(self, row: int) -> bool:
        """Removes one line after asking; the table only changes when it really worked."""
        if self._remove_callback is None or not 0 <= row < len(self._records):
            return False
        record = self._records[row]
        answer = QMessageBox.question(
            self, "Excluir linha",
            f"Excluir esta exportação do histórico?\n\n{record.name} · {record.moment:%d/%m/%Y %H:%M} · "
            f"{format_number(record.used_length_m)} m\n\nO arquivo exportado não é apagado.")
        if answer != QMessageBox.StandardButton.Yes:
            return False
        try:
            self._remove_callback(record.id)
        except OSError as error:
            QMessageBox.warning(self, "Excluir linha", str(error))
            return False
        self.set_records([r for r in self._records if r.id != record.id])
        return True

    def _trash_button(self, record_id: str) -> QPushButton:
        button = QPushButton("🗑")
        button.setObjectName("trashButton")
        button.setToolTip("Excluir esta linha")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFlat(True)
        button.setFixedSize(TRASH_WIDTH - 12, 28)
        button.clicked.connect(lambda: self.delete_row(self._row_of(record_id)))
        return button

    def _row_of(self, record_id: str) -> int:
        return next((row for row, record in enumerate(self._records) if record.id == record_id), -1)

    def set_records(self, records) -> None:
        records = list(records)
        self._records = records
        self.table.clearSelection()
        self.table.setRowCount(0)
        self.table.setRowCount(len(records) + 1 if records else 0)      # + the total row
        for row, record in enumerate(records):
            moment = record.moment
            cells = (record.weekday.capitalize(), f"{moment:%d/%m/%Y %H:%M}",
                     record.name + (f" ({record.parts} partes)" if record.parts > 1 else ""),
                     f"{format_number(record.used_length_m)} m", f"R$ {format_number(record.project_value)}")
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column >= 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
            if self._remove_callback is not None:
                self.table.setCellWidget(row, TRASH_COLUMN, self._trash_button(record.id))
        self.clear_button.setEnabled(bool(records))
        self.empty_label.setVisible(not records)
        self.table.setVisible(bool(records))
        total_length = sum(record.used_length_m for record in records)
        total_value = sum(record.project_value for record in records)
        self.totals_label.setText(
            f"{len(records)} exportação(ões) · {format_number(total_length)} m · R$ {format_number(total_value)}"
            if records else "")
        if records:
            row = len(records)
            bold = self.table.font()
            bold.setBold(True)
            for column, text in enumerate(("", "", "TOTAL", f"{format_number(total_length)} m",
                                            f"R$ {format_number(total_value)}", "")):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)                 # not selectable, never deleted
                item.setFont(bold)
                item.setBackground(QBrush(QColor("#2a1a35")))
                if 3 <= column <= 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
