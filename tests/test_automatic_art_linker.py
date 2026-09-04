import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from PIL import Image

from dtf_manager.models.automatic_link import ArtCandidate
from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.services.art_directory_scanner import scan_art_directory
from dtf_manager.services.automatic_art_linker import auto_link_orders, find_automatic_art_match
from dtf_manager.utils.art_matching import matching_tokens, normalize_for_matching


def art(name: str, folder: str = "C:/artes") -> ArtCandidate:
    path = f"{folder}/{name}"
    return ArtCandidate(
        id=str(uuid4()),
        file_name=name,
        base_name=Path(name).stem,
        normalized_name=normalize_for_matching(name, remove_extension=True),
        extension=Path(name).suffix.casefold(),
        file_reference=path,
        relative_path=name,
        tokens=matching_tokens(name, remove_extension=True),
    )


def item(
    sku: str,
    variant_id: str | None = None,
    product_name: str = "Produto exclusivo",
    status: str = "unlinked",
    linked_arts: list[LinkedArt] | None = None,
) -> ImportedOrderItem:
    return ImportedOrderItem(
        id=str(uuid4()), order_id="order", platform_order_number="ORDER-1",
        product_name=product_name, listing_id="LISTING-1", sku=sku,
        variation_raw="M", variation_normalized="m", variant_id=variant_id,
        product_image_url=None, product_price=None, product_quantity=1,
        linked_arts=linked_arts or [], link_status=status,
    )


class AutomaticArtLinkerTests(unittest.TestCase):
    def match(self, value: ImportedOrderItem, names: list[str]):
        return find_automatic_art_match(value, tuple(art(name) for name in names))

    def test_exact_textual_and_zero_padded_skus_are_high_confidence(self):
        cases = (
            ("KIT - TENHO SEDE DA TUA GRAÇA", "KIT - TENHO SEDE DA TUA GRAÇA.png"),
            ("001234", "001234.png"),
        )
        for sku, file_name in cases:
            with self.subTest(sku=sku):
                matches, result = self.match(item(sku), [file_name])
                self.assertEqual("linked", result.status)
                self.assertEqual("high", result.confidence)
                self.assertEqual(sku, item(sku).sku)
                self.assertEqual(1, len(matches))

    def test_short_numeric_sku_does_not_match_longer_token(self):
        matches, result = self.match(item("123"), ["1234.png"])
        self.assertEqual((), matches)
        self.assertEqual("not_found", result.status)

    def test_exact_variant_id_is_high_confidence(self):
        matches, result = self.match(item("NO-SKU", "189193446214"), ["189193446214.png"])
        self.assertEqual("linked", result.status)
        self.assertIn("variant ID", result.reason)
        self.assertEqual(1, len(matches))

    def test_variant_id_can_resolve_multiple_sku_candidates(self):
        matches, result = self.match(
            item("SKU123", "VARIANT-2"),
            ["SKU123-opcao-a.png", "SKU123-VARIANT-2.png"],
        )
        self.assertEqual("linked", result.status)
        self.assertEqual("SKU123-VARIANT-2.png", matches[0].file_name)

    def test_no_match_remains_unlinked(self):
        matches, result = self.match(item("ABC"), ["outra-arte.png"])
        self.assertFalse(matches)
        self.assertEqual("not_found", result.status)

    def test_equal_strength_candidates_are_ambiguous(self):
        matches, result = self.match(item("Jesus"), ["jesus-a.png", "jesus-b.png"])
        self.assertFalse(matches)
        self.assertEqual("ambiguous", result.status)

    def test_front_and_back_are_related_arts(self):
        matches, result = self.match(item("SKU123"), ["SKU123 - frente.png", "SKU123 - costas.png"])
        self.assertEqual("linked", result.status)
        self.assertEqual(2, len(matches))

    def test_numbered_files_are_ambiguous(self):
        matches, result = self.match(item("SKU123"), ["SKU123 1.png", "SKU123 2.png"])
        self.assertFalse(matches)
        self.assertEqual("ambiguous", result.status)

    def test_existing_link_is_preserved_and_second_run_does_not_duplicate(self):
        existing = LinkedArt("manual-id", "manual.png", "C:/manual.png", 2, "manual")
        linked_item = item("SKU123", status="linked", linked_arts=[existing])
        orders = [ImportedOrder("order", "ORDER-1", None, None, None, [linked_item])]
        first = auto_link_orders(orders, (art("SKU123.png"),))
        second = auto_link_orders(first.orders, (art("SKU123.png"),))
        preserved = second.orders[0].items[0]
        self.assertEqual([existing], preserved.linked_arts)
        self.assertEqual("preserved", second.results[0].status)

    def test_linked_art_has_original_name_absolute_reference_and_defaults(self):
        candidate = art("SKU123.png")
        value = item("SKU123")
        outcome = auto_link_orders(
            [ImportedOrder("order", "ORDER-1", None, None, None, [value])], (candidate,)
        )
        linked = outcome.orders[0].items[0].linked_arts[0]
        self.assertEqual("SKU123.png", linked.file_name)
        self.assertEqual(candidate.file_reference, linked.file_reference)
        self.assertEqual(1, linked.copies_per_product)
        self.assertEqual("automatic", linked.link_method)

    def test_normalization_is_accent_case_separator_and_extension_insensitive(self):
        left = normalize_for_matching("Tenho Sede da Tua Graça")
        right = normalize_for_matching("tenho_sede_da_tua_graca.PNG", remove_extension=True)
        self.assertEqual(left, right)

    def test_product_name_alone_never_auto_links(self):
        matches, result = self.match(
            item("NO-SKU", product_name="Camiseta Jesus Cristo"), ["Jesus Cristo.png"]
        )
        self.assertFalse(matches)
        self.assertNotEqual("linked", result.status)

    def test_scanner_recurses_and_ignores_unsupported_invalid_and_system_files(self):
        with TemporaryDirectory() as folder_name:
            folder = Path(folder_name)
            nested = folder / "CRISTÃS"
            nested.mkdir()
            Image.new("RGBA", (2, 2)).save(nested / "yeshua.png")
            (folder / "THUMBS.DB").write_text("ignored")
            (folder / "texto.txt").write_text("ignored")
            (folder / "corrompida.png").write_text("not an image")
            candidates = scan_art_directory(folder)
            self.assertEqual(["yeshua.png"], [candidate.file_name for candidate in candidates])
            self.assertEqual("CRISTÃS\\yeshua.png", candidates[0].relative_path)


if __name__ == "__main__":
    unittest.main()
