from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout,
)

from dtf_manager.models.print_plan import DTFOrderPlan


class PrintPlanConfirmationDialog(QDialog):
    def __init__(self, plan: DTFOrderPlan, parent=None):
        super().__init__(parent)
        self.setObjectName("printPlanConfirmationDialog")
        self.setWindowTitle("Montar pedido")
        self.resize(540, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel("MONTAR PEDIDO")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        grid = QGridLayout()
        metrics = (
            ("Pedidos", plan.source_order_count),
            ("Produtos", plan.source_item_count),
            ("Artes diferentes", len(plan.arts)),
            ("Total de estampas", plan.total_print_copies),
        )
        for row, (name, value) in enumerate(metrics):
            label = QLabel(name)
            label.setObjectName("muted")
            result = QLabel(str(value))
            result.setObjectName("metricValue")
            result.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(label, row, 0)
            grid.addWidget(result, row, 1)
        layout.addLayout(grid)
        arts = QListWidget()
        arts.setObjectName("printPlanList")
        for art in plan.arts:
            item = QListWidgetItem(f"{art.file_name}    × {art.total_copies}")
            item.setToolTip(art.file_name)
            arts.addItem(item)
        layout.addWidget(arts, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        mount = buttons.addButton("MONTAR ROLO", QDialogButtonBox.ButtonRole.AcceptRole)
        mount.setObjectName("primaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
