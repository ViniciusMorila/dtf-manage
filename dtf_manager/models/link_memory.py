from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ProductLinkIdentity:
    listing_id: str
    sku: str
    variant_id: str | None
    variation_raw: str
    variation_normalized: str


@dataclass(frozen=True, slots=True)
class RememberedArt:
    file_name: str
    file_reference: str
    relative_path: str | None
    copies_per_product: int
    width_cm: float | None = None
    height_cm: float | None = None
    color_mode: Literal["original", "black", "white"] = "original"


@dataclass(frozen=True, slots=True)
class ArtLinkMemory:
    id: str
    identity: ProductLinkIdentity
    product_name: str
    arts: tuple[RememberedArt, ...]
    created_at: str
    updated_at: str
    source: Literal["manual", "confirmed-auto"]
