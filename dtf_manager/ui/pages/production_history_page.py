from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from dtf_manager.services.production_history_repository import ProductionHistoryRepository, ProductionHistoryStorageError
from dtf_manager.services.production_history_service import batch_matches


class ProductionHistoryPage(QWidget):
    back_requested = Signal()

    def __init__(self, repository: ProductionHistoryRepository, parent=None):
        super().__init__(parent); self.setObjectName("productionHistoryPage")
        self.repository = repository; self._visible_batches = []
        root = QVBoxLayout(self); root.setContentsMargins(24, 20, 24, 20)
        header = QHBoxLayout(); back = QPushButton("← VOLTAR"); back.clicked.connect(self._back)
        header.addWidget(back); title = QLabel("HISTÓRICO DE LOTES"); title.setObjectName("sectionTitle"); header.addWidget(title); header.addStretch(); root.addLayout(header)
        self.pages = QStackedWidget(); root.addWidget(self.pages, 1)
        self.pages.addWidget(self._build_list()); self.pages.addWidget(self._build_detail())

    def _build_list(self):
        page = QWidget(); layout = QVBoxLayout(page); controls = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Buscar lote, pedido, SKU, produto ou arte..."); self.search.textChanged.connect(self.refresh); controls.addWidget(self.search, 1)
        self.period = QComboBox(); self.period.addItems(("HOJE", "ÚLTIMOS 7 DIAS", "ÚLTIMOS 30 DIAS", "TODOS")); self.period.setCurrentText("TODOS"); self.period.currentIndexChanged.connect(self.refresh); controls.addWidget(self.period); layout.addLayout(controls)
        metrics = QHBoxLayout(); self.metrics = {}
        for name in ("LOTES", "PEDIDOS", "ESTAMPAS"):
            card=QFrame(); card.setObjectName("orderMetricCard"); box=QVBoxLayout(card); cap=QLabel(name); cap.setObjectName("eyebrow"); val=QLabel("0"); val.setObjectName("metricValue"); box.addWidget(cap); box.addWidget(val); metrics.addWidget(card); self.metrics[name]=val
        layout.addLayout(metrics)
        self.table=QTableWidget(0,7); self.table.setObjectName("historyTable"); self.table.setHorizontalHeaderLabels(("LOTE","DATA","PEDIDOS","PRODUTOS","ARTES","ESTAMPAS","STATUS")); self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.doubleClicked.connect(self._open_selected); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); layout.addWidget(self.table,1)
        actions=QHBoxLayout(); actions.addStretch(); details=QPushButton("VER DETALHES"); details.clicked.connect(self._open_selected); actions.addWidget(details); clear=QPushButton("LIMPAR TODO O HISTÓRICO"); clear.clicked.connect(self._clear); actions.addWidget(clear); layout.addLayout(actions); return page

    def _build_detail(self):
        page=QWidget(); layout=QVBoxLayout(page); top=QHBoxLayout(); self.detail_title=QLabel(); self.detail_title.setObjectName("sectionTitle"); top.addWidget(self.detail_title); top.addStretch(); self.delete_button=QPushButton("EXCLUIR DO HISTÓRICO"); self.delete_button.clicked.connect(self._delete); top.addWidget(self.delete_button); layout.addLayout(top)
        self.detail_meta=QLabel(); self.detail_meta.setObjectName("muted"); layout.addWidget(self.detail_meta)
        self.detail_summary=QLabel(); self.detail_summary.setObjectName("panelTitle"); layout.addWidget(self.detail_summary)
        tabs=QHBoxLayout(); arts=QPushButton("ARTES"); orders=QPushButton("PEDIDOS"); arts.clicked.connect(lambda:self.detail_pages.setCurrentIndex(0)); orders.clicked.connect(lambda:self.detail_pages.setCurrentIndex(1)); tabs.addWidget(arts); tabs.addWidget(orders); tabs.addStretch(); layout.addLayout(tabs)
        self.detail_pages=QStackedWidget(); self.arts_tree=QTreeWidget(); self.arts_tree.setHeaderLabels(("Arte","Total","Produtos","Pedidos / SKUs")); self.orders_tree=QTreeWidget(); self.orders_tree.setHeaderLabels(("Pedido / Produto / Arte","Quantidade","SKU / Variação","Origem")); self.detail_pages.addWidget(self.arts_tree); self.detail_pages.addWidget(self.orders_tree); layout.addWidget(self.detail_pages,1)
        self.roll_info=QLabel(); self.roll_info.setWordWrap(True); layout.addWidget(self.roll_info); self.warning_info=QLabel(); self.warning_info.setWordWrap(True); layout.addWidget(self.warning_info); return page

    def refresh(self):
        now=datetime.now(timezone.utc); days={"HOJE":1,"ÚLTIMOS 7 DIAS":7,"ÚLTIMOS 30 DIAS":30}.get(self.period.currentText())
        batches=[]
        for batch in self.repository.list_all():
            stamp=datetime.fromisoformat((batch.mounted_at or batch.created_at).replace("Z","+00:00"))
            if days and stamp < now-timedelta(days=days): continue
            if batch_matches(batch,self.search.text()): batches.append(batch)
        self._visible_batches=batches; self.table.setRowCount(len(batches))
        for row,b in enumerate(batches):
            date=datetime.fromisoformat((b.mounted_at or b.created_at).replace("Z","+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
            values=(b.batch_number,date,b.summary.order_count,b.summary.item_count,b.summary.unique_art_count,b.summary.total_print_copies,"ROLO MONTADO")
            for col,value in enumerate(values): self.table.setItem(row,col,QTableWidgetItem(str(value)))
        self.metrics["LOTES"].setText(str(len(batches))); self.metrics["PEDIDOS"].setText(str(sum(b.summary.order_count for b in batches))); self.metrics["ESTAMPAS"].setText(str(sum(b.summary.total_print_copies for b in batches)))

    def _open_selected(self):
        row=self.table.currentRow()
        if row<0 or row>=len(self._visible_batches): return
        b=self._visible_batches[row]; self._current_id=b.id; self.detail_title.setText(f"LOTE {b.batch_number} — ROLO MONTADO"); self.detail_meta.setText(datetime.fromisoformat((b.mounted_at or b.created_at).replace("Z","+00:00")).astimezone().strftime("Montado em %d/%m/%Y às %H:%M"))
        s=b.summary; self.detail_summary.setText(f"PEDIDOS {s.order_count}    PRODUTOS {s.item_count}    UNIDADES {s.product_unit_count}    ARTES {s.unique_art_count}    ESTAMPAS {s.total_print_copies}")
        self.arts_tree.clear()
        for art in b.arts: self.arts_tree.addTopLevelItem(QTreeWidgetItem((art.file_name,str(art.total_copies),str(art.source_item_count),", ".join((*art.source_order_numbers,*art.source_skus)))))
        self.orders_tree.clear()
        for order in b.orders:
            order_row=QTreeWidgetItem((f"Pedido {order.platform_order_number}","","","")); self.orders_tree.addTopLevelItem(order_row)
            for item in order.items:
                item_row=QTreeWidgetItem((item.product_name,f"Qtd: {item.product_quantity}",f"{item.sku} · {item.variation_raw}","")); order_row.addChild(item_row)
                for art in item.arts: item_row.addChild(QTreeWidgetItem((art.file_name,f"{item.product_quantity} × {art.copies_per_product} = {art.final_copies} estampas","",art.link_method)))
            order_row.setExpanded(True)
        r=b.roll_settings; values=[]
        if r.film_width_cm is not None: values.append(f"Largura: {r.film_width_cm:g} cm")
        if r.gap_cm is not None: values.append(f"Gap: {r.gap_cm:g} cm")
        if r.dpi is not None: values.append(f"DPI: {r.dpi}")
        if r.automatic_division is not None: values.append(f"Divisão automática: {'Sim' if r.automatic_division else 'Não'}")
        self.roll_info.setText("CONFIGURAÇÕES DO ROLO\n"+" · ".join(values)); warnings=b.validation.warnings; self.warning_info.setText("AVISOS NA MONTAGEM\n"+("\n".join(f"• {w.message}" for w in warnings) if warnings else "Nenhum aviso registrado.")); self.pages.setCurrentIndex(1)

    def _delete(self):
        if QMessageBox.question(self,"Excluir lote","Excluir este lote do histórico?",QMessageBox.StandardButton.Cancel|QMessageBox.StandardButton.Yes,QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes:return
        try:self.repository.delete(self._current_id)
        except ProductionHistoryStorageError: QMessageBox.warning(self,"Histórico","Não foi possível excluir o registro."); return
        self.pages.setCurrentIndex(0); self.refresh()

    def _clear(self):
        if QMessageBox.warning(self,"Limpar histórico","Excluir TODOS os lotes do histórico? Esta ação não pode ser desfeita.",QMessageBox.StandardButton.Cancel|QMessageBox.StandardButton.Yes,QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes:return
        try:self.repository.clear()
        except ProductionHistoryStorageError: QMessageBox.warning(self,"Histórico","Não foi possível limpar o histórico.")
        self.refresh()

    def _back(self):
        if self.pages.currentIndex()==1: self.pages.setCurrentIndex(0)
        else:self.back_requested.emit()
