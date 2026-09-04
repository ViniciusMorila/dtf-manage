import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.services.manual_link_service import (
    ManualLinkQueue, ManualLinkValidationError, create_manual_linked_art,
    update_order_item_links, validate_linked_arts,
)


def item(item_id: str, status="unlinked", arts=None):
    return ImportedOrderItem(
        item_id, "order", "ORDER", f"Produto {item_id}", f"listing-{item_id}",
        f"sku-{item_id}", "M", "m", None, None, None, 1, arts or [], status,
    )


def orders_with(*items):
    return [ImportedOrder("order", "ORDER", None, None, None, list(items))]


def linked_art(reference: str, method="manual", copies=1):
    return LinkedArt(reference, Path(reference).name, reference, copies, method)


class ManualLinkServiceTests(unittest.TestCase):
    def test_queue_snapshot_does_not_skip_when_first_item_becomes_linked(self):
        queue = ManualLinkQueue(("A", "B", "C"))
        self.assertEqual("A", queue.current_item_id)
        self.assertTrue(queue.advance())
        self.assertEqual("B", queue.current_item_id)
        self.assertTrue(queue.advance())
        self.assertEqual("C", queue.current_item_id)

    def test_queue_can_start_at_specific_item_and_go_previous(self):
        queue = ManualLinkQueue(("A", "B", "C"), "B")
        self.assertEqual("B", queue.current_item_id)
        self.assertTrue(queue.previous())
        self.assertEqual("A", queue.current_item_id)

    def test_linking_all_items_leaves_no_unlinked(self):
        orders = orders_with(item("A"), item("B"), item("C"))
        for item_id in ("A", "B", "C"):
            orders, _ = update_order_item_links(orders, item_id, [linked_art(f"C:/{item_id}.png")])
        self.assertTrue(all(value.link_status == "linked" for value in orders[0].items))

    def test_skipped_item_remains_unlinked(self):
        orders = orders_with(item("A"), item("B"), item("C"))
        for item_id in ("A", "C"):
            orders, _ = update_order_item_links(orders, item_id, [linked_art(f"C:/{item_id}.png")])
        self.assertEqual("unlinked", orders[0].items[1].link_status)

    def test_one_or_multiple_manual_arts_are_saved(self):
        for references in (("C:/frente.png",), ("C:/frente.png", "C:/costas.png")):
            with self.subTest(references=references):
                updated, value = update_order_item_links(
                    orders_with(item("A")), "A", [linked_art(ref) for ref in references]
                )
                self.assertEqual(len(references), len(value.linked_arts))
                self.assertEqual("linked", value.link_status)
                self.assertTrue(all(art.link_method == "manual" for art in value.linked_arts))
                self.assertEqual("linked", updated[0].items[0].link_status)

    def test_removing_one_or_all_arts_updates_status(self):
        original = item("A", "linked", [linked_art("C:/frente.png"), linked_art("C:/costas.png")])
        _, one_left = update_order_item_links(orders_with(original), "A", [original.linked_arts[1]])
        self.assertEqual(["costas.png"], [art.file_name for art in one_left.linked_arts])
        _, none_left = update_order_item_links(orders_with(one_left), "A", [])
        self.assertEqual("unlinked", none_left.link_status)

    def test_copies_must_be_positive_and_can_increase(self):
        art = linked_art("C:/art.png")
        for copies in (1, 2, 3):
            self.assertEqual(copies, validate_linked_arts([replace(art, copies_per_product=copies)])[0].copies_per_product)
        with self.assertRaises(ManualLinkValidationError):
            validate_linked_arts([replace(art, copies_per_product=0)])

    def test_duplicate_reference_is_rejected_but_equal_names_in_other_folders_are_allowed(self):
        with self.assertRaises(ManualLinkValidationError):
            validate_linked_arts([linked_art("C:/one/art.png"), linked_art("C:/one/art.png")])
        self.assertEqual(2, len(validate_linked_arts([
            linked_art("C:/one/art.png"), linked_art("C:/two/art.png")
        ])))

    def test_automatic_art_is_preserved_when_saved_unchanged(self):
        automatic = linked_art("C:/automaticArt.png", "automatic")
        _, value = update_order_item_links(
            orders_with(item("A", "linked", [automatic])), "A", [automatic]
        )
        self.assertEqual(automatic, value.linked_arts[0])

    def test_replacement_created_by_picker_is_manual(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "manualArt.png"
            Image.new("RGBA", (2, 2)).save(path)
            art = create_manual_linked_art(path)
            self.assertEqual("manual", art.link_method)
            self.assertEqual(1, art.copies_per_product)
            self.assertEqual(str(path.resolve()), art.file_reference)

    def test_invalid_or_inaccessible_file_is_rejected(self):
        with TemporaryDirectory() as folder:
            invalid = Path(folder) / "invalid.png"
            invalid.write_text("invalid")
            with self.assertRaises(ManualLinkValidationError):
                create_manual_linked_art(invalid)
            with self.assertRaises(ManualLinkValidationError):
                create_manual_linked_art(Path(folder) / "missing.png")


if __name__ == "__main__":
    unittest.main()
