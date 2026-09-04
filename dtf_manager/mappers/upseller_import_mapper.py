from typing import Any
from uuid import uuid4

from dtf_manager.core.upseller_columns import UPSELLER_COLUMNS
from dtf_manager.models.imported_order import ImportedOrderItem
from dtf_manager.utils.spreadsheet_values import (
    normalize_variation,
    nullable_text,
    parse_optional_price,
    parse_positive_integer,
    text_value,
)


class InvalidOrderRowError(ValueError):
    pass


def map_upseller_row(row: dict[str, Any], row_number: int) -> ImportedOrderItem:
    get = lambda key: row.get(UPSELLER_COLUMNS[key])
    platform_order_number = text_value(get("platform_order_number"))
    product_name = text_value(get("product_name"))
    listing_id = text_value(get("listing_id"))
    sku = text_value(get("sku"))
    variation_raw = text_value(get("variation"))

    missing = next(
        (label for label, value in (
            (UPSELLER_COLUMNS["platform_order_number"], platform_order_number),
            (UPSELLER_COLUMNS["product_name"], product_name),
            (UPSELLER_COLUMNS["listing_id"], listing_id),
            (UPSELLER_COLUMNS["sku"], sku),
            (UPSELLER_COLUMNS["variation"], variation_raw),
        ) if not value),
        None,
    )
    if missing:
        raise InvalidOrderRowError(f'Linha {row_number}: o campo "{missing}" está vazio.')
    try:
        quantity = parse_positive_integer(get("product_quantity"))
    except ValueError as error:
        raise InvalidOrderRowError(
            f'Linha {row_number}: "{UPSELLER_COLUMNS["product_quantity"]}" deve ser um número inteiro positivo.'
        ) from error

    return ImportedOrderItem(
        id=str(uuid4()),
        order_id="",
        platform_order_number=platform_order_number,
        product_name=product_name,
        listing_id=listing_id,
        sku=sku,
        variation_raw=variation_raw,
        variation_normalized=normalize_variation(variation_raw),
        variant_id=nullable_text(get("variant_id")),
        product_image_url=nullable_text(get("product_image_url")),
        product_price=parse_optional_price(get("product_price")),
        product_quantity=quantity,
        linked_arts=[],
        link_status="unlinked",
    )

