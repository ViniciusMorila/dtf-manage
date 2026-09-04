from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.services.active_operation_service import build_import_operation_fingerprint, create_active_operation
from dtf_manager.services.link_memory_repository import SqliteProductLinkMemoryRepository
from dtf_manager.services.link_memory_service import ArtLinkMemoryService, identity_from_item
from dtf_manager.services.processed_order_repository import ProcessedOrderRepository
from dtf_manager.services.sqlite_active_operation_repository import SqliteActiveOperationRepository
from dtf_manager.services.sqlite_database import DTFDatabase


def sample_item():
    return ImportedOrderItem(
        "item", "order", "PED-1", "Produto", "ANUNCIO", "00123",
        "Preto,G", "preto,g", "VAR", None, None, 2,
        [LinkedArt("art", "frente.png", "C:/artes/frente.png", 3, "manual", 28, 36.2, "black")],
        "linked",
    )


class SqliteStorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.database = DTFDatabase(Path(self.folder.name) / "dtf_manager.db")

    def tearDown(self):
        self.folder.cleanup()

    def test_memory_is_normalized_and_roundtrips_dimensions(self):
        repository = SqliteProductLinkMemoryRepository(self.database)
        service = ArtLinkMemoryService(repository)
        item = sample_item()
        service.remember_item(item, "C:/artes")
        loaded = repository.find_for_identity(identity_from_item(item))
        self.assertIsNotNone(loaded)
        self.assertEqual((3, 28, 36.2), (
            loaded.arts[0].copies_per_product, loaded.arts[0].width_cm, loaded.arts[0].height_cm
        ))
        self.assertEqual("black", loaded.arts[0].color_mode)
        with self.database.transaction() as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM product_link_memory").fetchone()[0])
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM product_link_arts").fetchone()[0])

    def test_active_operation_is_singleton(self):
        repository = SqliteActiveOperationRepository(self.database)
        order = ImportedOrder("order", "PED-1", None, None, None, [sample_item()])
        operation = create_active_operation([order], build_import_operation_fingerprint([order]), "a.xlsx")
        repository.save_active(operation)
        self.assertEqual(operation.id, repository.load_active().id)
        repository.clear_active()
        self.assertIsNone(repository.load_active())

    def test_processed_order_stores_only_number_hash_and_date(self):
        repository = ProcessedOrderRepository(self.database)
        order = ImportedOrder("order", "PED-1", None, None, None, [sample_item()])
        repository.record([order], "2026-09-04T10:00:00Z")
        self.assertEqual("already_processed", repository.status(order))
        record = repository.get("PED-1")
        self.assertEqual(64, len(record.fingerprint))


if __name__ == "__main__":
    unittest.main()
