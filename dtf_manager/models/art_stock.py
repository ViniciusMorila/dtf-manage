from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArtFile:
    """A file found in the art folder (light listing: no image decoding)."""
    relative_path: str        # posix style, relative to the selected folder
    absolute_path: str
    name: str
    size: int
    mtime: float


@dataclass(frozen=True, slots=True)
class ArtFileRow:
    id: int
    key: str
    name: str
    relative_path: str
    absolute_path: str
    outside_folder: bool
    missing: bool


@dataclass(frozen=True, slots=True)
class ArtRow:
    """One art in the stock list. Each art appears once, whatever SKUs or sizes use it."""
    art_id: int
    name: str
    relative_path: str
    absolute_path: str
    stock: int
    future: int
    outside_folder: bool
    missing: bool

    @property
    def balance(self) -> int:
        return self.stock - self.future

    @property
    def shortage(self) -> int:
        return max(0, self.future - self.stock)


@dataclass(frozen=True, slots=True)
class ArtSeparationRow:
    art_id: int
    name: str
    absolute_path: str
    needed: int
    available: int
    separated: bool

    @property
    def shortage(self) -> int:
        return max(0, self.needed - self.available)


@dataclass(frozen=True, slots=True)
class ArtSnapshot:
    rows: tuple[ArtRow, ...]
    separation: tuple[ArtSeparationRow, ...]
    unlinked_items: int

    @property
    def has_future(self) -> bool:
        return any(row.future > 0 for row in self.rows)

    @property
    def total_stock(self) -> int:
        return sum(row.stock for row in self.rows)

    @property
    def total_future(self) -> int:
        return sum(row.future for row in self.rows)

    @property
    def total_shortage(self) -> int:
        return sum(row.shortage for row in self.rows)


@dataclass(frozen=True, slots=True)
class ArtFinalizeRow:
    name: str
    future: int
    stock: int
    after: int
    shortage: int


@dataclass(frozen=True, slots=True)
class MatchSuggestion:
    """A registered file that vanished and a file in the folder with the same name."""
    from_id: int
    to_id: int
    from_path: str
    to_path: str
    stock: int
