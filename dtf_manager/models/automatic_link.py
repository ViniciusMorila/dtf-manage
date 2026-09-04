from dataclasses import dataclass
from typing import Literal

from dtf_manager.models.imported_order import ImportedOrder


@dataclass(frozen=True, slots=True)
class ArtCandidate:
    id: str
    file_name: str
    base_name: str
    normalized_name: str
    extension: str
    file_reference: str
    relative_path: str
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AutoLinkResult:
    item_id: str
    status: Literal["linked", "not_found", "ambiguous", "preserved"]
    confidence: Literal["high", "medium", "low"]
    candidate_count: int
    reason: str
    linked_candidate_ids: tuple[str, ...] = ()
    link_origin: Literal["automatic", "memory"] | None = None
    memory_diagnostic: Literal["memory_file_missing"] | None = None


@dataclass(frozen=True, slots=True)
class AutomaticLinkOutcome:
    orders: list[ImportedOrder]
    results: tuple[AutoLinkResult, ...]

    @property
    def linked_count(self) -> int:
        return sum(result.status == "linked" and result.link_origin != "memory" for result in self.results)

    @property
    def memory_linked_count(self) -> int:
        return sum(result.status == "linked" and result.link_origin == "memory" for result in self.results)

    @property
    def not_found_count(self) -> int:
        return sum(result.status == "not_found" for result in self.results)

    @property
    def ambiguous_count(self) -> int:
        return sum(result.status == "ambiguous" for result in self.results)
