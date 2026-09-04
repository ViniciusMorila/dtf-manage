from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.models.print_plan import DTFOrderPlan, DTFPrintPlanItem
from dtf_manager.services.print_plan_service import build_dtf_print_plan
from dtf_manager.services.production_validation_service import validate_production_plan


class ProductionValidationTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "art.png"
        Image.new("RGBA", (2, 2)).save(self.path)

    def art(self, **changes):
        value = LinkedArt("a1", "art.png", str(self.path), 1, "manual")
        return replace(value, **changes)

    def item(self, **changes):
        value = ImportedOrderItem(
            "i1", "o1", "PED-1", "Produto", "listing", "sku", "var", "var",
            None, None, 10.0, 1, [self.art()], "linked",
        )
        return replace(value, **changes)

    def orders(self, item=None):
        return [ImportedOrder("o1", "PED-1", None, None, None, [item or self.item()])]

    def validate(self, item=None, plan=None):
        orders = self.orders(item)
        if plan is None:
            try:
                plan = build_dtf_print_plan(orders, validate_files=False)
            except ValueError:
                plan = None
        return validate_production_plan(orders, plan)

    def codes(self, result, severity="errors"):
        return {issue.code for issue in getattr(result, severity)}

    def test_unlinked_item_is_error(self):
        self.assertIn("UNLINKED_ITEM", self.codes(self.validate(self.item(link_status="unlinked"))))

    def test_linked_without_arts_is_error(self):
        self.assertIn("EMPTY_LINKED_ARTS", self.codes(self.validate(self.item(linked_arts=[]))))

    def test_invalid_product_quantity_is_error(self):
        self.assertIn("INVALID_PRODUCT_QUANTITY", self.codes(self.validate(self.item(product_quantity=0))))

    def test_invalid_copies_per_product_is_error(self):
        item = self.item(linked_arts=[self.art(copies_per_product=0)])
        result = self.validate(item)
        self.assertIn("INVALID_COPIES_PER_PRODUCT", self.codes(result))
        self.assertIn("INVALID_FINAL_COPIES", self.codes(result))

    def test_missing_reference_is_error(self):
        result = self.validate(self.item(linked_arts=[self.art(file_reference=None)]))
        self.assertIn("MISSING_FILE_REFERENCE", self.codes(result))

    def test_missing_file_is_error(self):
        missing = str(Path(self.folder.name) / "missing.png")
        result = self.validate(self.item(linked_arts=[self.art(file_reference=missing)]))
        self.assertIn("FILE_NOT_FOUND", self.codes(result))

    def test_duplicate_art_in_same_item_is_error(self):
        result = self.validate(self.item(linked_arts=[self.art(), self.art(id="a2")]))
        self.assertIn("DUPLICATE_LINKED_ART", self.codes(result))

    def test_unconfirmed_automatic_is_warning(self):
        result = self.validate(self.item(linked_arts=[self.art(link_method="automatic")]))
        self.assertIn("UNCONFIRMED_AUTO_LINK", self.codes(result, "warnings"))
        confirmed = self.validate(self.item(
            linked_arts=[self.art(link_method="automatic")], automatic_links_confirmed=True
        ))
        self.assertNotIn("UNCONFIRMED_AUTO_LINK", self.codes(confirmed, "warnings"))

    def test_manual_and_memory_do_not_need_confirmation(self):
        for method in ("manual", "memory"):
            result = self.validate(self.item(linked_arts=[self.art(link_method=method)]))
            self.assertNotIn("UNCONFIRMED_AUTO_LINK", self.codes(result, "warnings"))

    def test_high_total_is_warning_not_error(self):
        result = self.validate(self.item(product_quantity=20))
        self.assertIn("HIGH_TOTAL_COPIES", self.codes(result, "warnings"))
        self.assertNotIn("HIGH_TOTAL_COPIES", self.codes(result))

    def test_same_filename_different_files_warns_without_aggregation(self):
        other = Path(self.folder.name) / "nested" / "art.png"
        other.parent.mkdir()
        Image.new("RGBA", (2, 2)).save(other)
        item = self.item(linked_arts=[self.art(), self.art(id="a2", file_reference=str(other))])
        orders = self.orders(item)
        plan = build_dtf_print_plan(orders)
        result = validate_production_plan(orders, plan)
        self.assertEqual(2, len(plan.arts))
        self.assertIn("DUPLICATE_FILENAME_DIFFERENT_FILE", self.codes(result, "warnings"))

    def test_formula_and_consistent_total(self):
        item = self.item(product_quantity=3, linked_arts=[self.art(copies_per_product=2)])
        plan = build_dtf_print_plan(self.orders(item))
        result = validate_production_plan(self.orders(item), plan)
        self.assertEqual(6, plan.arts[0].total_copies)
        self.assertEqual(6, plan.total_print_copies)
        self.assertNotIn("PRINT_PLAN_TOTAL_MISMATCH", self.codes(result))

    def test_total_mismatch_blocks_production(self):
        art = DTFPrintPlanItem("p1", "art.png", str(self.path), 12, ("i1",), ("PED-1",))
        plan = DTFOrderPlan(1, 1, 11, (art,))
        result = validate_production_plan(self.orders(), plan)
        self.assertIn("PRINT_PLAN_TOTAL_MISMATCH", self.codes(result))
        self.assertFalse(result.is_valid)

    def test_clean_plan_is_ready(self):
        result = self.validate()
        self.assertTrue(result.is_valid)
        self.assertEqual("ready", result.status)
        self.assertEqual((), result.errors)
        self.assertEqual((), result.warnings)


if __name__ == "__main__":
    unittest.main()
