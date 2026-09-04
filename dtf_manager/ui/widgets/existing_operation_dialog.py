from datetime import datetime

from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from dtf_manager.models.active_operation import ActiveProductionOperation


class ExistingOperationDialog(QDialog):
    CONTINUE = "continue"
    RESTART = "restart"
    CANCEL = "cancel"

    def __init__(self, operation: ActiveProductionOperation, parent=None):
        super().__init__(parent)
        self.setObjectName("existingOperationDialog")
        self.setWindowTitle("Operação em andamento")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.choice = self.CANCEL
        root = QVBoxLayout(self)
        title = QLabel("OPERAÇÃO EM ANDAMENTO")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        text = QLabel(
            "Estes pedidos já possuem uma preparação em andamento.\n\n"
            "Deseja continuar de onde parou ou reiniciar a preparação?"
        )
        text.setWordWrap(True)
        root.addWidget(text)
        card = QFrame()
        card.setObjectName("summary")
        box = QVBoxLayout(card)
        meta = operation.metadata
        updated = datetime.fromisoformat(operation.updated_at.replace("Z", "+00:00")).astimezone()
        stage_names = {
            "orders_dashboard": "Pedidos importados",
            "automatic_linking": "Vinculação automática",
            "manual_linking": "Vinculação manual",
            "production_review": "Conferência de produção",
            "ready_to_mount": "Pronto para montar",
        }
        details = QLabel(
            f"Pedidos: {meta.order_count}\nItens: {meta.item_count}\n"
            f"Vinculados: {meta.linked_count}\nNão vinculados: {meta.unlinked_count}\n\n"
            f"Última atualização: {updated:%d/%m/%Y %H:%M}\n"
            f"Etapa atual: {stage_names.get(operation.workflow_stage, 'Pedidos importados')}"
        )
        box.addWidget(details)
        root.addWidget(card)
        buttons = QHBoxLayout()
        continue_button = QPushButton("CONTINUAR")
        continue_button.setObjectName("primaryButton")
        continue_button.clicked.connect(lambda: self._finish(self.CONTINUE))
        restart_button = QPushButton("REINICIAR")
        restart_button.setObjectName("removeButton")
        restart_button.clicked.connect(lambda: self._finish(self.RESTART))
        cancel_button = QPushButton("CANCELAR")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(continue_button)
        buttons.addWidget(restart_button)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()

