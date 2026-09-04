from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dtf_manager.models.imported_order import ImportedOrder
from dtf_manager.models.print_plan import DTFOrderPlan
from dtf_manager.models.production_history import (
    BatchArtSnapshot, BatchItemArtSnapshot, BatchOrderItemSnapshot, BatchOrderSnapshot,
    BatchRollSettingsSnapshot, BatchSummary, BatchValidationIssueSnapshot,
    BatchValidationSnapshot, ProductionBatchHistory,
)
from dtf_manager.models.production_validation import ProductionValidationResult


def create_production_batch_snapshot(
    imported_orders: tuple[ImportedOrder, ...] | list[ImportedOrder],
    print_plan: DTFOrderPlan,
    validation_result: ProductionValidationResult,
    roll_settings: BatchRollSettingsSnapshot,
    *, batch_number: str, operation_id: str, now: datetime | None = None,
) -> ProductionBatchHistory:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    order_snapshots: list[BatchOrderSnapshot] = []
    sku_by_item: dict[str, str] = {}
    for order in imported_orders:
        items: list[BatchOrderItemSnapshot] = []
        for item in order.items:
            sku_by_item[item.id] = item.sku
            arts = tuple(BatchItemArtSnapshot(
                file_name=art.file_name,
                file_reference_snapshot=str(Path(art.file_reference).resolve()) if art.file_reference else None,
                copies_per_product=art.copies_per_product,
                final_copies=item.product_quantity * art.copies_per_product,
                link_method=art.link_method,
                width_cm=art.width_cm,
                height_cm=art.height_cm,
            ) for art in item.linked_arts)
            items.append(BatchOrderItemSnapshot(
                item.product_name, item.listing_id, item.sku, item.variation_raw,
                item.variant_id, item.product_quantity, arts,
            ))
        order_snapshots.append(BatchOrderSnapshot(
            order.platform_order_number, order.upseller_order_number,
            order.platform, order.store_name, tuple(items),
        ))
    art_snapshots = tuple(BatchArtSnapshot(
        art_key=art.id, file_name=art.file_name,
        file_reference_snapshot=art.file_reference, total_copies=art.total_copies,
        source_order_numbers=tuple(art.source_order_numbers),
        source_skus=tuple(dict.fromkeys(sku_by_item.get(item_id, "") for item_id in art.source_item_ids if sku_by_item.get(item_id, ""))),
        source_item_count=len(set(art.source_item_ids)),
    ) for art in print_plan.arts)
    validation = BatchValidationSnapshot(
        len(validation_result.errors), len(validation_result.warnings), len(validation_result.info),
        tuple(BatchValidationIssueSnapshot(issue.code, issue.message) for issue in validation_result.warnings),
    )
    return ProductionBatchHistory(
        id=str(uuid4()), operation_id=operation_id, batch_number=batch_number,
        created_at=timestamp, mounted_at=timestamp, status="mounted",
        summary=BatchSummary(
            print_plan.source_order_count, print_plan.source_item_count,
            sum(item.product_quantity for order in imported_orders for item in order.items),
            len(print_plan.arts), print_plan.total_print_copies,
        ),
        orders=tuple(order_snapshots), arts=art_snapshots,
        validation=validation, roll_settings=roll_settings,
    )


def batch_matches(batch: ProductionBatchHistory, query: str) -> bool:
    needle = query.strip().casefold()
    if not needle:
        return True
    values = [batch.batch_number]
    for order in batch.orders:
        values.append(order.platform_order_number)
        for item in order.items:
            values.extend((item.sku, item.product_name))
            values.extend(art.file_name for art in item.arts)
    return any(needle in value.casefold() for value in values if value)
