"""Helpers shared by the art-stock tests."""
import tempfile
from dataclasses import replace
from pathlib import Path

from PIL import Image

from dtf_manager.models.imported_order import LinkedArt
from dtf_manager.services.art_folder_listing import list_art_files
from dtf_manager.services.art_stock_repository import ArtStockRepository
from dtf_manager.services.art_stock_service import ArtStockService
from dtf_manager.services.sqlite_database import DTFDatabase
from dtf_manager.services.stock_repository import StockRepository
from dtf_manager.services.stock_service import StockService
from tests.stock_fakes import make_item, make_order

_shade = [0]


def make_folder() -> Path:
    return Path(tempfile.mkdtemp())


def make_art(folder: Path, relative: str, same_as: Path | None = None) -> Path:
    """Creates a small PNG at folder/relative. Every call gives different content unless
    `same_as` is given (then it is a byte-for-byte copy)."""
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if same_as is not None:
        path.write_bytes(Path(same_as).read_bytes())
    else:
        _shade[0] += 7
        Image.new("RGB", (16 + _shade[0] % 5, 16), (_shade[0] % 256, 40, 90)).save(path)
    return path


def linked_item(order, art_paths, quantity=1, sku="SKU-1", variation="Preta,G", copies=1,
                width=None, height=None):
    """An order item already linked to one or more art files (copies = copies per product)."""
    item = make_item(order, variation, quantity, sku)
    if isinstance(art_paths, (str, Path)):
        art_paths = [art_paths]
    arts = [LinkedArt(id=f"{item.id}-{i}", file_name=Path(p).name, file_reference=str(p),
                      copies_per_product=copies, link_method="manual",
                      width_cm=width, height_cm=height)
            for i, p in enumerate(art_paths)]
    return replace(item, linked_arts=arts, link_status="linked")


def make_art_service(path: Path | None = None):
    path = path or Path(tempfile.mkdtemp()) / "dtf_manager.db"
    database = DTFDatabase(path)
    stock_repository = StockRepository(database)
    arts = ArtStockService(ArtStockRepository(database), stock_repository)
    return arts, StockService(stock_repository), path


def sync(arts, folder: Path) -> None:
    arts.sync_folder(folder, list_art_files(folder))


def row_of(arts, name_or_relative):
    for row in arts.snapshot().rows:
        if name_or_relative in (row.name, row.relative_path):
            return row
    return None


__all__ = ["make_folder", "make_art", "linked_item", "make_art_service", "sync", "row_of",
           "make_order", "make_item"]
