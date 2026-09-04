from dataclasses import dataclass, field
from typing import Literal

from dtf_manager.models.imported_order import ImportedOrder


OperationWorkflowStage = Literal[
    "orders_dashboard",
    "automatic_linking",
    "manual_linking",
    "production_review",
    "ready_to_mount",
]


@dataclass(frozen=True, slots=True)
class ManualLinkingSessionSnapshot:
    queue_item_ids: tuple[str, ...]
    current_item_id: str | None
    current_index: int
    skipped_item_ids: tuple[str, ...] = ()
    mode: Literal["queue", "single"] = "queue"


@dataclass(frozen=True, slots=True)
class ActiveOperationMetadata:
    order_count: int
    item_count: int
    linked_count: int
    unlinked_count: int


@dataclass(frozen=True, slots=True)
class ActiveProductionOperation:
    schema_version: int
    id: str
    import_fingerprint: str
    source_file_name: str | None
    created_at: str
    updated_at: str
    workflow_stage: OperationWorkflowStage
    current_view: str | None
    imported_orders: tuple[ImportedOrder, ...]
    manual_linking_state: ManualLinkingSessionSnapshot | None
    metadata: ActiveOperationMetadata

