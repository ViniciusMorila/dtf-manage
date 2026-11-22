from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dtf_manager.state.order_import_state import OrderImportState
from dtf_manager.state.order_selectors import ItemLinkFilter, filter_order_items, get_import_metrics
from dtf_manager.ui.widgets.order_items_table import OrderItemsTable
from dtf_manager.services.print_plan_service import can_build_print_plan


ACTION_BLOCK_WIDTH = 480


class OrdersDashboard(QWidget):
    back_requested = Signal()
    import_requested = Signal()
    automatic_link_requested = Signal()
    manual_link_requested = Signal()
    item_edit_requested = Signal(str)
    build_order_requested = Signal()

    def __init__(self, state: OrderImportState, parent=None):
        super().__init__(parent)
        self.setObjectName("ordersDashboard")
        self._state = state
        self._active_filter = ItemLinkFilter.ALL
        self._build_ui()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self._search_timer.start())
        self._state.changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        header = QHBoxLayout()
        back = QPushButton("← VOLTAR")
        back.clicked.connect(self.back_requested)
        header.addWidget(back)
        heading = QVBoxLayout()
        title = QLabel("PEDIDOS IMPORTADOS")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("Revise os produtos e vincule as artes antes de montar o rolo DTF.")
        subtitle.setObjectName("muted")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addLayout(heading)
        header.addStretch()
        layout.addLayout(header)

        cards = QHBoxLayout()
        self.metric_values: dict[str, QLabel] = {}
        for name in ("PEDIDOS", "ITENS", "VINCULADOS", "NÃO VINCULADOS"):
            card = QFrame()
            card.setObjectName("orderMetricCard")
            card_layout = QVBoxLayout(card)
            label = QLabel(name)
            label.setObjectName("eyebrow")
            value = QLabel("0")
            value.setObjectName("linkedMetricValue" if name == "VINCULADOS" else "unlinkedMetricValue" if name == "NÃO VINCULADOS" else "metricValue")
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            self.metric_values[name] = value
            cards.addWidget(card, 1)
        layout.addLayout(cards)

        progress_card = QFrame()
        progress_card.setObjectName("summary")
        progress_layout = QGridLayout(progress_card)
        progress_layout.addWidget(QLabel("Vinculação"), 0, 0)
        self.progress_text = QLabel("0 de 0 itens")
        self.progress_text.setObjectName("muted")
        progress_layout.addWidget(self.progress_text, 0, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        progress_layout.addWidget(self.progress, 1, 0, 1, 2)
        layout.addWidget(progress_card)

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar pedido, SKU ou produto...")
        self.search.setAccessibleName("Buscar produtos importados")
        controls.addWidget(self.search, 1)
        self.filter_group = QButtonGroup(self)
        for link_filter, label in ((ItemLinkFilter.ALL, "TODOS"), (ItemLinkFilter.LINKED, "VINCULADOS"), (ItemLinkFilter.UNLINKED, "NÃO VINCULADOS")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("filter", link_filter.value)
            button.clicked.connect(lambda checked, value=link_filter: self._set_filter(value))
            self.filter_group.addButton(button)
            controls.addWidget(button)
            if link_filter == ItemLinkFilter.ALL:
                button.setChecked(True)
        layout.addLayout(controls)
        self.table = OrderItemsTable()
        self.table.item_activated.connect(self.item_edit_requested)
        layout.addWidget(self.table, 1)
        self.empty_message = QLabel("Nenhum pedido importado.")
        self.empty_message.setObjectName("emptyState")
        self.empty_message.setWordWrap(True)
        layout.addWidget(self.empty_message, 1)
        self.empty_import = QPushButton("IMPORTAR PEDIDO")
        self.empty_import.setObjectName("primaryButton")
        self.empty_import.clicked.connect(self.import_requested)
        layout.addWidget(self.empty_import)
        self.build_hint = QLabel("Vincule todos os produtos para montar o pedido.")
        self.build_hint.setObjectName("muted")
        self.build_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.build_hint)
        self.automatic_link_button = QPushButton("VINCULAR AUTOMATICAMENTE")
        self.automatic_link_button.setObjectName("primaryButton")
        self.automatic_link_button.setToolTip(
            "Selecionar a pasta e vincular artes por memória e correspondências seguras.")
        self.automatic_link_button.clicked.connect(self.automatic_link_requested)
        self.manual_link_button = QPushButton("VINCULAR MANUALMENTE")
        self.manual_link_button.setObjectName("primaryButton")
        self.manual_link_button.clicked.connect(
            lambda: self.manual_link_requested.emit()
        )
        self.build_order_button = QPushButton("MONTAR PEDIDO")
        self.build_order_button.setObjectName("exportButton")
        self.build_order_button.clicked.connect(
            lambda: self.build_order_requested.emit()
        )
        # Bottom block: automatic (left) + manual (right); MONTAR PEDIDO below, as wide as the pair.
        for button in (self.automatic_link_button, self.manual_link_button, self.build_order_button):
            button.setProperty("pill", True)
        self.action_block = QWidget()
        self.action_block.setFixedWidth(ACTION_BLOCK_WIDTH)
        block = QGridLayout(self.action_block)
        block.setContentsMargins(0, 0, 0, 0)
        block.setHorizontalSpacing(10)
        block.setVerticalSpacing(10)
        block.addWidget(self.automatic_link_button, 0, 0)
        block.addWidget(self.manual_link_button, 0, 1)
        block.addWidget(self.build_order_button, 1, 0, 1, 2)
        block_row = QHBoxLayout()
        block_row.addStretch()
        block_row.addWidget(self.action_block)
        block_row.addStretch()
        layout.addLayout(block_row)

    def _set_filter(self, link_filter: ItemLinkFilter) -> None:
        self._active_filter = link_filter
        self.refresh()

    def refresh(self) -> None:
        orders = self._state.imported_orders
        items = self._state.all_items
        metrics = get_import_metrics(orders)
        self.metric_values["PEDIDOS"].setText(str(metrics.order_count))
        self.metric_values["ITENS"].setText(str(metrics.item_count))
        self.metric_values["VINCULADOS"].setText(str(metrics.linked_count))
        self.metric_values["NÃO VINCULADOS"].setText(str(metrics.unlinked_count))
        self.progress_text.setText(f"{metrics.linked_count} de {metrics.item_count} itens")
        self.progress.setValue(round(metrics.progress_percent))
        counts = {
            ItemLinkFilter.ALL.value: metrics.item_count,
            ItemLinkFilter.LINKED.value: metrics.linked_count,
            ItemLinkFilter.UNLINKED.value: metrics.unlinked_count,
        }
        for button in self.filter_group.buttons():
            name = str(button.property("filter"))
            label = "NÃO VINCULADOS" if name == ItemLinkFilter.UNLINKED.value else name.upper()
            button.setText(f"{label} ({counts[name]})")
        filtered = filter_order_items(items, self._active_filter, self.search.text())
        self.table.set_items(filtered)
        has_orders = bool(items)
        self.table.setVisible(has_orders and bool(filtered))
        self.empty_message.setVisible(not filtered)
        self.empty_import.setVisible(not has_orders)
        self.manual_link_button.setVisible(has_orders)
        self.manual_link_button.setEnabled(metrics.unlinked_count > 0)
        ready = can_build_print_plan(orders)
        has_linked = metrics.linked_count > 0
        self.build_order_button.setEnabled(has_linked)
        if ready:
            self.build_hint.setText("✓ TODOS OS PRODUTOS VINCULADOS")
        elif has_linked:
            self.build_hint.setText(
                f"Montar agora somente com os {metrics.linked_count} produtos vinculados."
            )
        elif metrics.unlinked_count == 1:
            self.build_hint.setText("Falta 1 produto para vincular.")
        elif metrics.unlinked_count > 1:
            self.build_hint.setText(f"Faltam {metrics.unlinked_count} produtos para vincular.")
        else:
            self.build_hint.setText("Revise os vínculos antes de montar o pedido.")
        if not has_orders:
            self.empty_message.setText("Nenhum pedido importado.")
        else:
            self.empty_message.setText("Nenhum produto encontrado.")

    def set_auto_linking(self, linking: bool) -> None:
        self.automatic_link_button.setEnabled(not linking)
        self.automatic_link_button.setText(
            "ANALISANDO ARTES..." if linking else "VINCULAR AUTOMATICAMENTE"
        )

    def set_building_order(self, building: bool, text: str = "Preparando pedido...") -> None:
        self.build_order_button.setEnabled(not building)
        self.build_order_button.setText(text if building else "MONTAR PEDIDO")
