"""REVISÃO button on the imported-orders screen and its hand-off in the main window."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dtf_manager.models.imported_order import ImportedOrder
from dtf_manager.state.order_import_state import OrderImportState
from dtf_manager.ui.pages.orders_dashboard import OrdersDashboard
from dtf_manager.ui.styles import APP_STYLE
from tests.test_manual_link_session import item


def state_with(*statuses):
    state = OrderImportState()
    state.replace_orders([ImportedOrder(
        "order", "ORDER", None, None, None, [item(str(n), s) for n, s in enumerate(statuses, start=1)])])
    return state


class ReviewButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE)

    def dashboard(self, *statuses):
        dashboard = OrdersDashboard(state_with(*statuses))
        self.addCleanup(dashboard.deleteLater)
        dashboard.show()
        dashboard.refresh()
        return dashboard

    def test_the_button_exists_between_the_linking_buttons_and_montar_pedido(self):
        dashboard = self.dashboard("linked", "unlinked")
        self.assertEqual(dashboard.review_button.text(), "REVISÃO")
        grid = dashboard.action_block.layout()
        positions = {grid.itemAt(i).widget(): grid.getItemPosition(i)[:2] for i in range(grid.count())}
        self.assertEqual(positions[dashboard.review_button], (1, 0))
        self.assertEqual(positions[dashboard.build_order_button], (2, 0))
        self.assertTrue(dashboard.review_button.property("pill"))

    def test_it_is_enabled_only_when_something_is_already_linked(self):
        self.assertFalse(self.dashboard("unlinked", "unlinked").review_button.isEnabled())
        self.assertTrue(self.dashboard("linked", "unlinked").review_button.isEnabled())

    def test_it_is_hidden_before_any_order_is_imported(self):
        dashboard = OrdersDashboard(OrderImportState())
        self.addCleanup(dashboard.deleteLater)
        dashboard.refresh()
        self.assertTrue(dashboard.review_button.isHidden())

    def test_clicking_it_asks_for_the_review(self):
        dashboard = self.dashboard("linked")
        asked = []
        dashboard.review_requested.connect(lambda: asked.append(True))
        dashboard.review_button.click()
        self.assertEqual(asked, [True])


class MainWindowHandOffTests(unittest.TestCase):
    def caller(self, *statuses):
        return SimpleNamespace(
            order_import_state=state_with(*statuses), pages=Mock(), manual_linking_page=Mock(),
            orders_dashboard=Mock(), _return_to_production_review=True, _checkpoint_current_operation=Mock())

    def test_the_review_receives_only_the_linked_products(self):
        from dtf_manager.ui.main_window import MainWindow
        caller = self.caller("linked", "unlinked", "linked")
        MainWindow._open_review(caller)
        caller.manual_linking_page.start_review.assert_called_once_with(("1", "3"))
        caller.pages.setCurrentWidget.assert_called_once_with(caller.manual_linking_page)
        self.assertFalse(caller._return_to_production_review)

    def test_with_nothing_linked_it_only_says_so(self):
        from dtf_manager.ui.main_window import MainWindow
        caller = self.caller("unlinked")
        with patch("dtf_manager.ui.main_window.QMessageBox.information") as info:
            MainWindow._open_review(caller)
        info.assert_called_once()
        caller.manual_linking_page.start_review.assert_not_called()

    def test_finishing_the_review_goes_back_to_the_screen_where_the_roll_is_assembled(self):
        from dtf_manager.ui.main_window import MainWindow
        caller = self.caller("linked")
        with patch("dtf_manager.ui.main_window.QMessageBox.information") as info:
            MainWindow._finish_review(caller, 2)
        caller.pages.setCurrentWidget.assert_called_once_with(caller.orders_dashboard)
        caller._checkpoint_current_operation.assert_called_once_with("orders_dashboard")
        caller.orders_dashboard.refresh.assert_called_once()
        self.assertIn("2", info.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
