from dataclasses import dataclass
from typing import Literal


IssueSeverity = Literal["error", "warning", "info"]


@dataclass(frozen=True, slots=True)
class ProductionIssue:
    id: str
    severity: IssueSeverity
    code: str
    message: str
    item_id: str | None = None
    order_id: str | None = None
    art_id: str | None = None
    file_reference: str | None = None
    product_name: str | None = None
    art_name: str | None = None
    action: str | None = None


@dataclass(frozen=True, slots=True)
class ProductionValidationResult:
    errors: tuple[ProductionIssue, ...] = ()
    warnings: tuple[ProductionIssue, ...] = ()
    info: tuple[ProductionIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def status(self) -> Literal["ready", "warning", "error"]:
        if self.errors:
            return "error"
        return "warning" if self.warnings else "ready"

    @property
    def all_issues(self) -> tuple[ProductionIssue, ...]:
        return self.errors + self.warnings + self.info
