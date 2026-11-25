"""Scrollbars are wide enough to be grabbed easily."""
import re
import unittest

from dtf_manager.ui.styles import APP_STYLE


class ScrollbarStyleTests(unittest.TestCase):
    def test_scrollbars_are_wider_than_the_old_8_px(self):
        vertical = int(re.search(r"QScrollBar:vertical \{ width: (\d+)px", APP_STYLE).group(1))
        horizontal = int(re.search(r"QScrollBar:horizontal \{ height: (\d+)px", APP_STYLE).group(1))
        self.assertGreaterEqual(vertical, 12)
        self.assertEqual(vertical, horizontal)
        self.assertLessEqual(vertical, 18)                  # a little wider, not a fat bar

    def test_the_handle_is_long_enough_to_grab(self):
        self.assertIn("min-height: 40px; min-width: 40px", APP_STYLE)


if __name__ == "__main__":
    unittest.main()
