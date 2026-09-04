import json
from collections import Counter
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from dtf_manager.models.import_history_analysis import AnalyzedImportedOrder, ImportHistoryAnalysis, OrderDifference
from dtf_manager.models.imported_order import ImportedOrder, LinkedArt
from dtf_manager.models.production_history import BatchOrderSnapshot, ProductionBatchHistory
from dtf_manager.utils.spreadsheet_values import normalize_variation


def _current_signature(item):
    variant = ("null", "") if item.variant_id is None else ("value", str(item.variant_id))
    return (str(item.listing_id), str(item.sku), variant, item.variation_normalized, item.product_quantity)


def _historical_signature(item):
    variant = ("null", "") if item.variant_id is None else ("value", str(item.variant_id))
    return (str(item.listing_id), str(item.sku), variant, normalize_variation(item.variation_raw), item.product_quantity)


def build_order_production_fingerprint(order: ImportedOrder) -> str:
    return json.dumps(sorted(_current_signature(item) for item in order.items), ensure_ascii=False, separators=(",", ":"))


def build_historical_order_fingerprint(order: BatchOrderSnapshot) -> str:
    return json.dumps(sorted(_historical_signature(item) for item in order.items), ensure_ascii=False, separators=(",", ":"))


def compare_order_snapshots(current: ImportedOrder, previous: BatchOrderSnapshot) -> tuple[OrderDifference, ...]:
    current_signatures = Counter(_current_signature(item) for item in current.items)
    previous_signatures = Counter(_historical_signature(item) for item in previous.items)
    if current_signatures == previous_signatures: return ()
    differences: list[OrderDifference] = []
    current_by_identity = {(str(i.listing_id), str(i.sku), i.variant_id): i for i in current.items}
    previous_by_identity = {(str(i.listing_id), str(i.sku), i.variant_id): i for i in previous.items}
    for identity in current_by_identity.keys() & previous_by_identity.keys():
        new, old = current_by_identity[identity], previous_by_identity[identity]
        if new.product_quantity != old.product_quantity:
            differences.append(OrderDifference("QUANTITY_CHANGED", f"A quantidade de {new.product_name} mudou de {old.product_quantity} para {new.product_quantity}."))
        old_variation = normalize_variation(old.variation_raw)
        if new.variation_normalized != old_variation:
            differences.append(OrderDifference("VARIATION_CHANGED", f"A variação mudou de {old.variation_raw or '—'} para {new.variation_raw or '—'}."))
    for new in current.items:
        if any(str(old.listing_id) == str(new.listing_id) and old.variant_id == new.variant_id and old.sku != new.sku for old in previous.items):
            differences.append(OrderDifference("SKU_CHANGED", f"O SKU de um produto mudou para {new.sku}."))
        if any(str(old.listing_id) == str(new.listing_id) and old.sku == new.sku and old.variant_id != new.variant_id for old in previous.items):
            differences.append(OrderDifference("VARIANT_CHANGED", "A variante de um produto foi alterada."))
        if any(old.sku == new.sku and old.variant_id == new.variant_id and str(old.listing_id) != str(new.listing_id) for old in previous.items):
            differences.append(OrderDifference("LISTING_CHANGED", "O anúncio associado a um produto foi alterado."))
    unmatched_current = current_signatures - previous_signatures
    unmatched_previous = previous_signatures - current_signatures
    explained_current = sum(1 for d in differences if d.code in ("QUANTITY_CHANGED", "VARIATION_CHANGED"))
    if sum(unmatched_current.values()) > explained_current:
        differences.append(OrderDifference("ITEM_ADDED", "Foi adicionado ou substituído um produto no pedido."))
    if sum(unmatched_previous.values()) > explained_current:
        differences.append(OrderDifference("ITEM_REMOVED", "Foi removido ou substituído um produto do pedido."))
    unique = list(dict.fromkeys((difference.code, difference.message) for difference in differences))
    return tuple(OrderDifference(code, message) for code, message in unique) or (OrderDifference("CONTENT_CHANGED", "O conteúdo deste pedido é diferente da versão processada anteriormente."),)


def build_history_order_index(batches: tuple[ProductionBatchHistory, ...] | list[ProductionBatchHistory]):
    index: dict[str, list[tuple[str, ProductionBatchHistory, BatchOrderSnapshot]]] = {}
    for batch in batches:
        if batch.status != "mounted": continue
        timestamp = batch.mounted_at or batch.created_at
        for order in batch.orders:
            index.setdefault(order.platform_order_number, []).append((timestamp, batch, order))
    for occurrences in index.values(): occurrences.sort(key=lambda value: value[0], reverse=True)
    return index


def restore_historical_order_links(
    current: ImportedOrder, previous: BatchOrderSnapshot
) -> ImportedOrder:
    """Restore saved art links onto an unchanged order imported again."""
    available = list(previous.items)
    restored_items = []
    for item in current.items:
        match_index = next((
            index for index, old in enumerate(available)
            if (
                str(old.listing_id), str(old.sku), old.variant_id,
                normalize_variation(old.variation_raw), old.product_quantity,
            ) == (
                str(item.listing_id), str(item.sku), item.variant_id,
                item.variation_normalized, item.product_quantity,
            )
        ), None)
        if match_index is None:
            restored_items.append(item)
            continue
        old = available.pop(match_index)
        arts = [LinkedArt(
            id=str(uuid5(NAMESPACE_URL, f"history-link:{item.id}:{position}:{art.file_reference_snapshot}")),
            file_name=art.file_name,
            file_reference=art.file_reference_snapshot,
            copies_per_product=art.copies_per_product,
            link_method="memory",
            width_cm=art.width_cm,
            height_cm=art.height_cm,
        ) for position, art in enumerate(old.arts) if art.file_reference_snapshot]
        restored_items.append(replace(
            item,
            linked_arts=arts,
            link_status="linked" if arts else "unlinked",
            automatic_links_confirmed=bool(arts),
        ))
    return replace(current, items=restored_items)


def analyze_imported_orders_against_history(imported_orders: list[ImportedOrder] | tuple[ImportedOrder, ...], batches) -> ImportHistoryAnalysis:
    index = build_history_order_index(batches); analyzed=[]
    for order in imported_orders:
        occurrences=index.get(order.platform_order_number)
        if not occurrences:
            analyzed.append(AnalyzedImportedOrder(order,"new",selected_for_current_batch=True)); continue
        timestamp,batch,previous=occurrences[0]
        equal=build_order_production_fingerprint(order)==build_historical_order_fingerprint(previous)
        restored_order = restore_historical_order_links(order, previous)
        analyzed.append(AnalyzedImportedOrder(
            restored_order,"already_processed" if equal else "changed",batch.id,batch.batch_number,timestamp,previous,
            () if equal else compare_order_snapshots(order,previous),False,False,
        ))
    return ImportHistoryAnalysis(analyzed)


def set_order_selection(analyzed: AnalyzedImportedOrder, selected: bool, *, explicitly_confirmed: bool = False) -> None:
    if selected and analyzed.classification != "new" and not explicitly_confirmed:
        raise ValueError("A inclusão deste pedido precisa de confirmação explícita.")
    analyzed.selected_for_current_batch = selected
    analyzed.manually_included_again = selected and analyzed.classification != "new"
