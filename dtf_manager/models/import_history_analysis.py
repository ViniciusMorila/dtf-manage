from dataclasses import dataclass, field
from typing import Literal

from dtf_manager.models.imported_order import ImportedOrder
from dtf_manager.models.production_history import BatchOrderSnapshot


ImportOrderClassification = Literal["new", "already_processed", "changed"]


@dataclass(frozen=True, slots=True)
class OrderDifference:
    code: str
    message: str


@dataclass(slots=True)
class AnalyzedImportedOrder:
    order: ImportedOrder
    classification: ImportOrderClassification
    previous_batch_id: str | None = None
    previous_batch_number: str | None = None
    previous_mounted_at: str | None = None
    previous_order: BatchOrderSnapshot | None = None
    differences: tuple[OrderDifference, ...] = ()
    selected_for_current_batch: bool = False
    manually_included_again: bool = False


@dataclass(slots=True)
class ImportHistoryAnalysis:
    orders: list[AnalyzedImportedOrder] = field(default_factory=list)

    @property
    def total_orders(self): return len(self.orders)
    @property
    def new_orders(self): return tuple(value for value in self.orders if value.classification == "new")
    @property
    def already_processed_orders(self): return tuple(value for value in self.orders if value.classification == "already_processed")
    @property
    def changed_orders(self): return tuple(value for value in self.orders if value.classification == "changed")
    @property
    def selected_orders(self): return tuple(value.order for value in self.orders if value.selected_for_current_batch)
