from collections import OrderedDict
from dataclasses import replace
import logging
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.utils.exceptions import InvalidFileException

from dtf_manager.core.upseller_columns import REQUIRED_UPSELLER_COLUMNS, UPSELLER_COLUMNS
from dtf_manager.mappers.upseller_import_mapper import InvalidOrderRowError, map_upseller_row
from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem
from dtf_manager.utils.spreadsheet_values import normalize_header


LOGGER = logging.getLogger(__name__)


class OrderImportError(ValueError):
    pass


def _cell_value(cell: Cell) -> Any:
    value = cell.value
    # Preserve leading zeroes when Excel stores an identifier as a number with
    # an all-zero display format (for example 001234567).
    if isinstance(value, (int, float)) and set(cell.number_format) <= {"0"}:
        return f"{int(value):0{len(cell.number_format)}d}"
    return value


def parse_xlsx(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() != ".xlsx":
        raise OrderImportError("Formato não suportado. Selecione um arquivo .xlsx.")
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except (OSError, InvalidFileException, ValueError, KeyError) as error:
        raise OrderImportError("Não foi possível ler este arquivo.") from error
    try:
        if not workbook.sheetnames:
            raise OrderImportError("Esta planilha está vazia.")
        missing_best: list[str] | None = None
        for sheet in workbook.worksheets:
            declared_dimension = sheet.calculate_dimension()
            # Read-only worksheets normally use the dimension metadata as the
            # iteration boundary. UpSeller exports can incorrectly declare A1
            # while their XML contains many more cells. reset_dimensions() is
            # openpyxl's supported way to make the streaming reader discover
            # bounds from the actual worksheet records.
            sheet.reset_dimensions()
            rows = sheet.iter_rows()
            for header_index, cells in enumerate(rows):
                headers = [normalize_header(cell.value) for cell in cells]
                if not any(headers):
                    continue
                missing = [name for name in REQUIRED_UPSELLER_COLUMNS if name not in headers]
                if missing:
                    LOGGER.debug(
                        "UpSeller worksheet candidate: sheet=%r declared_dimension=%s "
                        "detected_row=%d detected_columns=%d headers=%r missing=%r",
                        sheet.title,
                        declared_dimension,
                        header_index + 1,
                        len(cells),
                        [header for header in headers if header],
                        missing,
                    )
                    if missing_best is None or len(missing) < len(missing_best):
                        missing_best = missing
                    if header_index < 49:
                        continue
                    break
                records: list[dict[str, Any]] = []
                for row_cells in rows:
                    values = [_cell_value(cell) for cell in row_cells]
                    if not any(value is not None and str(value).strip() for value in values):
                        continue
                    records.append({
                        header: values[index] if index < len(values) else None
                        for index, header in enumerate(headers)
                        if header
                    })
                LOGGER.debug(
                    "UpSeller worksheet accepted: sheet=%r declared_dimension=%s "
                    "header_row=%d detected_columns=%d data_rows=%d headers=%r",
                    sheet.title,
                    declared_dimension,
                    header_index + 1,
                    len(headers),
                    len(records),
                    [header for header in headers if header],
                )
                return records
        if missing_best:
            raise OrderImportError(
                "Não foi possível identificar todas as colunas necessárias da UpSeller. "
                f"Colunas não encontradas: {', '.join(missing_best)}."
            )
        raise OrderImportError("Este arquivo não parece ser uma planilha válida da UpSeller.")
    finally:
        workbook.close()


def group_order_items(items: Iterable[ImportedOrderItem], rows: Iterable[dict[str, Any]]) -> list[ImportedOrder]:
    groups: OrderedDict[str, tuple[str, list[ImportedOrderItem], dict[str, Any]]] = OrderedDict()
    for item, row in zip(items, rows):
        if item.platform_order_number not in groups:
            groups[item.platform_order_number] = (str(uuid4()), [], row)
        order_id, grouped_items, first_row = groups[item.platform_order_number]
        grouped_items.append(replace(item, order_id=order_id))

    orders: list[ImportedOrder] = []
    for platform_number, (order_id, grouped_items, row) in groups.items():
        def optional(key: str) -> str | None:
            value = row.get(UPSELLER_COLUMNS[key])
            normalized = "" if value is None else str(value).strip()
            return normalized or None
        orders.append(ImportedOrder(
            id=order_id,
            platform_order_number=platform_number,
            upseller_order_number=optional("upseller_order_number"),
            platform=optional("platform"),
            store_name=optional("store_name"),
            items=grouped_items,
        ))
    return orders


def import_upseller_orders(path: Path) -> list[ImportedOrder]:
    rows = parse_xlsx(path)
    if not rows:
        raise OrderImportError("Não foi possível encontrar pedidos nesta planilha.")
    try:
        items = [map_upseller_row(row, number) for number, row in enumerate(rows, start=2)]
    except InvalidOrderRowError as error:
        raise OrderImportError(str(error)) from error
    orders = group_order_items(items, rows)
    if not orders:
        raise OrderImportError("Não foi possível encontrar pedidos nesta planilha.")
    return orders
