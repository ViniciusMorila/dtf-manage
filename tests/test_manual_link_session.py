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


class PageCase(unittest.TestCase):
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

    def _close(self):
        self.app.removeEventFilter(self.page)
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def current(self):
        return self.page._queue.current_item_id


class SessionCounterTests(PageCase):
    def setUp(self):
        super().setUp()
        self.page.start_queue(tuple(i.id for i in self.state.all_items))

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


class ReviewTests(PageCase):
    """REVISÃO: walks over the products that are already linked, one by one."""

    def setUp(self):
        super().setUp()
        self.done = []
        self.page.review_completed.connect(self.done.append)
        self.linked = tuple(i.id for i in self.state.all_items if i.link_status == "linked")   # 1, 2, 3, 6
        self.page.start_review(self.linked)

    def test_it_shows_the_first_linked_product_with_its_arts_and_a_review_title(self):
        self.assertEqual(self.linked, ("1", "2", "3", "6"))
        self.assertEqual(self.current(), "1")
        self.assertEqual(self.page.title_label.text(), "REVISÃO DOS VÍNCULOS")
        self.assertEqual(self.page.position_label.text(), "Revisão · Produto 1 de 4")
        self.assertEqual([art.file_name for art in self.page._draft if art], ["1.png"])
        self.assertEqual(self.page.save_button.text(), "SALVAR E AVANÇAR")
        self.assertTrue(self.page.skip_button.isHidden())                     # only SALVAR E AVANÇAR
        self.assertFalse(self.page.previous_button.isEnabled())

    def test_saving_every_product_goes_through_all_of_them_and_completes(self):
        order = [self.current()]
        for _ in range(3):
            self.page._save()
            order.append(self.current())
        self.assertEqual(order, ["1", "2", "3", "6"])
        self.assertEqual(self.page.save_button.text(), "SALVAR E CONCLUIR")
        self.assertTrue(self.page.skip_button.isHidden())                     # no "keep" button either
        self.assertEqual(self.done, [])
        self.page._save()
        self.assertEqual(self.done, [0])                                   # nothing was changed
        self.assertEqual(self.page._skipped_item_ids, set())

    def test_saving_an_edit_counts_it_and_goes_to_the_next_product(self):
        from dataclasses import replace
        self.page._draft[0] = replace(self.page._draft[0], copies_per_product=3)
        self.page._save()
        self.assertEqual(self.current(), "2")
        self.assertEqual(self.state.find_item("1").linked_arts[0].copies_per_product, 3)
        self.assertEqual(self.state.find_item("1").link_status, "linked")
        for _ in range(3):
            self.page._save()
        self.assertEqual(self.done, [1])                                   # one product was changed

    def test_saving_without_changes_just_advances(self):
        self.page._save()
        self.assertEqual(self.current(), "2")
        for _ in range(3):
            self.page._save()
        self.assertEqual(self.done, [0])

    def test_a_product_cannot_be_left_without_arts_during_the_review(self):
        from unittest.mock import patch
        self.page._draft = [None]
        with patch("dtf_manager.ui.pages.manual_linking_page.QMessageBox.information") as info:
            self.page._save()
        info.assert_called_once()
        self.assertEqual(self.current(), "1")
        self.assertEqual(self.state.find_item("1").link_status, "linked")

    def test_previous_walks_back_inside_the_review(self):
        self.page._save()
        self.page._save()
        self.page._previous()
        self.assertEqual(self.current(), "2")
        self.assertTrue(self.page.previous_button.isEnabled())

    def test_a_review_is_never_resumed_as_a_linking_queue_nor_saved_as_one(self):
        self.assertFalse(self.page.can_resume_queue())
        self.assertIsNone(self.page.session_snapshot())

    def test_starting_the_normal_linking_afterwards_brings_back_the_normal_screen(self):
        self.page.start_queue(tuple(i.id for i in self.state.all_items))
        self.assertEqual(self.page.title_label.text(), "VINCULAÇÃO MANUAL")
        self.assertEqual(self.page.position_label.text(), "Produto 1 de 4")
        self.assertEqual(self.page.skip_button.text(), "PULAR POR ENQUANTO")


if __name__ == "__main__":
    unittest.main()
