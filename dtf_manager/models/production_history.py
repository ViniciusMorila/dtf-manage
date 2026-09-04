from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class BatchItemArtSnapshot:
    file_name: str
    file_reference_snapshot: str | None
    copies_per_product: int
    final_copies: int
    link_method: str
    width_cm: float | None = None
    height_cm: float | None = None


@dataclass(frozen=True, slots=True)
class BatchOrderItemSnapshot:
    product_name: str
    listing_id: str
    sku: str
    variation_raw: str
    variant_id: str | None
    product_quantity: int
    arts: tuple[BatchItemArtSnapshot, ...]


@dataclass(frozen=True, slots=True)
class BatchOrderSnapshot:
    platform_order_number: str
    upseller_order_number: str | None
    platform: str | None
    store_name: str | None
    items: tuple[BatchOrderItemSnapshot, ...]


@dataclass(frozen=True, slots=True)
class BatchArtSnapshot:
    art_key: str
    file_name: str
    file_reference_snapshot: str | None
    total_copies: int
    source_order_numbers: tuple[str, ...]
    source_skus: tuple[str, ...]
    source_item_count: int


@dataclass(frozen=True, slots=True)
class BatchSummary:
    order_count: int
    item_count: int
    product_unit_count: int
    unique_art_count: int
    total_print_copies: int


@dataclass(frozen=True, slots=True)
class BatchValidationIssueSnapshot:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class BatchValidationSnapshot:
    error_count: int
    warning_count: int
    info_count: int
    warnings: tuple[BatchValidationIssueSnapshot, ...]


@dataclass(frozen=True, slots=True)
class BatchRollSettingsSnapshot:
    film_width_cm: float | None
    gap_cm: float | None
    dpi: int | None
    automatic_division: bool | None
    maximum_length_m: float | None


@dataclass(frozen=True, slots=True)
class ProductionBatchHistory:
    id: str
    operation_id: str
    batch_number: str
    created_at: str
    mounted_at: str | None
    status: Literal["prepared", "mounted"]
    summary: BatchSummary
    orders: tuple[BatchOrderSnapshot, ...]
    arts: tuple[BatchArtSnapshot, ...]
    validation: BatchValidationSnapshot
    roll_settings: BatchRollSettingsSnapshot
