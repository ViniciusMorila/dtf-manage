from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class LinkedArt:
    id: str
    file_name: str
    file_reference: str | None
    copies_per_product: int
    link_method: Literal["automatic", "manual", "memory"]
    width_cm: float | None = None
    height_cm: float | None = None
    color_mode: Literal["original", "black", "white"] = "original"


@dataclass(frozen=True, slots=True)
class ImportedOrderItem:
    id: str
    order_id: str
    platform_order_number: str
    product_name: str
    listing_id: str
    sku: str
    variation_raw: str
    variation_normalized: str
    variant_id: str | None
    product_image_url: str | None
    product_price: float | None
    product_quantity: int
    linked_arts: list[LinkedArt] = field(default_factory=list)
    link_status: Literal["linked", "unlinked"] = "unlinked"
    automatic_links_confirmed: bool = False


@dataclass(frozen=True, slots=True)
class ImportedOrder:
    id: str
    platform_order_number: str
    upseller_order_number: str | None
    platform: str | None
    store_name: str | None
    items: list[ImportedOrderItem] = field(default_factory=list)
