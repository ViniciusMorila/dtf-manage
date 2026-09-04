from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.models.print_plan import DTFOrderPlan, DTFPrintPlanItem


class PrintPlanValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedRollArtwork:
    file_path: Path
    width_cm: float
    height_cm: float
    quantity: int
    color_mode: str = "original"


@dataclass(slots=True)
class _AggregatedArt:
    file_name: str
    file_reference: str
    total_copies: int
    source_item_ids: list[str]
    source_order_numbers: list[str]
    width_cm: float | None
    height_cm: float | None
    color_mode: str


def _positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def is_item_print_ready(item: ImportedOrderItem) -> bool:
    return (
        item.link_status == "linked"
        and _positive_integer(item.product_quantity)
        and bool(item.linked_arts)
        and all(
            art.file_name
            and art.file_reference
            and _positive_integer(art.copies_per_product)
            for art in item.linked_arts
        )
    )


def can_build_print_plan(orders: tuple[ImportedOrder, ...] | list[ImportedOrder]) -> bool:
    items = [item for order in orders for item in order.items]
    return bool(items) and all(is_item_print_ready(item) for item in items)


def _validate_art_file(item: ImportedOrderItem, art: LinkedArt) -> Path:
    if not art.file_reference:
        raise PrintPlanValidationError(
            f'A arte "{art.file_name or "sem nome"}" do produto "{item.product_name}" não possui referência válida.'
        )
    path = Path(art.file_reference)
    if not path.is_file():
        raise PrintPlanValidationError(
            f'Não foi possível acessar a arte "{art.file_name}" do produto "{item.product_name}".'
        )
    return path.resolve()


def build_dtf_print_plan(
    orders: tuple[ImportedOrder, ...] | list[ImportedOrder],
    validate_files: bool = True,
) -> DTFOrderPlan:
    if not orders:
        raise PrintPlanValidationError("Nenhum pedido foi importado.")
    aggregated: dict[str, _AggregatedArt] = {}
    source_item_count = 0
    for order in orders:
        for item in order.items:
            source_item_count += 1
            if not is_item_print_ready(item):
                raise PrintPlanValidationError(
                    f'O produto "{item.product_name}" ainda não possui vínculos válidos.'
                )
            for art in item.linked_arts:
                if not _positive_integer(item.product_quantity):
                    raise PrintPlanValidationError(
                        f'A quantidade do produto "{item.product_name}" é inválida.'
                    )
                if not _positive_integer(art.copies_per_product):
                    raise PrintPlanValidationError(
                        f'A quantidade da arte "{art.file_name}" é inválida.'
                    )
                final_copies = item.product_quantity * art.copies_per_product
                if not _positive_integer(final_copies):
                    raise PrintPlanValidationError(
                        f'Não foi possível calcular a quantidade da arte "{art.file_name}".'
                    )
                path = _validate_art_file(item, art) if validate_files else Path(art.file_reference or "").resolve()
                # The same file may intentionally be printed at different sizes.
                # Aggregate only links whose file and configured dimensions match.
                identity = f"{str(path).casefold()}|{art.width_cm}|{art.height_cm}|{art.color_mode}"
                entry = aggregated.setdefault(
                    identity,
                    _AggregatedArt(art.file_name, str(path), 0, [], [], art.width_cm, art.height_cm, art.color_mode),
                )
                if entry.width_cm is None and art.width_cm is not None:
                    entry.width_cm = art.width_cm
                if entry.height_cm is None and art.height_cm is not None:
                    entry.height_cm = art.height_cm
                entry.total_copies += final_copies
                if item.id not in entry.source_item_ids:
                    entry.source_item_ids.append(item.id)
                if item.platform_order_number not in entry.source_order_numbers:
                    entry.source_order_numbers.append(item.platform_order_number)
    if source_item_count == 0:
        raise PrintPlanValidationError("Não há produtos para montar.")
    arts = tuple(
        DTFPrintPlanItem(
            id=str(uuid5(NAMESPACE_URL, f"print-plan:{identity}")),
            file_name=entry.file_name,
            file_reference=entry.file_reference,
            total_copies=entry.total_copies,
            source_item_ids=tuple(entry.source_item_ids),
            source_order_numbers=tuple(entry.source_order_numbers),
            width_cm=entry.width_cm,
            height_cm=entry.height_cm,
            color_mode=entry.color_mode,
        )
        for identity, entry in aggregated.items()
    )
    return DTFOrderPlan(
        source_order_count=len(orders),
        source_item_count=source_item_count,
        total_print_copies=sum(art.total_copies for art in arts),
        arts=arts,
    )


def prepare_print_plan_for_roll(plan: DTFOrderPlan, dimension_reader) -> tuple[PreparedRollArtwork, ...]:
    prepared: list[PreparedRollArtwork] = []
    for art in plan.arts:
        path = Path(art.file_reference)
        try:
            width_cm, height_cm = (
                (art.width_cm, art.height_cm)
                if art.width_cm and art.height_cm
                else dimension_reader(path)
            )
        except (OSError, ValueError) as error:
            raise PrintPlanValidationError(f'Não foi possível carregar a arte "{art.file_name}".') from error
        prepared.append(PreparedRollArtwork(path, width_cm, height_cm, art.total_copies, art.color_mode))
    return tuple(prepared)
