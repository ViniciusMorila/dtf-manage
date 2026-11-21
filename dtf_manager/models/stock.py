from dataclasses import dataclass, field

# Movement kinds (history)
MOVEMENT_MANUAL = "ajuste_manual"
MOVEMENT_BULK = "adicao_em_massa"
MOVEMENT_IMPORT = "importacao"
MOVEMENT_FINALIZE = "finalizacao"
MOVEMENT_LABELS = {
    MOVEMENT_MANUAL: "Ajuste manual",
    MOVEMENT_BULK: "Adição em massa",
    MOVEMENT_IMPORT: "Importação",
    MOVEMENT_FINALIZE: "Finalização",
}


@dataclass(frozen=True, slots=True)
class StockColor:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class StockSize:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class Movement:
    id: int
    at: str
    kind: str
    scope: str           # "estoque" or "futuro"
    color: str
    size: str
    quantity: int        # after - before
    before: int
    after: int
    note: str


@dataclass(frozen=True, slots=True)
class ImportRecord:
    id: int
    at: str
    file_name: str
    file_hash: str
    order_count: int
    orders: tuple[str, ...]
    finalized_at: str | None


@dataclass(frozen=True, slots=True)
class PendingRow:
    product_name: str
    sku: str
    variation: str
    sizes: str
    quantity: int
    reason: str


@dataclass(frozen=True, slots=True)
class SeparationRow:
    color_id: int
    size_id: int
    color: str
    size: str
    needed: int          # futuro
    available: int       # estoque
    missing: int         # max(0, needed - available)
    separated: bool


@dataclass(frozen=True, slots=True)
class StockSnapshot:
    colors: tuple[StockColor, ...]
    sizes: tuple[StockSize, ...]
    stock: dict          # (color_id, size_id) -> int
    future: dict         # (color_id, size_id) -> int
    separation: tuple[SeparationRow, ...]
    pending: tuple[PendingRow, ...]
    note: str            # last import description (empty if none)

    @property
    def has_future(self) -> bool:
        return any(quantity > 0 for quantity in self.future.values())


# ---- import ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ValidationLine:
    """One row of the validation window: items with the same SKU (or listing + variant)."""
    key: str
    product_name: str
    sku: str
    variation: str
    sizes_text: str       # sizes identified ("" when none)
    shirts: int           # shirts affected
    needs_color: bool
    needs_size: bool
    color_hint: str       # unrecognized/ambiguous text found in the Variação, if any
    reason: str
    image_url: str = ""   # product image link from the spreadsheet, if any


@dataclass(frozen=True, slots=True)
class LineDecision:
    """What the user chose for a line. color/sizes: id of an existing one or a new name."""
    color: "int | str | None" = None
    sizes: tuple = ()
    remember: bool = True


@dataclass(slots=True)
class Preparation:
    totals: dict                          # (color_id, size_id) -> shirts, already resolved
    lines: list                           # list[ValidationLine]
    unresolved: dict                      # line key -> list of internal items
    counted_orders: list                  # order numbers counted
    excluded_orders: list                 # order numbers left out (already finalized)
    all_orders: list
    repeated_lines: int
    signature: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    shirts: int
    pending: int
    repeated_lines: int
    excluded_orders: int


@dataclass(frozen=True, slots=True)
class DuplicateInfo:
    previous: ImportRecord
    same_file: bool
    overlap: float
    new_orders: tuple[str, ...]
    old_count: int

    @property
    def finalized(self) -> bool:
        return self.previous.finalized_at is not None

    @property
    def mixed(self) -> bool:
        return bool(self.new_orders) and self.old_count > 0


@dataclass(frozen=True, slots=True)
class ImportNotice:
    """What the controller shows before processing a spreadsheet (B + A + already mounted)."""
    duplicate: DuplicateInfo | None
    finalized_count: int
    finalized_date: str                   # "DD/MM"
    mounted_count: int


@dataclass(frozen=True, slots=True)
class NoticeChoice:
    action: str = "import"                # "cancel" | "import" | "only_new"
    include_finalized: bool = False


@dataclass(frozen=True, slots=True)
class ImportDecision:
    orders: list
    file_name: str
    file_hash: str
    include_finalized: bool = False


@dataclass(frozen=True, slots=True)
class FinalizeRow:
    color: str
    size: str
    future: int
    stock: int
    after: int
    shortage: int


@dataclass(frozen=True, slots=True)
class FinalizeSummary:
    rows: tuple[FinalizeRow, ...]
    pending: int

    @property
    def shortages(self) -> tuple[FinalizeRow, ...]:
        return tuple(row for row in self.rows if row.shortage > 0)

    @property
    def needs_acknowledgement(self) -> bool:
        return bool(self.shortages) or self.pending > 0
