from dataclasses import dataclass
from enum import Enum
import unicodedata

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem


class ItemLinkFilter(str, Enum):
    ALL = "all"
    LINKED = "linked"
    UNLINKED = "unlinked"


@dataclass(frozen=True, slots=True)
class OrderImportMetrics:
    order_count: int
    item_count: int
    linked_count: int
    unlinked_count: int
    progress_percent: float


def get_all_items(orders: tuple[ImportedOrder, ...] | list[ImportedOrder]) -> tuple[ImportedOrderItem, ...]:
    return tuple(item for order in orders for item in order.items)


def get_linked_items(items: tuple[ImportedOrderItem, ...]) -> tuple[ImportedOrderItem, ...]:
    return tuple(item for item in items if item.link_status == "linked")


def get_unlinked_items(items: tuple[ImportedOrderItem, ...]) -> tuple[ImportedOrderItem, ...]:
    return tuple(item for item in items if item.link_status == "unlinked")


def get_import_metrics(orders: tuple[ImportedOrder, ...] | list[ImportedOrder]) -> OrderImportMetrics:
    items = get_all_items(orders)
    linked_count = len(get_linked_items(items))
    item_count = len(items)
    return OrderImportMetrics(
        order_count=len(orders),
        item_count=item_count,
        linked_count=linked_count,
        unlinked_count=len(get_unlinked_items(items)),
        progress_percent=(linked_count / item_count * 100) if item_count else 0.0,
    )


def _search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold().strip())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def filter_order_items(
    items: tuple[ImportedOrderItem, ...],
    link_filter: ItemLinkFilter = ItemLinkFilter.ALL,
    query: str = "",
) -> tuple[ImportedOrderItem, ...]:
    normalized_query = _search_text(query)
    result: list[ImportedOrderItem] = []
    for item in items:
        if link_filter != ItemLinkFilter.ALL and item.link_status != link_filter.value:
            continue
        searchable = " ".join((
            item.platform_order_number,
            item.sku,
            item.product_name,
            item.variation_raw,
            item.listing_id,
        ))
        if normalized_query and normalized_query not in _search_text(searchable):
            continue
        result.append(item)
    return tuple(result)


def get_order_link_status(order: ImportedOrder) -> str:
    linked = sum(item.link_status == "linked" for item in order.items)
    if not order.items or linked == 0:
        return "unlinked"
    if linked == len(order.items):
        return "all_linked"
    return "partial"

