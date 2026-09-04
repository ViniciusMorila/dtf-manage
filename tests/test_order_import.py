import unittest
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook

from dtf_manager.core.upseller_columns import UPSELLER_COLUMNS
from dtf_manager.mappers.upseller_import_mapper import InvalidOrderRowError, map_upseller_row
from dtf_manager.services.order_import_service import OrderImportError, group_order_items, parse_xlsx


def row(order="A", product="Produto", listing="10", sku="SKU", variation="M", quantity=1, **extra):
    data = {
        UPSELLER_COLUMNS["platform_order_number"]: order,
        UPSELLER_COLUMNS["product_name"]: product,
        UPSELLER_COLUMNS["listing_id"]: listing,
        UPSELLER_COLUMNS["sku"]: sku,
        UPSELLER_COLUMNS["variation"]: variation,
        UPSELLER_COLUMNS["product_quantity"]: quantity,
    }
    data.update({UPSELLER_COLUMNS[key]: value for key, value in extra.items()})
    return data


class OrderImportTests(unittest.TestCase):
    def group(self, rows):
        items = [map_upseller_row(value, index + 2) for index, value in enumerate(rows)]
        return group_order_items(items, rows)

    def test_groups_two_and_three_lines_of_same_order(self):
        self.assertEqual([2], [len(o.items) for o in self.group([row(product="1"), row(product="2")])])
        self.assertEqual([3], [len(o.items) for o in self.group([row(product=str(i)) for i in range(3)])])

    def test_three_distinct_orders(self):
        self.assertEqual(3, len(self.group([row(order=value) for value in "ABC"])))

    def test_skus_are_preserved_as_strings(self):
        for sku in ("KIT - TENHO SEDE DA TUA GRAÇA", "189193446214", "001234567"):
            self.assertEqual(sku, map_upseller_row(row(sku=sku), 2).sku)

    def test_sku_and_variant_are_independent(self):
        item = map_upseller_row(row(sku="KIT - TENHO SEDE DA TUA GRAÇA", variant_id="189193446214"), 2)
        self.assertEqual("KIT - TENHO SEDE DA TUA GRAÇA", item.sku)
        self.assertEqual("189193446214", item.variant_id)

    def test_variation_raw_is_preserved_and_normalized(self):
        item = map_upseller_row(row(variation="Bege,P  -  M"), 2)
        self.assertEqual("Bege,P  -  M", item.variation_raw)
        self.assertEqual("bege,p - m", item.variation_normalized)

    def test_positive_quantities(self):
        for quantity in (1, 2, 3):
            self.assertEqual(quantity, map_upseller_row(row(quantity=quantity), 2).product_quantity)

    def test_invalid_quantities(self):
        for quantity in (0, -2, "abc", ""):
            with self.subTest(quantity=quantity), self.assertRaises(InvalidOrderRowError):
                map_upseller_row(row(quantity=quantity), 2)

    def test_empty_image_is_allowed_and_links_start_empty(self):
        item = map_upseller_row(row(product_image_url=""), 2)
        self.assertIsNone(item.product_image_url)
        self.assertEqual([], item.linked_arts)
        self.assertEqual("unlinked", item.link_status)

    def test_equal_product_names_with_different_listing_ids_remain_two_items(self):
        orders = self.group([row(listing="1"), row(listing="2")])
        self.assertEqual(["1", "2"], [item.listing_id for item in orders[0].items])

    def test_xlsx_ignores_empty_rows_and_finds_valid_second_sheet(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "orders.xlsx"
            workbook = Workbook()
            workbook.active.append(["Capa sem dados"])
            sheet = workbook.create_sheet("Pedidos")
            sheet.append(list(UPSELLER_COLUMNS.values()))
            sheet.append([None] * len(UPSELLER_COLUMNS))
            valid = row()
            sheet.append([valid.get(name) for name in UPSELLER_COLUMNS.values()])
            workbook.save(path)
            self.assertEqual(1, len(parse_xlsx(path)))

    def test_missing_required_platform_order_column_is_reported(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.xlsx"
            workbook = Workbook()
            headers = [name for name in UPSELLER_COLUMNS.values() if name != UPSELLER_COLUMNS["platform_order_number"]]
            workbook.active.append(headers)
            workbook.save(path)
            with self.assertRaisesRegex(OrderImportError, "Nº de Pedido da Plataforma"):
                parse_xlsx(path)

    def test_xlsx_with_incorrect_a1_dimension_reads_actual_cells(self):
        """Regression: real UpSeller exports may declare A1 despite A1:Pn data."""
        with TemporaryDirectory() as folder:
            path = Path(folder) / "wrong-dimension.xlsx"
            rebuilt_path = Path(folder) / "rebuilt.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            headers = list(UPSELLER_COLUMNS.values()) + ["NCM*", "Origem*", "Unidade*", "Imposto*"]
            sheet.append(headers)
            for order_number in ("A", "B"):
                data = row(order=order_number)
                sheet.append([data.get(name) for name in headers])
            workbook.save(path)

            with ZipFile(path, "r") as source, ZipFile(rebuilt_path, "w", ZIP_DEFLATED) as target:
                for entry in source.infolist():
                    payload = source.read(entry.filename)
                    if entry.filename == "xl/worksheets/sheet1.xml":
                        payload, replacements = re.subn(
                            br'<dimension ref="[^"]+"\s*/>',
                            b'<dimension ref="A1"/>',
                            payload,
                            count=1,
                        )
                        self.assertEqual(1, replacements)
                    target.writestr(entry, payload)
            rebuilt_path.replace(path)

            records = parse_xlsx(path)
            self.assertEqual(2, len(records))
            self.assertEqual(set(headers), set(records[0]))
            self.assertEqual("B", records[1][UPSELLER_COLUMNS["platform_order_number"]])


if __name__ == "__main__":
    unittest.main()
