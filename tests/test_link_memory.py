import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from dtf_manager.models.automatic_link import ArtCandidate
from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.services.automatic_art_linker import auto_link_orders
from dtf_manager.services.link_memory_repository import (
    ProductLinkMemoryRepository, build_product_memory_key,
)
from dtf_manager.services.link_memory_service import ArtLinkMemoryService, identity_from_item
from dtf_manager.utils.art_matching import matching_tokens, normalize_for_matching


def item(
    listing="111", sku="SKU-A", variant="999", variation="Preta,G",
    arts=None, status="unlinked", product_name="Produto de referência", quantity=1,
):
    return ImportedOrderItem(
        "item", "order", "ORDER", product_name, listing, sku, variation,
        normalize_for_matching(variation), variant, None, None, quantity,
        arts or [], status,
    )


def linked(path: Path, copies=1, method="manual"):
    return LinkedArt(str(path), path.name, str(path.resolve()), copies, method)


def order_with(value):
    return [ImportedOrder("order", "ORDER", None, None, None, [value])]


def candidate(name: str):
    return ArtCandidate(
        name, name, Path(name).stem,
        normalize_for_matching(name, remove_extension=True), Path(name).suffix,
        f"C:/{name}", name, matching_tokens(name, remove_extension=True),
    )


class LinkMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.repository = ProductLinkMemoryRepository(self.folder / "memory.json")
        self.service = ArtLinkMemoryService(self.repository)
        self.art_path = self.folder / "approved.png"
        Image.new("RGBA", (2, 2)).save(self.art_path)

    def tearDown(self):
        self.temporary.cleanup()

    def remember(self, value=None, copies=1, method="manual"):
        value = value or item()
        confirmed = replace(
            value,
            linked_arts=[linked(self.art_path, copies, method)],
            link_status="linked",
        )
        return confirmed, self.service.remember_item(confirmed, str(self.folder))

    def test_exact_memory_is_applied_before_filename_heuristic(self):
        value, _ = self.remember(copies=2)
        fresh = replace(value, linked_arts=[], link_status="unlinked", product_quantity=7)
        outcome = auto_link_orders(
            order_with(fresh), (candidate("SKU-A-other.png"),), self.service, str(self.folder)
        )
        restored = outcome.orders[0].items[0]
        self.assertEqual("linked", restored.link_status)
        self.assertEqual("memory", restored.linked_arts[0].link_method)
        self.assertEqual(2, restored.linked_arts[0].copies_per_product)
        self.assertEqual(7, restored.product_quantity)
        self.assertEqual(1, outcome.memory_linked_count)

    def test_different_variation_sku_or_variant_does_not_exact_match(self):
        self.remember()
        variants = (
            item(variation="Branca,G"),
            item(sku="SKU-B"),
            item(variant="888"),
        )
        for changed in variants:
            with self.subTest(item=changed):
                self.assertEqual("not_found", self.service.find_and_resolve(changed).status)

    def test_missing_variant_can_match_when_reduced_identity_is_unambiguous(self):
        self.remember(item(variant=None))
        self.assertEqual("matched", self.service.find_and_resolve(item(variant="999")).status)

    def test_reduced_identity_with_multiple_variant_memories_is_ambiguous(self):
        self.remember(item(variant="111"))
        other_art = self.folder / "other.png"
        Image.new("RGBA", (2, 2)).save(other_art)
        second = replace(
            item(variant="222"), linked_arts=[linked(other_art)], link_status="linked"
        )
        self.service.remember_item(second)
        self.assertEqual("not_found", self.service.find_and_resolve(item(variant=None)).status)

    def test_product_name_is_not_part_of_identity(self):
        self.remember(item(product_name="Título antigo"))
        self.assertEqual(
            "matched", self.service.find_and_resolve(item(product_name="Título novo")).status
        )

    def test_null_and_empty_variant_have_distinct_deterministic_keys(self):
        null_key = build_product_memory_key(identity_from_item(item(variant=None)))
        empty_key = build_product_memory_key(identity_from_item(item(variant="")))
        self.assertNotEqual(null_key, empty_key)
        self.assertEqual(null_key, build_product_memory_key(identity_from_item(item(variant=None))))

    def test_missing_memory_file_is_diagnostic_then_filename_matcher_runs(self):
        remembered, _ = self.remember()
        self.art_path.unlink()
        fresh = replace(remembered, linked_arts=[], link_status="unlinked", sku="SKU-A")
        outcome = auto_link_orders(
            order_with(fresh), (candidate("SKU-A.png"),), self.service, str(self.folder)
        )
        self.assertEqual("linked", outcome.results[0].status)
        self.assertEqual("memory_file_missing", outcome.results[0].memory_diagnostic)
        self.assertEqual("automatic", outcome.orders[0].items[0].linked_arts[0].link_method)

    def test_multiple_arts_and_copies_are_persisted_and_restored(self):
        second = self.folder / "back.png"
        Image.new("RGBA", (2, 2)).save(second)
        value = replace(item(), linked_arts=[linked(self.art_path, 2), linked(second, 1)], link_status="linked")
        self.service.remember_item(value, str(self.folder))
        match = self.service.find_and_resolve(item(), str(self.folder))
        self.assertEqual("matched", match.status)
        self.assertEqual([2, 1], [art.copies_per_product for art in match.arts])

    def test_updating_memory_replaces_art_without_duplicate_identity(self):
        value, first = self.remember()
        replacement = self.folder / "replacement.png"
        Image.new("RGBA", (2, 2)).save(replacement)
        updated = replace(value, linked_arts=[linked(replacement)])
        second = self.service.remember_item(updated, str(self.folder))
        self.assertEqual(first.id, second.id)
        self.assertEqual(1, len(self.repository.list_all()))
        self.assertEqual("replacement.png", self.repository.list_all()[0].arts[0].file_name)

    def test_delete_and_remove_all_prevent_future_application(self):
        value, memory = self.remember()
        self.repository.delete(memory.id)
        self.assertEqual("not_found", self.service.find_and_resolve(item()).status)
        self.service.remember_item(value)
        self.service.remember_item(replace(value, linked_arts=[], link_status="unlinked"))
        self.assertEqual((), self.repository.list_all())

    def test_unconfirmed_automatic_does_not_create_memory_but_confirmation_does(self):
        automatic_item = replace(
            item(), linked_arts=[linked(self.art_path, method="automatic")], link_status="linked"
        )
        self.assertEqual((), self.repository.list_all())
        memory = self.service.remember_item(automatic_item)
        self.assertEqual("confirmed-auto", memory.source)

    def test_manual_memory_source(self):
        _, memory = self.remember(method="manual")
        self.assertEqual("manual", memory.source)

    def test_persistence_survives_repository_reload_and_has_schema_version(self):
        self.remember()
        reloaded = ProductLinkMemoryRepository(self.folder / "memory.json")
        self.assertEqual(1, len(reloaded.list_all()))
        payload = json.loads((self.folder / "memory.json").read_text(encoding="utf-8"))
        self.assertEqual(1, payload["schemaVersion"])

    def test_relative_path_recovers_art_after_root_moves(self):
        nested = self.folder / "old" / "category"
        nested.mkdir(parents=True)
        old_art = nested / "design.png"
        Image.new("RGBA", (2, 2)).save(old_art)
        value = replace(item(), linked_arts=[linked(old_art)], link_status="linked")
        self.service.remember_item(value, str(self.folder / "old"))
        new_root = self.folder / "new"
        (self.folder / "old").rename(new_root)
        match = self.service.find_and_resolve(item(), str(new_root))
        self.assertEqual("matched", match.status)
        self.assertTrue(Path(match.arts[0].file_reference).is_file())

    def test_corrupt_storage_is_backed_up_without_crashing(self):
        storage = self.folder / "corrupt.json"
        storage.write_text("not json", encoding="utf-8")
        repository = ProductLinkMemoryRepository(storage)
        self.assertIsNotNone(repository.load_warning)
        self.assertEqual((), repository.list_all())
        self.assertEqual(1, len(list(self.folder.glob("corrupt.corrupt-*.bak"))))


if __name__ == "__main__":
    unittest.main()
