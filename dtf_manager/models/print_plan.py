from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class DTFPrintPlanItem:
    id: str
    file_name: str
    file_reference: str
    total_copies: int
    source_item_ids: tuple[str, ...]
    source_order_numbers: tuple[str, ...]
    width_cm: float | None = None
    height_cm: float | None = None
    color_mode: Literal["original", "black", "white"] = "original"


@dataclass(frozen=True, slots=True)
class DTFOrderPlan:
    source_order_count: int
    source_item_count: int
    total_print_copies: int
    arts: tuple[DTFPrintPlanItem, ...]
