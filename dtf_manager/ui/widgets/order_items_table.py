from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QAbstractItemView, QLabel, QTableWidget, QTableWidgetItem

from dtf_manager.models.imported_order import ImportedOrderItem


class OrderItemsTable(QTableWidget):
    item_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("orderItemsTable")
        self.setColumnCount(7)
        self.setHorizontalHeaderLabels(("IMAGEM", "PRODUTO", "PEDIDO", "SKU", "VARIAÇÃO", "QTD.", "STATUS"))
        self.verticalHeader().hide()
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setColumnWidth(0, 82)
        self.setColumnWidth(1, 320)
        self.setColumnWidth(2, 170)
        self.setColumnWidth(3, 210)
        self.setColumnWidth(4, 210)
        self.setColumnWidth(5, 65)
        self.horizontalHeader().setStretchLastSection(True)
        self._network = QNetworkAccessManager(self)
        self._image_urls: dict[int, str] = {}
        self._requested_rows: set[int] = set()
        self._pixmap_cache: dict[str, QPixmap | None] = {}
        self._item_ids: dict[int, str] = {}
        self.verticalScrollBar().valueChanged.connect(self._schedule_visible_images)
        self.cellClicked.connect(lambda row, _column: self.item_activated.emit(self._item_ids[row]))

    def set_items(self, items: tuple[ImportedOrderItem, ...]) -> None:
        self.setUpdatesEnabled(False)
        self.setRowCount(0)
        self._image_urls.clear()
        self._requested_rows.clear()
        self._item_ids.clear()
        for row, item in enumerate(items):
            self._item_ids[row] = item.id
            self.insertRow(row)
            self.setRowHeight(row, 70)
            image = QLabel("Sem imagem")
            image.setObjectName("productImagePlaceholder")
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setAccessibleName(f"Imagem de {item.product_name}")
            self.setCellWidget(row, 0, image)
            if item.product_image_url:
                self._image_urls[row] = item.product_image_url
            art_count = len(item.linked_arts)
            linked_label = "VINCULADO"
            if item.link_status == "linked" and art_count:
                linked_label += f" · {art_count} arte" if art_count == 1 else f" · {art_count} artes"
                methods = {art.link_method for art in item.linked_arts}
                origin = (
                    "MEMÓRIA" if methods == {"memory"}
                    else "MANUAL" if methods == {"manual"}
                    else "AUTOMÁTICO" if methods == {"automatic"}
                    else "MISTO"
                )
                linked_label += f" · {origin}"
            values = (
                item.product_name,
                item.platform_order_number,
                item.sku,
                item.variation_raw,
                str(item.product_quantity),
                linked_label if item.link_status == "linked" else "NÃO VINCULADO",
            )
            for column, value in enumerate(values, start=1):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                if column in (5, 6):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 6:
                    cell.setData(Qt.ItemDataRole.UserRole, item.link_status)
                    cell.setForeground(QBrush(QColor("#54c98a" if item.link_status == "linked" else "#e69b45")))
                    if item.link_status == "linked" and item.linked_arts:
                        count = len(item.linked_arts)
                        cell.setToolTip(f"{count} arte" if count == 1 else f"{count} artes")
                self.setItem(row, column, cell)
        self.setUpdatesEnabled(True)
        QTimer.singleShot(0, self._load_visible_images)

    def _schedule_visible_images(self) -> None:
        QTimer.singleShot(0, self._load_visible_images)

    def _load_visible_images(self) -> None:
        if not self._image_urls or self.rowCount() == 0:
            return
        first = max(0, self.rowAt(0))
        last = self.rowAt(self.viewport().height() - 1)
        if last < 0:
            last = min(self.rowCount() - 1, first + 15)
        for row in range(first, last + 1):
            url = self._image_urls.get(row)
            if not url or row in self._requested_rows:
                continue
            self._requested_rows.add(row)
            if url in self._pixmap_cache:
                self._show_image(row, self._pixmap_cache[url])
                continue
            request = QNetworkRequest(QUrl(url))
            request.setTransferTimeout(8000)
            reply = self._network.get(request)
            reply.setProperty("table_row", row)
            reply.setProperty("image_url", url)
            reply.finished.connect(lambda current=reply: self._image_finished(current))

    def _image_finished(self, reply: QNetworkReply) -> None:
        row = int(reply.property("table_row"))
        url = str(reply.property("image_url"))
        pixmap = QPixmap()
        valid = reply.error() == QNetworkReply.NetworkError.NoError and pixmap.loadFromData(reply.readAll())
        cached = pixmap if valid else None
        self._pixmap_cache[url] = cached
        self._show_image(row, cached)
        reply.deleteLater()

    def _show_image(self, row: int, pixmap: QPixmap | None) -> None:
        label = self.cellWidget(row, 0)
        if not isinstance(label, QLabel):
            return
        if pixmap is None or pixmap.isNull():
            label.setText("Sem imagem")
            label.setPixmap(QPixmap())
            return
        label.setText("")
        label.setPixmap(pixmap.scaled(64, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
