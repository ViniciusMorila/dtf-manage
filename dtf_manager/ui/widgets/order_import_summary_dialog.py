from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout

from dtf_manager.models.imported_order import ImportedOrder


class OrderImportSummaryDialog(QDialog):
    def __init__(self, orders: list[ImportedOrder], parent=None):
        super().__init__(parent)
        self.setObjectName("orderImportSummaryDialog")
        self.setWindowTitle("Pedidos importados")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)
        title = QLabel("PEDIDOS IMPORTADOS")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        items = [item for order in orders for item in order.items]
        grid = QGridLayout()
        for row, (name, value) in enumerate((
            ("Pedidos", len(orders)),
            ("Itens", len(items)),
            ("Quantidade de produtos", sum(item.product_quantity for item in items)),
        )):
            label = QLabel(name)
            label.setObjectName("muted")
            metric = QLabel(str(value))
            metric.setObjectName("metricValue")
            metric.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(label, row, 0)
            grid.addWidget(metric, row, 1)
        layout.addLayout(grid)
        continue_button = QPushButton("CONTINUAR")
        continue_button.setObjectName("primaryButton")
        continue_button.clicked.connect(self.accept)
        layout.addWidget(continue_button)
