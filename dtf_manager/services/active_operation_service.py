import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from dtf_manager.models.active_operation import (
    ActiveOperationMetadata,
    ActiveProductionOperation,
    ManualLinkingSessionSnapshot,
    OperationWorkflowStage,
)
from dtf_manager.models.imported_order import ImportedOrder
from dtf_manager.state.order_selectors import get_import_metrics


ACTIVE_OPERATION_SCHEMA_VERSION = 1


def build_import_operation_fingerprint(orders) -> str:
    canonical_orders = []
    for order in orders:
        items = sorted((
            str(item.listing_id),
            str(item.sku),
            ("null", "") if item.variant_id is None else ("value", str(item.variant_id)),
            str(item.variation_normalized),
            int(item.product_quantity),
        ) for item in order.items)
        canonical_orders.append((str(order.platform_order_number), items))
    canonical_orders.sort(key=lambda value: (value[0], value[1]))
    payload = json.dumps(canonical_orders, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def operation_metadata(orders) -> ActiveOperationMetadata:
    metrics = get_import_metrics(orders)
    return ActiveOperationMetadata(
        metrics.order_count, metrics.item_count, metrics.linked_count, metrics.unlinked_count
    )


def create_active_operation(
    orders: list[ImportedOrder] | tuple[ImportedOrder, ...],
    import_fingerprint: str,
    source_file_name: str | None,
) -> ActiveProductionOperation:
    now = datetime.now(timezone.utc).isoformat()
    return ActiveProductionOperation(
        schema_version=ACTIVE_OPERATION_SCHEMA_VERSION,
        id=str(uuid4()),
        import_fingerprint=import_fingerprint,
        source_file_name=source_file_name,
        created_at=now,
        updated_at=now,
        workflow_stage="orders_dashboard",
        current_view="orders_dashboard",
        imported_orders=tuple(orders),
        manual_linking_state=None,
        metadata=operation_metadata(orders),
    )


def checkpoint_operation(
    operation: ActiveProductionOperation,
    orders,
    stage: OperationWorkflowStage,
    manual_state: ManualLinkingSessionSnapshot | None = None,
    current_view: str | None = None,
) -> ActiveProductionOperation:
    return ActiveProductionOperation(
        schema_version=operation.schema_version,
        id=operation.id,
        import_fingerprint=operation.import_fingerprint,
        source_file_name=operation.source_file_name,
        created_at=operation.created_at,
        updated_at=datetime.now(timezone.utc).isoformat(),
        workflow_stage=stage,
        current_view=current_view or stage,
        imported_orders=tuple(orders),
        manual_linking_state=manual_state,
        metadata=operation_metadata(orders),
    )
