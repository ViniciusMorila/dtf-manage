"""Real MainWindow: plan/days in the status bar, account menu and save-before-lock."""
from datetime import timedelta
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from dtf_manager.models.license import LicenseInfo
from dtf_manager.services.active_operation_service import create_active_operation
from dtf_manager.services.production_history_repository import ProductionHistoryRepository
from dtf_manager.services.sqlite_database import DTFDatabase
from dtf_manager.ui.main_window import MainWindow
from dtf_manager.ui.styles import APP_STYLE
from tests.license_fakes import license_data


def info(**changes):
    return LicenseInfo.from_dict(license_data(**changes))


class MainWindowLicenseTests(unittest.TestCase):
    # One shared window: creating many MainWindow instances in a single process
    # leaves dangling application event filters (pre-existing manual linking page
    # behavior) that crash the interpreter at exit.
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE)
        cls.temp = TemporaryDirectory()
        folder = Path(cls.temp.name)
        database = DTFDatabase(folder / "test.db")
        history = ProductionHistoryRepository(folder / "history.json")
        settings = QSettings(str(folder / "settings.ini"), QSettings.Format.IniFormat)
        with patch("dtf_manager.ui.main_window.DTFDatabase.default", return_value=database),              patch("dtf_manager.ui.main_window.ProductionHistoryRepository.default", return_value=history),              patch("dtf_manager.ui.panels.project_settings_panel.QSettings", return_value=settings):
            cls.window = MainWindow()
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window._export_timer.stop()
        cls.window.close()
        cls.window.deleteLater()
        cls.app.processEvents()
        cls.temp.cleanup()

    def setUp(self):
        self.window.set_user_name("")
        self.window.set_license_state(None)

    def label(self):
        return self.window.license_label

    def test_the_main_window_has_the_app_icon(self):
        self.assertFalse(self.window.windowIcon().isNull())

    def test_the_title_bar_shows_the_app_version(self):
        from dtf_manager.core.version import APP_VERSION
        self.assertIn(APP_VERSION, self.window.windowTitle())

    def test_nothing_is_shown_before_the_first_validation(self):
        self.assertFalse(self.label().isVisible())
        self.assertFalse(self.window.greeting_label.isVisible())

    def test_regular_plan_shows_plan_and_days(self):
        self.window.set_license_state(info(dias_restantes=37))
        self.assertTrue(self.label().isVisible())
        self.assertEqual(self.label().text(), "Plano Mensal: 37 dias restantes")
        self.assertEqual(self.label().property("tone"), "normal")

    def test_trial_highlights_the_days_left_without_a_subscribe_button(self):
        self.window.set_license_state(info(plano="TESTE", dias_restantes=6))
        self.assertEqual(self.label().text(), "Período de teste: faltam 6 dias")
        self.assertEqual(self.label().property("tone"), "trial")
        self.assertFalse(hasattr(self.window, "renew_button"))   # subscribing lives in Conta

    def test_discreet_warning_with_seven_days_or_less(self):
        for days in [7, 1]:
            with self.subTest(days=days):
                self.window.set_license_state(info(dias_restantes=days))
                self.assertIn("vence em", self.label().text())
                self.assertEqual(self.label().property("tone"), "warning")
        self.window.set_license_state(info(dias_restantes=8))
        self.assertEqual(self.label().property("tone"), "normal")

    def test_lifetime_plan_has_no_days_and_no_warning(self):
        self.window.set_license_state(info(plano="VITALICIO", data_expiracao=None,
                                           dias_restantes=None, vitalicia=True))
        self.assertEqual(self.label().text(), "Plano Vitalício")

    def test_offline_grace_is_a_visible_warning(self):
        self.window.set_license_state(info(), timedelta(hours=52))
        self.assertIn("Modo offline", self.label().text())
        self.assertIn("2 dia(s) e 4 h", self.label().text())
        self.assertEqual(self.label().property("tone"), "offline")

    def test_clearing_the_state_hides_the_label(self):
        self.window.set_license_state(info())
        self.window.set_license_state(None)
        self.assertFalse(self.label().isVisible())

    def test_everything_lives_in_the_top_right_corner(self):
        corner = self.window.menuBar().cornerWidget(Qt.Corner.TopRightCorner)
        self.assertIsNotNone(corner)
        for widget in (self.window.license_label, self.window.greeting_label,
                       self.window.account_button, self.window.logout_button):
            self.assertIs(widget.parentWidget(), corner)
        self.assertEqual(self.window.logout_button.text(), "Sair da conta")

    def test_greeting_uses_the_first_name_and_hides_when_unknown(self):
        greeting = self.window.greeting_label
        self.window.set_user_name("Maria da Silva")
        self.assertEqual(greeting.text(), "Olá, Maria")
        self.assertTrue(greeting.isVisible())
        self.window.set_user_name("   ")
        self.assertFalse(greeting.isVisible())
        self.window.set_user_name(None)
        self.assertEqual(greeting.text(), "")

    def test_greeting_shows_the_plan_in_parentheses_and_the_trial_keeps_its_message(self):
        w, greeting, label = self.window, self.window.greeting_label, self.label()
        w.set_user_name("Vinicius Morila")
        w.set_license_state(info(plano="TESTE", dias_restantes=7))
        self.assertEqual(greeting.text(), "Olá, Vinicius")                  # no parentheses
        self.assertEqual(label.text(), "Período de teste: faltam 7 dias")
        w.set_license_state(info(plano="ANUAL", dias_restantes=300))
        self.assertEqual(greeting.text(), "Olá, Vinicius (Anual)")
        self.assertEqual(label.text(), "300 dias restantes")
        w.set_license_state(info(plano="MENSAL", dias_restantes=5))
        self.assertEqual(greeting.text(), "Olá, Vinicius (Mensal)")
        self.assertEqual(label.text(), "vence em 5 dias")
        self.assertEqual(label.property("tone"), "warning")
        w.set_license_state(info(plano="VITALICIO", data_expiracao=None, dias_restantes=None,
                                 vitalicia=True))
        self.assertEqual(greeting.text(), "Olá, Vinicius (Vitalício)")
        self.assertFalse(label.isVisible())

    def test_greeting_comes_before_the_license_text_in_the_corner(self):
        corner = self.window.menuBar().cornerWidget(Qt.Corner.TopRightCorner)
        order = [corner.layout().itemAt(i).widget() for i in range(corner.layout().count())]
        self.assertEqual(order[:2], [self.window.greeting_label, self.window.license_label])

    def test_without_a_name_the_label_keeps_the_full_plan_text(self):
        self.window.set_user_name("")
        self.window.set_license_state(info(plano="MENSAL", dias_restantes=37))
        self.assertEqual(self.label().text(), "Plano Mensal: 37 dias restantes")
        self.assertFalse(self.window.greeting_label.isVisible())

    def test_roll_footer_sits_at_the_bottom_of_the_editor(self):
        self.window.show()
        self.window.pages.setCurrentWidget(self.window.editor_page)
        self.app.processEvents()
        label = self.window.used_length_label
        area = label.parentWidget()
        top = label.mapTo(area, label.rect().topLeft()).y()
        self.assertFalse(self.window.roll_canvas.isVisible())
        self.assertGreater(top, area.height() - 40)     # the text itself, not a tall empty row

    def test_account_menu_has_renewal_and_plans_that_reach_the_controller(self):
        received = []
        self.window.renew_requested.connect(lambda: received.append("renew"))
        self.window.subscribe_requested.connect(lambda: received.append("subscribe"))
        self.window.plans_requested.connect(lambda: received.append("site"))
        self.window.subscribe_action.trigger()
        self.window.renew_action.trigger()
        self.window.plans_action.trigger()
        self.assertEqual(received, ["subscribe", "renew", "site"])
        self.assertEqual([a.text() for a in self.window.account_button.menu().actions()],
                         ["Assinar...", "Renovar licença (inserir chave)...", "Ver planos no site..."])
        self.assertFalse(self.window.plans_action.isVisible())
        self.window.set_payment_site(True)
        self.assertTrue(self.window.plans_action.isVisible())
        self.window.set_payment_site(False)

    def test_license_widgets_use_only_theme_object_names(self):
        self.assertEqual(self.label().objectName(), "licenseLabel")
        self.assertIn('QLabel#licenseLabel', APP_STYLE)
        self.assertNotIn("setStyleSheet", open(
            Path(__file__).resolve().parents[1] / "dtf_manager" / "ui" / "main_window.py",
            encoding="utf-8").read().split("_build_license_status")[1].split("def _build_ui")[0])

    def test_save_for_license_lock_checkpoints_the_active_operation(self):
        self.window.active_operation = create_active_operation([], "fingerprint", "pedidos.xlsx")
        with patch.object(self.window.active_operation_repository, "save_active") as save:
            self.assertTrue(self.window.save_for_license_lock())
        save.assert_called_once()

    def test_save_without_an_active_operation_is_a_safe_noop(self):
        self.window.active_operation = None
        self.assertTrue(self.window.save_for_license_lock())

    def test_a_failing_save_is_reported_without_raising(self):
        self.window.active_operation = create_active_operation([], "fingerprint", "pedidos.xlsx")
        with patch.object(self.window, "_checkpoint_current_operation", side_effect=RuntimeError("x")):
            self.assertFalse(self.window.save_for_license_lock())


if __name__ == "__main__":
    unittest.main()
