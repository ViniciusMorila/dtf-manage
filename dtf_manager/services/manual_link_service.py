from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt


SUPPORTED_MANUAL_ART_EXTENSIONS = frozenset((".png", ".jpg", ".jpeg", ".webp"))


class ManualLinkValidationError(ValueError):
    pass


def create_manual_linked_art(path: Path) -> LinkedArt:
    if path.suffix.casefold() not in SUPPORTED_MANUAL_ART_EXTENSIONS:
        raise ManualLinkValidationError("Selecione uma imagem PNG, JPG, JPEG ou WEBP.")
    if not path.is_file():
        raise ManualLinkValidationError("Não foi possível acessar esta arte.")
    try:
        with Image.open(path) as image:
            dpi_x, dpi_y = image.info.get("dpi", (300, 300))
            dpi_x, dpi_y = dpi_x or 300, dpi_y or 300
            width_cm = image.width / dpi_x * 2.54
            height_cm = image.height / dpi_y * 2.54
            image.verify()
    except (OSError, UnidentifiedImageError, ValueError) as error:
        raise ManualLinkValidationError("Não foi possível ler esta imagem.") from error
    return LinkedArt(
        id=str(uuid4()),
        file_name=path.name,
        file_reference=str(path.resolve()),
        copies_per_product=1,
        link_method="manual",
        width_cm=width_cm,
        height_cm=height_cm,
    )


def validate_linked_arts(arts: list[LinkedArt]) -> list[LinkedArt]:
    validated: list[LinkedArt] = []
    references: set[str] = set()
    for art in arts:
        if not art.file_name or not art.file_reference:
            continue
        if art.copies_per_product < 1:
            raise ManualLinkValidationError("A quantidade de cada arte deve ser pelo menos 1.")
        reference_key = (
            str(Path(art.file_reference).resolve()).casefold(),
            round(art.width_cm or 0.0, 4),
            round(art.height_cm or 0.0, 4),
            art.color_mode,
        )
        if reference_key in references:
            raise ManualLinkValidationError("Esta arte já foi adicionada a este produto.")
        references.add(reference_key)
        validated.append(art)
    return validated


def update_order_item_links(
    orders: tuple[ImportedOrder, ...] | list[ImportedOrder],
    item_id: str,
    arts: list[LinkedArt],
) -> tuple[list[ImportedOrder], ImportedOrderItem]:
    validated = validate_linked_arts(arts)
    updated_item: ImportedOrderItem | None = None
    updated_orders: list[ImportedOrder] = []
    for order in orders:
        new_items: list[ImportedOrderItem] = []
        for item in order.items:
            if item.id == item_id:
                updated_item = replace(
                    item,
                    linked_arts=list(validated),
                    link_status="linked" if validated else "unlinked",
                    automatic_links_confirmed=any(
                        art.link_method == "automatic" for art in validated
                    ),
                )
                new_items.append(updated_item)
            else:
                new_items.append(item)
        updated_orders.append(replace(order, items=new_items) if new_items != order.items else order)
    if updated_item is None:
        raise ManualLinkValidationError("O produto selecionado não está mais disponível.")
    return updated_orders, updated_item


class ManualLinkQueue:
    def __init__(self, item_ids: tuple[str, ...], start_item_id: str | None = None):
        self.item_ids = item_ids
        if not item_ids:
            self.index = 0
        elif start_item_id in item_ids:
            self.index = item_ids.index(start_item_id)
        else:
            self.index = 0

    @property
    def current_item_id(self) -> str | None:
        return self.item_ids[self.index] if self.item_ids else None

    @property
    def is_last(self) -> bool:
        return bool(self.item_ids) and self.index == len(self.item_ids) - 1

    def advance(self) -> bool:
        if self.is_last or not self.item_ids:
            return False
        self.index += 1
        return True

    def previous(self) -> bool:
        if self.index <= 0:
            return False
        self.index -= 1
        return True
