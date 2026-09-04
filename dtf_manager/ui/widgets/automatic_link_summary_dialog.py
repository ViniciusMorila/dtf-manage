from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout

from dtf_manager.models.automatic_link import AutomaticLinkOutcome


class AutomaticLinkSummaryDialog(QDialog):
    def __init__(self, outcome: AutomaticLinkOutcome, parent=None):
        super().__init__(parent)
        self.setObjectName("automaticLinkSummaryDialog")
        self.setWindowTitle("Vinculação concluída")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)
        title = QLabel("VINCULAÇÃO CONCLUÍDA")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        grid = QGridLayout()
        for row, (name, value) in enumerate((
            ("Vinculados pela memória", outcome.memory_linked_count),
            ("Vinculados automaticamente", outcome.linked_count),
            ("Não encontrados", outcome.not_found_count),
            ("Precisam de conferência", outcome.ambiguous_count),
        )):
            label = QLabel(name)
            label.setObjectName("muted")
            metric = QLabel(str(value))
            metric.setObjectName("metricValue")
            metric.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(label, row, 0)
            grid.addWidget(metric, row, 1)
        layout.addLayout(grid)
        close = QPushButton("FECHAR")
        close.setObjectName("primaryButton")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
