"""Manual linking session: it only walks through (and counts) the products that are still unlinked."""
import os
from pathlib import Path
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.state.order_import_state import OrderImportState
from dtf_manager.ui.pages.manual_linking_page import ManualLinkingPage
from dtf_manager.ui.styles import APP_STYLE


def item(item_id, status):
    arts = [LinkedArt(f"/arts/{item_id}.png", f"{item_id}.png", f"/arts/{item_id}.png", 1, "automatic")] \
        if status == "linked" else []
    return ImportedOrderItem(item_id, "order", "ORDER", f"Produto {item_id}", f"listing-{item_id}",
                             f"sku-{item_id}", "M", "m", None, None, None, 1, arts, status)


class SessionCounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE)

    def setUp(self):
        # 8 imported items; 1, 2, 3 and 6 were linked automatically, 4, 5, 7 and 8 are still missing.
        statuses = {"1": "linked", "2": "linked", "3": "linked", "4": "unlinked", "5": "unlinked",
                    "6": "linked", "7": "unlinked", "8": "unlinked"}
        self.state = OrderImportState()
        self.state.replace_orders([ImportedOrder(
            "order", "ORDER", None, None, None, [item(key, value) for key, value in statuses.items()])])
        self.page = ManualLinkingPage(self.state, Mock())
        self.page.show()
        self.addCleanup(self._close)
        self.page.start_queue(tuple(i.id for i in self.state.all_items))

    def _close(self):
        self.app.removeEventFilter(self.page)
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def current(self):
        return self.page._queue.current_item_id

    def test_it_starts_at_the_first_unlinked_product_and_counts_only_the_pending_ones(self):
        self.assertEqual(self.current(), "4")
        self.assertEqual(self.page.position_label.text(), "Produto 1 de 4")
        self.assertEqual(self.page.session_progress.value(), 25)

    def test_skipping_goes_over_the_linked_products(self):
        labels = []
        for _ in range(3):
            self.page._skip()
            labels.append((self.current(), self.page.position_label.text()))
        self.assertEqual(labels[:2], [("5", "Produto 2 de 4"), ("7", "Produto 3 de 4")])   # 6 is skipped
        self.assertEqual(labels[2], ("8", "Produto 4 de 4"))

    def test_the_last_pending_product_says_conclude_even_if_it_is_not_the_last_row(self):
        self.page._queue.index = self.page._queue.item_ids.index("7")
        self.page._load_current()
        self.assertEqual(self.page.save_button.text(), "SALVAR E AVANÇAR")
        self.page._skip()                                                # now on 8, the last pending
        self.assertEqual(self.page.save_button.text(), "SALVAR E CONCLUIR")
        self.assertEqual(self.page.skip_button.text(), "PULAR E CONCLUIR")

    def test_previous_goes_back_only_to_pending_products(self):
        self.page._skip()                                                # 5
        self.page._skip()                                                # 7 (6 is linked)
        self.page._previous()
        self.assertEqual(self.current(), "5")
        self.page._previous()
        self.assertEqual(self.current(), "4")
        self.assertFalse(self.page.previous_button.isEnabled())          # 1-3 are not part of the session
        self.page._previous()
        self.assertEqual(self.current(), "4")

    def test_previous_is_disabled_on_the_first_pending_product(self):
        self.assertFalse(self.page.previous_button.isEnabled())
        self.page._skip()
        self.assertTrue(self.page.previous_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
