"""Manual linking: the art-name suggestions must be fully visible while the user is typing."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from dtf_manager.ui.pages.manual_linking_page import (
    SUGGESTIONS_MAX_HEIGHT, SUGGESTIONS_MIN_HEIGHT, ManualLinkingPage)
from dtf_manager.ui.styles import APP_STYLE
from dtf_manager.state.order_import_state import OrderImportState


def make_image(path):
    image = QImage(40, 40, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))


class PageBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.page = ManualLinkingPage(OrderImportState(), Mock())
        self.page.resize(1600, 700)                                    # a modest window on purpose
        self.page.show()
        self.addCleanup(self._close_page)

    def _close_page(self):
        self.app.removeEventFilter(self.page)
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def type_name(self, text, count):
        for number in range(count):
            make_image(self.folder / f"{text} {number:02d}.png")
        self.page.set_artwork_folder(self.folder)
        self.page.art_search.setText(text)
        self.page._search_timer.stop()
        self.page._refresh_suggestions()
        self.app.processEvents()


class SuggestionsAreaTests(PageBase):
    def test_the_area_is_tall_enough_for_two_whole_rows_of_cards(self):
        self.type_name("doom", 12)
        scroll = self.page.suggestions_scroll
        self.assertTrue(scroll.isVisibleTo(self.page))
        self.assertGreaterEqual(scroll.height(), SUGGESTIONS_MIN_HEIGHT)
        self.assertLessEqual(scroll.height(), SUGGESTIONS_MAX_HEIGHT)
        self.assertGreaterEqual(SUGGESTIONS_MIN_HEIGHT, 2 * 116 + 8)

    def test_a_few_results_still_get_the_minimum_height(self):
        self.type_name("doom", 2)
        self.assertGreaterEqual(self.page.suggestions_scroll.height(), SUGGESTIONS_MIN_HEIGHT)

    def test_clearing_the_search_hides_the_area_again(self):
        self.type_name("doom", 4)
        self.page.art_search.clear()
        self.assertFalse(self.page.suggestions_scroll.isVisible())


class PointerLeavingTests(PageBase):
    """The list also closes when the mouse, after being over it, goes away (no click needed)."""

    def enter_and_leave(self, pointer_still_over=False):
        scroll = self.page.suggestions_scroll
        self.page.eventFilter(scroll, QEvent(QEvent.Type.Enter))
        with patch.object(self.page, "_pointer_over_suggestions", return_value=pointer_still_over):
            self.page.eventFilter(scroll, QEvent(QEvent.Type.Leave))
            self.page._close_if_pointer_left_list()        # what the short timer runs

    def test_leaving_the_list_closes_it_and_clears_the_search(self):
        self.type_name("doom", 6)
        self.enter_and_leave()
        self.assertFalse(self.page.suggestions_scroll.isVisible())
        self.assertEqual(self.page.art_search.text(), "")

    def test_it_stays_open_while_the_mouse_never_went_over_it(self):
        self.type_name("doom", 6)
        with patch.object(self.page, "_pointer_over_suggestions", return_value=False):
            self.page._close_if_pointer_left_list()
        self.assertTrue(self.page.suggestions_scroll.isVisible())
        self.assertEqual(self.page.art_search.text(), "doom")

    def test_it_stays_open_while_the_mouse_is_still_over_it(self):
        self.type_name("doom", 6)
        self.enter_and_leave(pointer_still_over=True)
        self.assertTrue(self.page.suggestions_scroll.isVisible())

    def test_typing_again_forgets_that_the_mouse_was_over_the_old_list(self):
        self.type_name("doom", 6)
        self.page.eventFilter(self.page.suggestions_scroll, QEvent(QEvent.Type.Enter))
        self.page._refresh_suggestions()                   # new results after typing
        with patch.object(self.page, "_pointer_over_suggestions", return_value=False):
            self.page._close_if_pointer_left_list()
        self.assertTrue(self.page.suggestions_scroll.isVisible())


if __name__ == "__main__":
    unittest.main()
