from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout


class SummaryWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("summary")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        title = QLabel("RESUMO DO PROJETO")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        values = [
            ("Artes únicas", "0"),
            ("Total de cópias", "0"),
            ("Comprimento usado", "0,00 m"),
            ("Valor do projeto", "R$ 0,00"),
        ]
        self._value_labels = {}
        for row, (label, value) in enumerate(values):
            name = QLabel(label)
            name.setObjectName("muted")
            result = QLabel(value)
            result.setObjectName("metricValue")
            result.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(name, row, 0)
            grid.addWidget(result, row, 1)
            self._value_labels[label] = result
        layout.addLayout(grid)

    def update_values(self, unique_artworks: int, total_copies: int, used_meters: float, cost_per_meter: float) -> None:
        total_cost = used_meters * cost_per_meter
        values = {
            "Artes únicas": str(unique_artworks),
            "Total de cópias": str(total_copies),
            "Comprimento usado": f"{self._format_number(used_meters)} m",
            "Valor do projeto": f"R$ {self._format_number(total_cost)}",
        }
        for label, value in values.items():
            self._value_labels[label].setText(value)

    @staticmethod
    def _format_number(value: float) -> str:
        return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
