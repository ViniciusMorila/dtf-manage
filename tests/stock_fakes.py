"""Helpers shared by the stock tests."""
import tempfile
from itertools import count
from pathlib import Path

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem
from dtf_manager.services.sqlite_database import DTFDatabase
from dtf_manager.services.stock_repository import StockRepository
from dtf_manager.services.stock_service import StockService
from dtf_manager.utils.spreadsheet_values import normalize_variation

_ids = count(1)


def make_item(order, variation, quantity=1, sku="SKU-1", listing="L1", variant="V1", name="Camiseta"):
    n = next(_ids)
    return ImportedOrderItem(
        id=f"i{n}", order_id=f"o-{order}", platform_order_number=order, product_name=name,
        listing_id=listing, sku=sku, variation_raw=variation,
        variation_normalized=normalize_variation(variation), variant_id=variant,
        product_image_url=None, product_price=None, product_quantity=quantity)


def make_order(number, *items):
    """items: (variation, quantity[, sku]) tuples."""
    built = [make_item(number, *item) if isinstance(item, tuple) else item for item in items]
    return ImportedOrder(id=f"o-{number}", platform_order_number=number,
                         upseller_order_number=None, platform=None, store_name=None, items=built)


def make_service(path: Path | None = None):
    path = path or Path(tempfile.mkdtemp()) / "dtf_manager.db"
    repository = StockRepository(DTFDatabase(path))
    return StockService(repository), path


def ids(service):
    snap = service.snapshot()
    return ({c.name: c.id for c in snap.colors}, {s.name: s.id for s in snap.sizes})


def stock_of(service, color, size):
    colors, sizes = ids(service)
    return service.snapshot().stock.get((colors[color], sizes[size]), 0)


def future_of(service, color, size):
    colors, sizes = ids(service)
    return service.snapshot().future.get((colors[color], sizes[size]), 0)


def do_import(service, orders, file_name="a.xlsx", file_hash="h1", decisions=None, excluded=()):
    prep = service.prepare_import(orders, excluded)
    return service.commit_import(prep, decisions or {}, file_name, file_hash), prep
