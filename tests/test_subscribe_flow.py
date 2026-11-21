"""Manual WhatsApp subscription: plan screen, entry points, message and link."""
import os
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QWidget

from dtf_manager.services.api_client import ApiResult
from dtf_manager.services.plans import PlansError
from dtf_manager.services.whatsapp import build_url
from tests.license_fakes import TOKENS, active, http_error, license_data
from tests.session_fakes import MACHINE_ID
from tests.test_license_flow import CONTROLLER, LicenseFlowBase
from tests.test_offline_grace import status as cache_status

NUMBER = "5511999999999"


def sent_text(opener):
    """Decoded message of the last wa.me link handed to the URL opener."""
    url = opener.call_args.args[0]
    return url, parse_qs(urlsplit(url).query)["text"][0]


class SubscribeBase(LicenseFlowBase):
    def setUp(self):
        env = patch.dict(os.environ, {"DTF_WHATSAPP_NUMBER": NUMBER})
        env.start()
        self.addCleanup(env.stop)
        super().setUp()

    def expired_login(self, **license):
        self.storage.token = None
        self.controller.start()
        self.controller.login("user@example.com", "Exemplo123")
        self.client.respond(http_error(403, "LICENCA_EXPIRADA",
                                       license=license_data(status="EXPIRADA", dias_restantes=0, **license)))

    @property
    def subscribe(self):
        return self.controller._subscribe_window


class EntryPointTests(SubscribeBase):
    def test_expired_license_screen_offers_subscribe_and_opens_the_plan_screen(self):
        self.expired_login()
        activation = self.controller.activation_window
        self.assertEqual(activation.title.text(), "Licença vencida")
        activation.subscribe.click()
        self.assertTrue(self.subscribe.isVisible())
        self.assertFalse(activation.isVisible())
        self.assertIn("licença venceu", self.subscribe.reason.text())

    def test_trial_end_screen_has_its_own_title_and_reason(self):
        self.expired_login(plano="TESTE")
        activation = self.controller.activation_window
        self.assertEqual(activation.title.text(), "Fim do período de teste")
        self.assertIn("período de teste terminou", activation.intro.text())
        activation.subscribe.click()
        self.assertIn("período de teste terminou", self.subscribe.reason.text())

    def test_account_menu_and_status_bar_button_open_the_screen(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.assertTrue(self.subscribe.isVisible())
        self.assertTrue(self.main.isEnabled())
        self.assertEqual(self.subscribe.reason.text(), "")

    def test_menu_entry_during_the_trial_explains_it(self):
        self.storage.token = None
        self.controller.start()
        self.controller.login("user@example.com", "Exemplo123")
        self.client.respond(ApiResult(200, TOKENS))
        self.client.respond(active(plano="TESTE", dias_restantes=5))
        self.main.subscribe_requested.emit()
        self.assertIn("período de teste", self.subscribe.reason.text())

    def test_real_main_window_button_and_menu_reach_the_screen(self):
        from dtf_manager.ui.main_window import MainWindow
        for signal_name in ("subscribe_requested", "renew_requested", "plans_requested"):
            self.assertTrue(hasattr(MainWindow, signal_name))

    def test_back_returns_to_the_key_screen_of_an_expired_license(self):
        self.expired_login()
        self.controller.activation_window.subscribe.click()
        self.subscribe.back.click()
        self.assertTrue(self.controller.activation_window.isVisible())
        self.assertFalse(self.subscribe.isVisible())

    def test_back_from_the_menu_keeps_the_app_running(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.subscribe.back.click()
        self.assertFalse(self.subscribe.isVisible())
        self.assertTrue(self.main.isEnabled())
        self.assertFalse(self.controller._stopped)

    def test_closing_the_plan_screen_of_a_working_session_does_not_quit(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.subscribe.close()
        self.assertFalse(self.controller._stopped)

    def test_closing_the_plan_screen_of_an_expired_license_quits(self):
        self.expired_login()
        self.controller.activation_window.subscribe.click()
        with patch.object(self.controller, "app"):
            self.subscribe.close()
        self.assertTrue(self.controller._stopped)

    def test_have_a_key_from_the_expired_flow_returns_to_the_key_screen(self):
        self.expired_login()
        self.controller.activation_window.subscribe.click()
        self.subscribe.have_key.click()
        self.assertTrue(self.controller.activation_window.isVisible())
        self.assertFalse(self.subscribe.isVisible())

    def test_have_a_key_from_the_menu_opens_the_renewal(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.subscribe.have_key.click()
        self.assertTrue(self.controller.activation_window.isVisible())
        self.assertTrue(self.controller.activation_window.session_mode)
        self.assertFalse(self.subscribe.isVisible())


class PlanChoiceTests(SubscribeBase):
    def test_choosing_a_plan_opens_the_expected_whatsapp_link(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        calls = len(self.client.calls)
        self.subscribe.choose_buttons["ANUAL"].click()
        self.opener.assert_called_once()
        url, text = sent_text(self.opener)
        self.assertTrue(url.startswith(f"https://wa.me/{NUMBER}?text="))
        self.assertEqual(text, "Olá! Quero assinar o DTF Manager. Plano: Anual (R$ 449,90). "
                               "E-mail da conta: user@example.com.")
        self.assertEqual(url, build_url(NUMBER, text))
        self.assertNotIn(" ", url)
        self.assertEqual(len(self.client.calls), calls)          # no API call on this screen

    def test_each_plan_button_builds_its_own_message(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        for code, label in [("MENSAL", "Mensal (R$ 49,90)"), ("SEMESTRAL", "Semestral (R$ 249,90)"),
                            ("VITALICIO", "Vitalício (R$ 1.299,00)")]:
            with self.subTest(code=code):
                self.subscribe.choose_buttons[code].click()
                self.assertIn("Plano: " + label, sent_text(self.opener)[1])

    def test_message_uses_registration_data_from_the_session(self):
        self.storage.token = None
        self.controller.start()
        self.controller.show_register()
        window = self.controller.register_window
        window.name.setText("Maria Silva")
        window.phone.setText("(11) 91234-5678")
        window.email.setText("maria@example.com")
        window.password.setText("Exemplo123")
        window.confirm.setText("Exemplo123")
        window.create.click()
        self.client.respond(ApiResult(201, {"licenca": license_data(plano="TESTE", dias_restantes=7)}))
        self.client.respond(ApiResult(200, TOKENS))
        self.client.respond(active(plano="TESTE", dias_restantes=7))
        self.main.subscribe_requested.emit()
        self.subscribe.choose_buttons["MENSAL"].click()
        self.assertEqual(sent_text(self.opener)[1],
                         "Olá! Quero assinar o DTF Manager. Plano: Mensal (R$ 49,90). Nome: Maria Silva. "
                         "E-mail da conta: maria@example.com. Telefone: 11912345678.")

    def test_without_a_session_the_message_asks_for_the_email_in_the_chat(self):
        self.storage.token = None
        self.controller.start()
        self.controller.show_subscribe()
        self.subscribe.choose_buttons["ANUAL"].click()
        text = sent_text(self.opener)[1]
        self.assertIn("Plano: Anual (R$ 449,90)", text)
        self.assertIn("vou informar aqui na conversa", text)
        self.assertNotIn("Nome:", text)

    def test_expired_license_without_token_uses_the_contact_kept_in_the_local_cache(self):
        self.grace.record_success(cache_status(), {"email": "cache@example.com", "name": "Cliente"})
        self.restore_start()
        self.client.respond(http_error(403, "LICENCA_EXPIRADA",
                                       license=license_data(status="EXPIRADA", dias_restantes=0)))
        self.assertIsNone(self.store.snapshot)                    # cache cleared by the expiry
        self.controller.activation_window.subscribe.click()
        self.subscribe.choose_buttons["ANUAL"].click()
        text = sent_text(self.opener)[1]
        self.assertIn("E-mail da conta: cache@example.com.", text)
        self.assertIn("Nome: Cliente.", text)

    def test_message_never_contains_password_token_or_machine_id(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.subscribe.choose_buttons["ANUAL"].click()
        url, text = sent_text(self.opener)
        for secret in ["Exemplo123", "private-access", "private-refresh", MACHINE_ID, "saved-refresh"]:
            self.assertNotIn(secret, text)
            self.assertNotIn(secret, url)

    def test_buttons_are_disabled_while_the_link_is_being_opened(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        states = []
        self.opener.side_effect = lambda url: states.append(
            [b.isEnabled() for b in (*self.subscribe.choose_buttons.values(), self.subscribe.copy,
                                     self.subscribe.have_key, self.subscribe.back)]) or True
        self.subscribe.choose_buttons["ANUAL"].click()
        self.assertEqual(states, [[False] * 7])
        self.assertTrue(all(b.isEnabled() for b in self.subscribe.choose_buttons.values()))

    def test_guidance_and_copy_button_appear_after_opening(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.assertFalse(self.subscribe.guidance.isVisibleTo(self.subscribe))
        self.assertFalse(self.subscribe.copy.isVisibleTo(self.subscribe))
        self.subscribe.choose_buttons["ANUAL"].click()
        self.assertTrue(self.subscribe.guidance.isVisibleTo(self.subscribe))
        self.assertEqual(self.subscribe.guidance.text(),
                         "Finalize o pagamento pelo WhatsApp. Quando receber a chave, "
                         "clique em 'Tenho uma chave'.")
        self.assertTrue(self.subscribe.copy.isVisibleTo(self.subscribe))

    def test_copy_message_puts_the_same_text_in_the_clipboard(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.subscribe.choose_buttons["ANUAL"].click()
        self.subscribe.copy.click()
        self.assertEqual(QApplication.clipboard().text(), sent_text(self.opener)[1])
        self.assertIn("copiada", self.subscribe.notice.text())

    def test_if_whatsapp_cannot_be_opened_the_user_is_told_to_copy(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.opener.return_value = False
        self.subscribe.choose_buttons["ANUAL"].click()
        self.assertIn("Copiar mensagem", self.subscribe.notice.text())
        self.assertIn(NUMBER, self.subscribe.notice.text())
        self.assertTrue(self.subscribe.copy.isVisibleTo(self.subscribe))

    def test_screen_stays_inert_while_busy(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        received = []
        self.subscribe.plan_chosen.connect(received.append)
        self.subscribe.set_busy(True)
        self.subscribe._choose("ANUAL")
        self.assertEqual(received, [])


class MissingNumberTests(SubscribeBase):
    def test_missing_or_malformed_number_shows_a_warning_instead_of_a_broken_link(self):
        for value in [None, "", "abc", "+5511999999999", "123"]:
            with self.subTest(value=value):
                env = {k: v for k, v in os.environ.items() if k != "DTF_WHATSAPP_NUMBER"}
                if value is not None:
                    env["DTF_WHATSAPP_NUMBER"] = value
                with patch.dict(os.environ, env, clear=True):
                    self.sign_in() if not self.main.isVisible() else None
                    self.main.subscribe_requested.emit()
                    self.assertIn("DTF_WHATSAPP_NUMBER", self.subscribe.notice.text())
                    self.subscribe.choose_buttons["ANUAL"].click()
                    self.opener.assert_not_called()
                    self.assertFalse(self.subscribe.guidance.isVisibleTo(self.subscribe))


class ScreenTests(SubscribeBase):
    def test_four_plans_with_name_duration_price_and_an_escolher_button(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.assertEqual(list(self.subscribe.choose_buttons), ["MENSAL", "SEMESTRAL", "ANUAL", "VITALICIO"])
        texts = " ".join(label.text() for label in self.subscribe.findChildren(type(self.subscribe.reason)))
        for expected in ["Mensal", "1 mês", "Semestral", "6 meses", "Anual", "12 meses", "Vitalício",
                         "Sem expiração", "R$ 49,90", "R$ 449,90", "EXEMPLO"]:
            self.assertIn(expected, texts)
        self.assertTrue(all(b.text() == "Escolher" for b in self.subscribe.choose_buttons.values()))
        self.assertTrue(self.subscribe.example_note.isVisibleTo(self.subscribe))

    def test_annual_is_highlighted_without_inventing_a_discount(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        cards = [f.objectName() for f in self.subscribe.findChildren(QFrame) if type(f) is QFrame]
        self.assertEqual(cards, ["previewCard", "previewCard", "widthCard", "previewCard"])
        self.assertEqual(self.subscribe.choose_buttons["ANUAL"].objectName(), "primaryButton")
        texts = " ".join(label.text() for label in self.subscribe.findChildren(type(self.subscribe.reason)))
        self.assertIn("MAIS VANTAJOSO", texts)
        self.assertNotIn("%", texts)
        self.assertNotIn("desconto", texts.lower())

    def test_uses_the_theme_only_no_inline_styles(self):
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.assertEqual(self.subscribe.objectName(), "appRoot")
        for widget in [self.subscribe, *self.subscribe.findChildren(QWidget)]:
            self.assertEqual(widget.styleSheet(), "")

    def test_invalid_plans_file_is_reported_and_no_window_is_created(self):
        controller = self.controller
        controller._plans_loader = Mock(side_effect=PlansError("Arquivo de planos inválido."))
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.assertIsNone(controller._subscribe_window)
        self.assertIn("planos inválido", self.warning.call_args.args[2])

    def test_custom_plans_come_from_the_loader_not_from_the_ui(self):
        from dtf_manager.services.plans import Plan
        self.controller._plans_loader = lambda: (Plan("MENSAL", "Mensal", "1 mês", "R$ 5,00"),)
        self.sign_in()
        self.main.subscribe_requested.emit()
        self.assertEqual(list(self.subscribe.choose_buttons), ["MENSAL"])
        self.assertFalse(self.subscribe.example_note.isVisibleTo(self.subscribe))
        self.subscribe.choose_buttons["MENSAL"].click()
        self.assertIn("Mensal (R$ 5,00)", sent_text(self.opener)[1])


if __name__ == "__main__":
    unittest.main()
