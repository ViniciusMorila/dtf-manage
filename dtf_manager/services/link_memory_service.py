from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from dtf_manager.models.imported_order import ImportedOrderItem, LinkedArt
from dtf_manager.models.link_memory import ArtLinkMemory, ProductLinkIdentity, RememberedArt
from dtf_manager.services.link_memory_repository import ProductLinkMemoryRepository


@dataclass(frozen=True, slots=True)
class MemoryLinkMatch:
    status: Literal["matched", "not_found", "memory_file_missing"]
    arts: tuple[LinkedArt, ...] = ()


def identity_from_item(item: ImportedOrderItem) -> ProductLinkIdentity:
    return ProductLinkIdentity(
        listing_id=item.listing_id,
        sku=item.sku,
        variant_id=item.variant_id,
        variation_raw=item.variation_raw,
        variation_normalized=item.variation_normalized,
    )


class ArtLinkMemoryService:
    def __init__(self, repository: ProductLinkMemoryRepository):
        self.repository = repository

    def remember_item(self, item: ImportedOrderItem, arts_root: str | None = None) -> ArtLinkMemory | None:
        identity = identity_from_item(item)
        if not item.linked_arts:
            existing = self.repository.find_for_identity(identity)
            if existing:
                self.repository.delete(existing.id)
            return None
        source = "manual" if any(art.link_method == "manual" for art in item.linked_arts) else "confirmed-auto"
        existing = self.repository.find_for_identity(identity)
        now = datetime.now(timezone.utc).isoformat()
        remembered_arts: list[RememberedArt] = []
        root = Path(arts_root).resolve() if arts_root else None
        for art in item.linked_arts:
            if not art.file_reference:
                continue
            path = Path(art.file_reference).resolve()
            relative: str | None = None
            if root:
                try:
                    relative = str(path.relative_to(root))
                except ValueError:
                    pass
            remembered_arts.append(RememberedArt(
                file_name=art.file_name,
                file_reference=str(path),
                relative_path=relative,
                copies_per_product=art.copies_per_product,
                width_cm=art.width_cm,
                height_cm=art.height_cm,
                color_mode=art.color_mode,
            ))
        if not remembered_arts:
            self.repository.delete_by_identity(identity)
            return None
        memory = ArtLinkMemory(
            id=existing.id if existing else str(uuid4()),
            identity=identity,
            product_name=item.product_name,
            arts=tuple(remembered_arts),
            created_at=existing.created_at if existing else now,
            updated_at=now,
            source=source,
        )
        self.repository.upsert(memory)
        return memory

    def find_and_resolve(self, item: ImportedOrderItem, arts_root: str | None = None) -> MemoryLinkMatch:
        memory = self.repository.find_for_identity(identity_from_item(item))
        if memory is None:
            return MemoryLinkMatch("not_found")
        root = Path(arts_root).resolve() if arts_root else None
        resolved: list[LinkedArt] = []
        for remembered in memory.arts:
            path = Path(remembered.file_reference)
            if not path.is_file() and root and remembered.relative_path:
                alternative = root / remembered.relative_path
                if alternative.is_file():
                    path = alternative
            if not path.is_file() or remembered.copies_per_product < 1:
                return MemoryLinkMatch("memory_file_missing")
            resolved.append(LinkedArt(
                id=str(uuid4()),
                file_name=remembered.file_name,
                file_reference=str(path.resolve()),
                copies_per_product=remembered.copies_per_product,
                link_method="memory",
                width_cm=remembered.width_cm,
                height_cm=remembered.height_cm,
                color_mode=remembered.color_mode,
            ))
        return MemoryLinkMatch("matched", tuple(resolved))
