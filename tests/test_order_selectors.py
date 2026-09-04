import unittest

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem
from dtf_manager.state.order_selectors import (
    ItemLinkFilter,
    filter_order_items,
    get_all_items,
    get_import_metrics,
    get_order_link_status,
)


def item(item_id: str, status: str = "unlinked", order="A", sku="SKU", product="Produto") -> ImportedOrderItem:
    return ImportedOrderItem(
        id=item_id,
        order_id=order,
        platform_order_number=order,
        product_name=product,
        listing_id=f"listing-{item_id}",
        sku=sku,
        variation_raw="Bege,G - GG",
        variation_normalized="bege,g - gg",
        variant_id=None,
        product_image_url=None,
        product_price=None,
        product_quantity=1,
        linked_arts=[],
        link_status=status,
    )


def order(number: str, items: list[ImportedOrderItem]) -> ImportedOrder:
    return ImportedOrder(number, number, None, None, None, items)


class OrderSelectorTests(unittest.TestCase):
    def test_order_and_item_counts(self):
        orders = (order("A", [item("1"), item("2")]), order("B", [item("3", order="B")]))
        metrics = get_import_metrics(orders)
        self.assertEqual(2, metrics.order_count)
        self.assertEqual(3, metrics.item_count)

    def test_progress_for_unlinked_partial_linked_and_empty(self):
        cases = ((["unlinked"] * 3, (0, 3, 0.0)), (["linked", "linked", "unlinked"], (2, 1, 200 / 3)), (["linked"] * 3, (3, 0, 100.0)), ([], (0, 0, 0.0)))
        for statuses, expected in cases:
            with self.subTest(statuses=statuses):
                orders = (order("A", [item(str(index), status) for index, status in enumerate(statuses)]),) if statuses else ()
                metrics = get_import_metrics(orders)
                self.assertEqual(expected[0], metrics.linked_count)
                self.assertEqual(expected[1], metrics.unlinked_count)
                self.assertAlmostEqual(expected[2], metrics.progress_percent)

    def test_link_filters_only_return_requested_status(self):
        items = (item("1", "linked"), item("2"), item("3", "linked"))
        self.assertTrue(all(value.link_status == "linked" for value in filter_order_items(items, ItemLinkFilter.LINKED)))
        self.assertTrue(all(value.link_status == "unlinked" for value in filter_order_items(items, ItemLinkFilter.UNLINKED)))

    def test_searches_textual_sku_order_product_and_is_accent_insensitive(self):
        target = item("1", order="260831S53JCCWE", sku="KIT - TENHO SEDE DA TUA GRAÇA", product="Camiseta Yeshua")
        items = (target, item("2"))
        for query in ("TENHO SEDE", "260831s53jccwe", "yeshua", "graca"):
            self.assertEqual((target,), filter_order_items(items, query=query))

    def test_null_image_is_valid_model_data(self):
        self.assertIsNone(item("1").product_image_url)

    def test_partial_order_status_is_derived(self):
        value = order("A", [item("1", "linked"), item("2", "linked"), item("3")])
        self.assertEqual("partial", get_order_link_status(value))
        self.assertEqual(3, len(get_all_items((value,))))


if __name__ == "__main__":
    unittest.main()
