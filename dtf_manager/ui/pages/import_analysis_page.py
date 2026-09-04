from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dtf_manager.models.automatic_link import AutomaticLinkOutcome
from dtf_manager.models.import_history_analysis import ImportHistoryAnalysis


class ImportAnalysisPage(QWidget):
    cancelled = Signal()
    confirmed = Signal(object)
    automatic_link_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("importAnalysisPage")
        self._analysis = ImportHistoryAnalysis()
        self._auto_link_results = ()
        self._automatic_link_completed = False
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        header = QHBoxLayout()
        back = QPushButton("← CANCELAR IMPORTAÇÃO")
        back.clicked.connect(self.cancelled)
        header.addWidget(back)
        title = QLabel("ANÁLISE DA IMPORTAÇÃO")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        metrics = QHBoxLayout()
        self.metrics = {}
        for name in ("TOTAL IMPORTADO", "NOVOS", "JÁ PROCESSADOS", "ALTERADOS"):
            self.metrics[name] = self._add_metric_card(metrics, name, "metricValue")
        root.addLayout(metrics)
        instructions = QLabel(
            "Use a Pasta das artes definida nas configurações para localizar e vincular "
            "automaticamente as estampas dos novos pedidos."
        )
        instructions.setObjectName("muted")
        instructions.setWordWrap(True)
        root.addWidget(instructions)

        action_row = QHBoxLayout()
        self.folder_label = QLabel("Pasta das artes: não configurada")
        self.folder_label.setObjectName("muted")
        self.folder_label.setWordWrap(True)
        action_row.addWidget(self.folder_label, 1)
        self.automatic_link_button = QPushButton("VINCULAR AUTOMATICAMENTE")
        self.automatic_link_button.setObjectName("primaryButton")
        self.automatic_link_button.clicked.connect(self.automatic_link_requested)
        action_row.addWidget(self.automatic_link_button)
        root.addLayout(action_row)
        self.link_status = QLabel("Clique em vincular automaticamente para analisar as estampas.")
        self.link_status.setObjectName("muted")
        self.link_status.setWordWrap(True)
        root.addWidget(self.link_status)

        link_metrics = QHBoxLayout()
        self.linked_orders_value = self._add_metric_card(link_metrics, "PEDIDOS VINCULADOS", "linkedMetricValue")
        self.unlinked_orders_value = self._add_metric_card(link_metrics, "PEDIDOS NÃO VINCULADOS", "unlinkedMetricValue")
        root.addLayout(link_metrics)
        root.addStretch()
        footer = QHBoxLayout()
        footer.addStretch()
        self.continue_button = QPushButton("CONTINUAR COM 0 PEDIDOS")
        self.continue_button.setObjectName("primaryButton")
        self.continue_button.clicked.connect(self._confirm)
        footer.addWidget(self.continue_button)
        root.addLayout(footer)

    @staticmethod
    def _add_metric_card(layout, name, value_style):
        card = QFrame()
        card.setObjectName("orderMetricCard")
        box = QVBoxLayout(card)
        caption = QLabel(name)
        caption.setObjectName("eyebrow")
        value = QLabel("0")
        value.setObjectName(value_style)
        box.addWidget(caption)
        box.addWidget(value)
        layout.addWidget(card, 1)
        return value

    @property
    def selected_orders(self):
        return self._analysis.selected_orders

    @property
    def auto_link_results(self):
        return self._auto_link_results

    @property
    def automatic_link_completed(self):
        return self._automatic_link_completed

    def set_analysis(self, analysis, artwork_folder=None):
        self._analysis = analysis
        self._auto_link_results = ()
        self._automatic_link_completed = False
        self.metrics["TOTAL IMPORTADO"].setText(str(analysis.total_orders))
        self.metrics["NOVOS"].setText(str(len(analysis.new_orders)))
        self.metrics["JÁ PROCESSADOS"].setText(str(len(analysis.already_processed_orders)))
        self.metrics["ALTERADOS"].setText(str(len(analysis.changed_orders)))
        self.folder_label.setText(f"Pasta das artes: {artwork_folder}" if artwork_folder else "Pasta das artes: não configurada")
        self.automatic_link_button.setEnabled(bool(artwork_folder and analysis.selected_orders))
        self.automatic_link_button.setText("VINCULAR AUTOMATICAMENTE")
        self.linked_orders_value.setText("0")
        self.unlinked_orders_value.setText(str(len(analysis.selected_orders)))
        self.link_status.setText("Clique em vincular automaticamente para analisar as estampas.")
        self._update_continue()

    def apply_automatic_link(self, outcome: AutomaticLinkOutcome):
        updated = {order.id: order for order in outcome.orders}
        for analyzed in self._analysis.orders:
            if analyzed.order.id in updated:
                analyzed.order = updated[analyzed.order.id]
        self._auto_link_results = outcome.results
        self._automatic_link_completed = True
        linked, unlinked = self._order_link_counts()
        self.linked_orders_value.setText(str(linked))
        self.unlinked_orders_value.setText(str(unlinked))
        self.link_status.setText(f"Vinculação concluída: {linked} pedido(s) vinculado(s) e {unlinked} pedido(s) ainda precisam de vínculo.")
        self._update_continue()

    def set_auto_linking(self, linking):
        self.automatic_link_button.setEnabled(not linking)
        self.automatic_link_button.setText("ANALISANDO ARTES..." if linking else "VINCULAR NOVAMENTE")

    def _order_link_counts(self):
        orders = self._analysis.selected_orders
        linked = sum(bool(order.items) and all(item.link_status == "linked" for item in order.items) for order in orders)
        return linked, len(orders) - linked

    def _update_continue(self):
        count = self._order_link_counts()[1] if self._automatic_link_completed else len(self._analysis.selected_orders)
        self.continue_button.setText(f"CONTINUAR COM {count} PEDIDOS")
        self.continue_button.setEnabled(bool(self._analysis.selected_orders))

    def _confirm(self):
        if self._analysis.orders:
            self.confirmed.emit([analyzed.order for analyzed in self._analysis.orders])
