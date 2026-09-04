from PySide6.QtCore import QObject, Signal

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem
from dtf_manager.models.automatic_link import AutoLinkResult
from dtf_manager.state.order_selectors import get_all_items
from dtf_manager.models.imported_order import LinkedArt
from dtf_manager.services.manual_link_service import update_order_item_links


class OrderImportState(QObject):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._imported_orders: list[ImportedOrder] = []
        self._auto_link_results: tuple[AutoLinkResult, ...] = ()
        self.last_art_folder: str | None = None

    @property
    def imported_orders(self) -> tuple[ImportedOrder, ...]:
        return tuple(self._imported_orders)

    @property
    def all_items(self) -> tuple[ImportedOrderItem, ...]:
        return get_all_items(self._imported_orders)

    def replace_orders(self, orders: list[ImportedOrder]) -> None:
        self._imported_orders = list(orders)
        self._auto_link_results = ()
        self.changed.emit()

    @property
    def auto_link_results(self) -> tuple[AutoLinkResult, ...]:
        return self._auto_link_results

    def apply_auto_link(self, orders: list[ImportedOrder], results: tuple[AutoLinkResult, ...]) -> None:
        self._imported_orders = list(orders)
        self._auto_link_results = results
        self.changed.emit()

    def find_item(self, item_id: str) -> ImportedOrderItem | None:
        return next((item for item in self.all_items if item.id == item_id), None)

    def find_order_for_item(self, item_id: str) -> ImportedOrder | None:
        return next(
            (order for order in self._imported_orders if any(item.id == item_id for item in order.items)),
            None,
        )

    def update_item_links(self, item_id: str, arts: list[LinkedArt]) -> ImportedOrderItem:
        orders, updated_item = update_order_item_links(self._imported_orders, item_id, arts)
        self._imported_orders = orders
        self.changed.emit()
        return updated_item
