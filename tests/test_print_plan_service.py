import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.services.print_plan_service import (
    PrintPlanValidationError, build_dtf_print_plan, can_build_print_plan,
    prepare_print_plan_for_roll,
)


def art(reference: str, copies=1, name: str | None = None):
    return LinkedArt(reference, name or Path(reference).name, reference, copies, "manual")


def item(item_id: str, quantity=1, arts=None, status="linked"):
    return ImportedOrderItem(
        item_id, item_id, f"ORDER-{item_id}", f"Produto {item_id}", f"listing-{item_id}",
        f"sku-{item_id}", "M", "m", None, None, None, quantity, arts or [], status,
    )


def order(order_id: str, items):
    return ImportedOrder(order_id, f"ORDER-{order_id}", None, None, None, list(items))


class PrintPlanServiceTests(unittest.TestCase):
    def build(self, orders):
        return build_dtf_print_plan(orders, validate_files=False)

    def test_fundamental_quantity_examples(self):
        for product_quantity, copies_per_product, expected in ((1, 1, 1), (3, 1, 3), (2, 3, 6)):
            with self.subTest(values=(product_quantity, copies_per_product)):
                plan = self.build([order("A", [item("A", product_quantity, [art("C:/A.png", copies_per_product)])])])
                self.assertEqual(expected, plan.arts[0].total_copies)
                self.assertEqual(expected, plan.total_print_copies)

    def test_front_and_back_remain_independent(self):
        plan = self.build([order("A", [item("A", 4, [art("C:/frente.png"), art("C:/costas.png")])])])
        self.assertEqual({"frente.png": 4, "costas.png": 4}, {value.file_name: value.total_copies for value in plan.arts})
        self.assertEqual(8, plan.total_print_copies)

    def test_same_reference_is_aggregated_across_orders_with_traceability(self):
        plan = self.build([
            order("A", [item("A", 2, [art("C:/shared.png")])]),
            order("B", [item("B", 3, [art("C:/shared.png")])]),
        ])
        self.assertEqual(1, len(plan.arts))
        self.assertEqual(5, plan.arts[0].total_copies)
        self.assertEqual(("A", "B"), plan.arts[0].source_item_ids)
        self.assertEqual(("ORDER-A", "ORDER-B"), plan.arts[0].source_order_numbers)

    def test_same_filename_different_references_are_not_aggregated(self):
        plan = self.build([order("A", [item("A", arts=[
            art("C:/folder-a/jesus.png"), art("C:/folder-b/jesus.png")
        ])])])
        self.assertEqual(2, len(plan.arts))

    def test_same_art_in_different_colors_remains_separate(self):
        reference = "C:/shared.png"
        black = LinkedArt("black", "shared.png", reference, 1, "manual", 10, 20, "black")
        white = LinkedArt("white", "shared.png", reference, 1, "manual", 10, 20, "white")
        plan = self.build([order("A", [item("A", arts=[black, white])])])
        self.assertEqual(2, len(plan.arts))
        self.assertEqual({"black", "white"}, {value.color_mode for value in plan.arts})

    def test_three_items_multiply_and_aggregate(self):
        plan = self.build([order("A", [
            item("A", 2, [art("C:/shared.png", 2)]),
            item("B", 2, [art("C:/shared.png", 2)]),
            item("C", 2, [art("C:/shared.png", 2)]),
        ])])
        self.assertEqual(12, plan.arts[0].total_copies)

    def test_unlinked_empty_links_and_invalid_quantities_are_rejected(self):
        invalid_items = (
            item("A", arts=[], status="unlinked"),
            item("A", arts=[], status="linked"),
            item("A", arts=[art("C:/A.png", 0)]),
            item("A", quantity=0, arts=[art("C:/A.png")]),
        )
        for invalid in invalid_items:
            with self.subTest(item=invalid), self.assertRaises(PrintPlanValidationError):
                self.build([order("A", [invalid])])

    def test_empty_or_partially_linked_orders_are_not_ready(self):
        self.assertFalse(can_build_print_plan([]))
        mixed = [order("A", [item(str(index), arts=[art(f"C:/{index}.png")]) for index in range(88)] + [item("missing", arts=[], status="unlinked")])]
        self.assertFalse(can_build_print_plan(mixed))
        ready = [order("A", [item(str(index), arts=[art(f"C:/{index}.png")]) for index in range(89)])]
        self.assertTrue(can_build_print_plan(ready))

    def test_missing_file_is_reported_before_roll_application(self):
        with self.assertRaisesRegex(PrintPlanValidationError, "Produto A"):
            build_dtf_print_plan([order("A", [item("A", arts=[art("Z:/missing/art.png")])])])

    def test_plan_can_be_prepared_for_existing_roll_pipeline(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "art.png"
            Image.new("RGBA", (30, 20)).save(path, dpi=(300, 300))
            plan = build_dtf_print_plan([order("A", [item("A", 2, [art(str(path), 2)])])])
            prepared = prepare_print_plan_for_roll(plan, lambda _path: (2.54, 1.27))
            self.assertEqual(1, len(prepared))
            self.assertEqual(4, prepared[0].quantity)
            self.assertEqual((2.54, 1.27), (prepared[0].width_cm, prepared[0].height_cm))


if __name__ == "__main__":
    unittest.main()
