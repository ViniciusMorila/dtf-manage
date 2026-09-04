from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dtf_manager.models.active_operation import ManualLinkingSessionSnapshot
from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.services.active_operation_repository import JsonActiveOperationRepository
from dtf_manager.services.active_operation_service import (
    build_import_operation_fingerprint, checkpoint_operation, create_active_operation,
)


class ActiveOperationTests(unittest.TestCase):
    def item(self, identity, quantity=1, variant=None, arts=None):
        return ImportedOrderItem(
            identity, "order", "ORDER", "Produto", "LIST", identity,
            "Preto, G", "preto,g", variant, None, None, quantity,
            arts or [], "linked" if arts else "unlinked",
        )

    def order(self, number, items):
        return ImportedOrder(number, number, None, "Shopee", "Loja", items)

    def test_fingerprint_ignores_order_and_item_order(self):
        a = self.order("A", [self.item("001234"), self.item("KIT - TENHO SEDE DA TUA GRAÇA", variant="V")])
        b = self.order("B", [self.item("B")])
        first = build_import_operation_fingerprint([a, b])
        reordered = build_import_operation_fingerprint([
            b, replace(a, items=list(reversed(a.items)))
        ])
        self.assertEqual(first, reordered)

    def test_fingerprint_changes_with_quantity_not_file_name(self):
        order = self.order("A", [self.item("SKU")])
        self.assertNotEqual(
            build_import_operation_fingerprint([order]),
            build_import_operation_fingerprint([replace(order, items=[self.item("SKU", 2)])]),
        )

    def test_repository_roundtrip_preserves_links_dimensions_and_manual_position(self):
        with TemporaryDirectory() as folder:
            art = LinkedArt("art", "frente.png", "C:/artes/frente.png", 2, "manual", 28, 36.2)
            orders = [self.order("A", [self.item("A", arts=[art]), self.item("B")])]
            operation = create_active_operation(
                orders, build_import_operation_fingerprint(orders), "pedidos.xlsx"
            )
            manual = ManualLinkingSessionSnapshot(("A", "B"), "B", 1, ("A",), "queue")
            operation = checkpoint_operation(operation, orders, "manual_linking", manual)
            repository = JsonActiveOperationRepository(Path(folder) / "active_operation.json")
            repository.save_active(operation)
            loaded = repository.load_active()
            self.assertIsNotNone(loaded)
            self.assertEqual("B", loaded.manual_linking_state.current_item_id)
            restored = loaded.imported_orders[0].items[0].linked_arts[0]
            self.assertEqual((2, 28, 36.2), (
                restored.copies_per_product, restored.width_cm, restored.height_cm
            ))
            repository.clear_active()
            self.assertIsNone(repository.load_active())

    def test_corrupt_state_does_not_break_loading(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "active_operation.json"
            path.write_text("{broken", encoding="utf-8")
            repository = JsonActiveOperationRepository(path)
            self.assertIsNone(repository.load_active())
            self.assertIsNotNone(repository.load_warning)


if __name__ == "__main__":
    unittest.main()
