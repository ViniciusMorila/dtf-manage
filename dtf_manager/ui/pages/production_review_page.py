from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from dtf_manager.models.print_plan import DTFOrderPlan
from dtf_manager.models.production_validation import ProductionIssue, ProductionValidationResult
from dtf_manager.services.print_plan_service import PrintPlanValidationError, build_dtf_print_plan
from dtf_manager.services.production_validation_service import validate_production_plan
from dtf_manager.state.order_import_state import OrderImportState


class ProductionReviewPage(QWidget):
    back_requested = Signal()
    correction_requested = Signal(str)
    mount_requested = Signal(object)

    def __init__(self, state: OrderImportState, parent=None):
        super().__init__(parent)
        self.setObjectName("productionReviewPage")
        self._state = state
        self._review_orders = state.imported_orders
        self._plan: DTFOrderPlan | None = None
        self._result = ProductionValidationResult()
        self._view_mode = "arts"
        self._preview_cache: dict[str, QIcon] = {}
        self._issues_by_id: dict[str, ProductionIssue] = {}
        self._build_ui()
        self._state.changed.connect(self._mark_stale)

    @property
    def validation_result(self) -> ProductionValidationResult:
        return self._result

    @property
    def reviewed_orders(self):
        return self._review_orders

    def review_orders(self, orders) -> None:
        self._review_orders = tuple(orders)
        self.revalidate()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        header = QHBoxLayout()
        back = QPushButton("← VOLTAR AOS PEDIDOS")
        back.clicked.connect(self.back_requested)
        header.addWidget(back)
        title = QLabel("CONFERÊNCIA DE PRODUÇÃO")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        metrics = QHBoxLayout()
        self.metric_values: dict[str, QLabel] = {}
        for name in ("PEDIDOS", "PRODUTOS", "ARTES DIFERENTES", "TOTAL DE ESTAMPAS"):
            card = QFrame()
            card.setObjectName("orderMetricCard")
            layout = QVBoxLayout(card)
            caption = QLabel(name)
            caption.setObjectName("eyebrow")
            value = QLabel("0")
            value.setObjectName("metricValue")
            layout.addWidget(caption)
            layout.addWidget(value)
            metrics.addWidget(card, 1)
            self.metric_values[name] = value
        root.addLayout(metrics)
        self.status_card = QFrame()
        self.status_card.setObjectName("productionStatusCard")
        status_layout = QHBoxLayout(self.status_card)
        self.status_label = QLabel("CONFERINDO PEDIDO...")
        self.status_label.setObjectName("productionStatus")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        self.status_detail = QLabel("")
        self.status_detail.setObjectName("muted")
        status_layout.addWidget(self.status_detail)
        root.addWidget(self.status_card)

        controls = QHBoxLayout()
        self.arts_button = QPushButton("POR ARTES")
        self.orders_button = QPushButton("POR PEDIDOS")
        self.arts_button.clicked.connect(lambda: self._set_mode("arts"))
        self.orders_button.clicked.connect(lambda: self._set_mode("orders"))
        controls.addWidget(self.arts_button)
        controls.addWidget(self.orders_button)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar pedido, SKU, produto ou arte...")
        self.search.textChanged.connect(self._rebuild_content)
        controls.addWidget(self.search, 1)
        self.only_problems = QCheckBox("MOSTRAR SOMENTE COM PROBLEMAS")
        self.only_problems.toggled.connect(self._rebuild_content)
        controls.addWidget(self.only_problems)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        issues_card = QFrame()
        issues_card.setObjectName("manualColumn")
        issues_layout = QVBoxLayout(issues_card)
        issues_title = QLabel("VERIFICAÇÕES")
        issues_title.setObjectName("panelTitle")
        issues_layout.addWidget(issues_title)
        self.issues_tree = QTreeWidget()
        self.issues_tree.setObjectName("productionIssues")
        self.issues_tree.setHeaderHidden(True)
        self.issues_tree.setWordWrap(True)
        self.issues_tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.issues_tree.itemDoubleClicked.connect(lambda *_: self._correct_selected())
        issues_layout.addWidget(self.issues_tree, 1)
        splitter.addWidget(issues_card)
        content_card = QFrame()
        content_card.setObjectName("manualColumn")
        content_layout = QVBoxLayout(content_card)
        self.content_title = QLabel("ARTES DO LOTE")
        self.content_title.setObjectName("panelTitle")
        content_layout.addWidget(self.content_title)
        self.content_tree = QTreeWidget()
        self.content_tree.setObjectName("productionContent")
        self.content_tree.setIconSize(self.content_tree.iconSize().expandedTo(self.content_tree.iconSize() * 3))
        content_layout.addWidget(self.content_tree, 1)
        splitter.addWidget(content_card)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes((760, 570))
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        self.mount_button = QPushButton("MONTAR ROLO")
        self.mount_button.setObjectName("primaryButton")
        self.mount_button.clicked.connect(self._mount)
        footer.addWidget(self.mount_button)
        root.addLayout(footer)

    def revalidate(self) -> None:
        self.status_label.setText("VALIDANDO ARTES...")
        self.repaint()
        try:
            self._plan = build_dtf_print_plan(self._review_orders, validate_files=False)
        except PrintPlanValidationError:
            self._plan = None
        try:
            self._result = validate_production_plan(self._review_orders, self._plan)
        except Exception:
            self._plan = None
            self._result = ProductionValidationResult(errors=(ProductionIssue(
                id="validation-failure", severity="error", code="VALIDATION_FAILURE",
                message="Não foi possível concluir a conferência do pedido.",
            ),))
        self._refresh()

    def _mark_stale(self) -> None:
        self._plan = None
        self.mount_button.setEnabled(False)
        self.status_label.setText("CONFERÊNCIA DESATUALIZADA — REVALIDANDO AO RETORNAR")

    def _refresh(self) -> None:
        plan = self._plan
        values = {
            "PEDIDOS": plan.source_order_count if plan else len(self._review_orders),
            "PRODUTOS": plan.source_item_count if plan else sum(len(order.items) for order in self._review_orders),
            "ARTES DIFERENTES": len(plan.arts) if plan else 0,
            "TOTAL DE ESTAMPAS": plan.total_print_copies if plan else 0,
        }
        for name, value in values.items():
            self.metric_values[name].setText(str(value))
        status = self._result.status
        self.status_label.setText({"ready": "✓ PRONTO PARA PRODUÇÃO", "warning": "⚠ ATENÇÃO NECESSÁRIA", "error": "✕ ERROS ENCONTRADOS"}[status])
        self.status_card.setProperty("status", status)
        self.status_card.style().unpolish(self.status_card)
        self.status_card.style().polish(self.status_card)
        self.status_detail.setText(f"{len(self._result.errors)} erros · {len(self._result.warnings)} avisos")
        # Keep the action available so clicking it can explain validation errors.
        self.mount_button.setEnabled(True)
        self._rebuild_issues()
        self._rebuild_content()
        self._set_mode(self._view_mode, rebuild=False)

    def _rebuild_issues(self) -> None:
        self.issues_tree.clear()
        self._issues_by_id = {issue.id: issue for issue in self._result.all_issues}
        groups = (("ERROS", self._result.errors, "✕"), ("AVISOS", self._result.warnings, "⚠"), ("INFORMAÇÕES", self._result.info, "•"))
        any_issue = False
        for label, issues, icon in groups:
            if not issues:
                continue
            any_issue = True
            parent = QTreeWidgetItem([f"{label} ({len(issues)})"])
            self.issues_tree.addTopLevelItem(parent)
            for issue in issues:
                detail = issue.message
                if issue.product_name:
                    detail += f"\nProduto: {issue.product_name}"
                if issue.art_name:
                    detail += f"\nArte: {issue.art_name}"
                child = QTreeWidgetItem([f"{icon} {detail}"])
                child.setData(0, Qt.ItemDataRole.UserRole, issue.id)
                parent.addChild(child)
            parent.setExpanded(True)
        if not any_issue:
            self.issues_tree.addTopLevelItem(QTreeWidgetItem(["✓ Nenhum problema encontrado."]))

    def _problem_ids(self) -> tuple[set[str], set[str]]:
        item_ids = {issue.item_id for issue in self._result.errors + self._result.warnings if issue.item_id}
        references = {str(Path(issue.file_reference).resolve()).casefold() for issue in self._result.errors + self._result.warnings if issue.file_reference}
        return item_ids, references

    def _rebuild_content(self) -> None:
        if not hasattr(self, "content_tree"):
            return
        self.content_tree.clear()
        query = self.search.text().strip().casefold()
        problem_items, problem_refs = self._problem_ids()
        if self._view_mode == "arts":
            self._build_art_view(query, problem_items, problem_refs)
        else:
            self._build_order_view(query, problem_items)

    def _review_items(self):
        return tuple(item for order in self._review_orders for item in order.items)

    def _build_art_view(self, query: str, problem_items: set[str], problem_refs: set[str]) -> None:
        self.content_tree.setHeaderLabels(("Arte", "Estampas", "Produtos", "Pedidos"))
        for art in self._plan.arts if self._plan else ():
            reference = str(Path(art.file_reference).resolve()).casefold()
            source_items = set(art.source_item_ids)
            if self.only_problems.isChecked() and reference not in problem_refs and not source_items.intersection(problem_items):
                continue
            searchable = " ".join((art.file_name, *art.source_order_numbers, *(
                f"{item.product_name} {item.sku}" for item in self._review_items() if item.id in source_items
            ))).casefold()
            if query and query not in searchable:
                continue
            row = QTreeWidgetItem((art.file_name, str(art.total_copies), str(len(source_items)), str(len(set(art.source_order_numbers)))))
            row.setToolTip(0, art.file_reference)
            row.setIcon(0, self._preview_icon(art.file_reference))
            self.content_tree.addTopLevelItem(row)
            for item in self._review_items():
                if item.id not in source_items:
                    continue
                linked = next((linked for linked in item.linked_arts if linked.file_reference and str(Path(linked.file_reference).resolve()).casefold() == reference), None)
                if linked:
                    total = item.product_quantity * linked.copies_per_product
                    child = QTreeWidgetItem((f"Pedido {item.platform_order_number} · {item.product_name}", f"{item.product_quantity} × {linked.copies_per_product} = {total}", "", ""))
                    row.addChild(child)

    def _build_order_view(self, query: str, problem_items: set[str]) -> None:
        self.content_tree.setHeaderLabels(("Pedido / Produto / Arte", "Quantidade", "Origem", ""))
        for order in self._review_orders:
            visible_items = []
            for item in order.items:
                searchable = " ".join((item.platform_order_number, item.sku, item.product_name, *(art.file_name for art in item.linked_arts))).casefold()
                if query and query not in searchable:
                    continue
                if self.only_problems.isChecked() and item.id not in problem_items:
                    continue
                visible_items.append(item)
            if not visible_items:
                continue
            order_row = QTreeWidgetItem((f"Pedido {order.platform_order_number}", "", "", ""))
            self.content_tree.addTopLevelItem(order_row)
            for item in visible_items:
                item_row = QTreeWidgetItem((item.product_name, f"Qtd produto: {item.product_quantity}", "", ""))
                order_row.addChild(item_row)
                for art in item.linked_arts:
                    total = item.product_quantity * art.copies_per_product if type(item.product_quantity) is int and type(art.copies_per_product) is int else "—"
                    origin = {"manual": "Manual", "automatic": "Automático", "memory": "Memória"}.get(art.link_method, art.link_method)
                    art_row = QTreeWidgetItem((art.file_name, f"{item.product_quantity} × {art.copies_per_product} = {total} estampas", origin, ""))
                    art_row.setIcon(0, self._preview_icon(art.file_reference or ""))
                    item_row.addChild(art_row)
            order_row.setExpanded(True)

    def _preview_icon(self, reference: str) -> QIcon:
        key = str(Path(reference).resolve()).casefold() if reference else ""
        if key not in self._preview_cache:
            pixmap = QPixmap(reference)
            self._preview_cache[key] = QIcon(pixmap.scaled(52, 52, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)) if not pixmap.isNull() else QIcon()
        return self._preview_cache[key]

    def _set_mode(self, mode: str, rebuild: bool = True) -> None:
        self._view_mode = mode
        self.content_title.setText("ARTES DO LOTE" if mode == "arts" else "PEDIDOS DO LOTE")
        self.arts_button.setProperty("selected", mode == "arts")
        self.orders_button.setProperty("selected", mode == "orders")
        if rebuild:
            self._rebuild_content()

    def _correct_selected(self) -> None:
        selected = self.issues_tree.currentItem()
        issue = self._issues_by_id.get(selected.data(0, Qt.ItemDataRole.UserRole)) if selected else None
        if issue and issue.item_id and issue.action:
            self.correction_requested.emit(issue.item_id)

    def _mount(self) -> None:
        if not self._result.is_valid or self._plan is None:
            QMessageBox.warning(
                self, "Erros encontrados",
                f"Não foi possível montar o rolo porque existem {len(self._result.errors)} erro(s).\n\n"
                "Confira a caixa VERIFICAÇÕES antes de continuar.",
            )
            return
        self.mount_requested.emit(self._plan)
