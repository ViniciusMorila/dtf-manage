"""Sign-up with an activation key: the checkbox, the key field, trial-used guidance and 429."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest

from dtf_manager.services.api_client import ApiResult
from dtf_manager.utils.forms import format_key_mask, validate_key
from tests.license_fakes import TOKENS, active, http_error, license_data
from tests.test_subscribe_flow import SubscribeBase

KEY = "K7QM-2XTA-9PHD-WR4E"


def created(**changes):
    return ApiResult(201, {"user": {}, "subscription": None, "licenca": license_data(**changes)})


class KeyFieldTests(unittest.TestCase):
    def test_mask_groups_and_uppercases(self):
        self.assertEqual(format_key_mask("k7qm2xta"), "K7QM-2XTA")
        self.assertEqual(format_key_mask(" k7qm-2xta 9phd/wr4e-extra"), KEY)
        self.assertEqual(format_key_mask(""), "")

    def test_format_validation(self):
        self.assertIsNone(validate_key(KEY))
        self.assertIsNone(validate_key("k7qm 2xta 9phd wr4e"))
        self.assertIn("Informe", validate_key(""))
        self.assertIn("incompleta", validate_key("K7QM-2XTA"))
        self.assertIn("não são usados", validate_key("K7QM-2XTA-9PHD-WR40"))   # 0 never appears
        self.assertIn("não são usados", validate_key("K7QM-2XTA-9PHD-WRIO"))


class RegisterKeyBase(SubscribeBase):
    def fill(self, window):
        window.name.setText("Maria Silva")
        window.phone.setText("(11) 91234-5678")
        window.email.setText("maria@example.com")
        window.password.setText("Exemplo123")
        window.confirm.setText("Exemplo123")

    def open_register(self):
        self.storage.token = None
        self.controller.start()
        self.controller.show_register()
        return self.controller.register_window

    def submit_without_key(self, window):
        self.fill(window)
        window.create.click()
        return self.client.calls[-1][1]

    def type_key(self, window, text):
        window.key.clear()
        QTest.keyClicks(window.key, text)


class CheckboxTests(RegisterKeyBase):
    def test_key_field_is_hidden_until_the_option_is_checked(self):
        window = self.open_register()
        self.assertFalse(window.key.isVisibleTo(window))
        self.assertEqual(window.create.text(), "Criar conta e iniciar teste")
        window.has_key.setChecked(True)
        self.assertTrue(window.key.isVisibleTo(window))
        self.assertEqual(window.key.placeholderText(), "XXXX-XXXX-XXXX-XXXX")
        self.assertEqual(window.create.text(), "Criar conta e ativar chave")
        window.has_key.setChecked(False)
        self.assertFalse(window.key.isVisibleTo(window))

    def test_key_is_masked_while_typing(self):
        window = self.open_register()
        window.has_key.setChecked(True)
        self.type_key(window, "k7qm2xta9phdwr4e")
        self.assertEqual(window.key.text(), KEY)

    def test_invalid_key_format_is_rejected_before_any_request(self):
        window = self.open_register()
        window.has_key.setChecked(True)
        self.fill(window)
        for text, expected in [("", "Informe a chave"), ("K7QM-2XTA", "incompleta"),
                               ("K7QM2XTA9PHDWR40", "não são usados")]:
            with self.subTest(text=text):
                self.type_key(window, text)
                window.create.click()
                self.assertIn(expected, window.message.text())
        self.assertEqual(self.client.calls, [])

    def test_trial_registration_does_not_send_a_key(self):
        window = self.open_register()
        payload = self.submit_without_key(window)
        self.assertNotIn("chave_ativacao", payload)


class RegistrationWithKeyTests(RegisterKeyBase):
    def finish_signup(self, plano, **changes):
        self.client.respond(created(plano=plano, **changes))
        self.assertEqual(self.client.calls[-1][0], "/auth/login")
        self.client.respond(ApiResult(200, TOKENS))
        self.assertEqual(self.client.calls[-1][0], "/licencas/status")
        self.client.respond(active(plano=plano, **changes))

    def test_key_is_sent_and_the_paid_plan_shows_in_the_status_bar(self):
        window = self.open_register()
        window.has_key.setChecked(True)
        self.fill(window)
        self.type_key(window, KEY.lower())
        window.create.click()
        path, payload, _ = self.client.calls[-1]
        self.assertEqual(path, "/auth/register")
        self.assertEqual(payload["chave_ativacao"], KEY)
        self.assertNotIn("plan_code", payload)
        self.finish_signup("ANUAL", data_expiracao="2027-11-19T18:00:00Z", dias_restantes=365)
        self.assertTrue(self.main.isVisible())
        info = self.main.states[-1][0]
        self.assertEqual((info.plano, info.dias_restantes), ("ANUAL", 365))
        self.assertEqual(self.store.snapshot is not None, True)

    def test_lifetime_key_shows_the_lifetime_plan(self):
        window = self.open_register()
        window.has_key.setChecked(True)
        self.fill(window)
        self.type_key(window, KEY)
        window.create.click()
        self.finish_signup("VITALICIO", vitalicia=True, data_expiracao=None, dias_restantes=None)
        info = self.main.states[-1][0]
        self.assertEqual((info.plano, info.vitalicia), ("VITALICIO", True))

    def test_after_the_trial_was_used_the_key_creates_the_account_with_the_paid_plan(self):
        # The server answers TESTE_JA_UTILIZADO for a used machine and a used phone alike.
        window = self.open_register()
        self.submit_without_key(window)
        self.client.respond(http_error(409, "TESTE_JA_UTILIZADO", "texto do servidor"))
        self.assertTrue(window.has_key.isChecked())
        self.fill(window)                   # the passwords were cleared on submit
        self.type_key(window, KEY)
        window.create.click()
        path, payload, _ = self.client.calls[-1]
        self.assertEqual((path, payload["chave_ativacao"]), ("/auth/register", KEY))
        self.finish_signup("MENSAL", dias_restantes=30)
        self.assertEqual(self.main.states[-1][0].plano, "MENSAL")


class TrialUsedTests(RegisterKeyBase):
    def test_trial_used_opens_the_key_field_focuses_it_and_offers_to_subscribe(self):
        window = self.open_register()
        self.submit_without_key(window)
        self.client.respond(http_error(409, "TESTE_JA_UTILIZADO", "texto do servidor"))
        self.assertTrue(window.has_key.isChecked())
        self.assertTrue(window.key.isVisibleTo(window))
        self.assertIs(window.focusWidget(), window.key)
        self.assertTrue(window.subscribe.isVisibleTo(window))
        self.assertIn("computador ou este telefone já usou", window.message.text())
        self.assertIn("chave de ativação", window.message.text())
        self.assertNotIn("texto do servidor", window.message.text())
        self.assertTrue(window.create.isEnabled())
        self.assertEqual(self.paths(), ["/auth/register"])      # nothing else was called

    def test_subscribe_button_opens_the_whatsapp_flow_and_back_returns_here(self):
        window = self.open_register()
        self.submit_without_key(window)
        self.client.respond(http_error(409, "TESTE_JA_UTILIZADO"))
        window.subscribe.click()
        self.assertTrue(self.subscribe.isVisible())
        self.assertFalse(window.isVisible())
        self.assertIn("período de teste já foi utilizado", self.subscribe.reason.text())
        self.subscribe.have_key.click()
        self.assertTrue(window.isVisible())
        self.assertFalse(self.subscribe.isVisible())
        self.assertTrue(window.key.isVisibleTo(window))
        self.subscribe.show()
        self.subscribe.back.click()
        self.assertTrue(window.isVisible())


class InvalidKeyTests(RegisterKeyBase):
    def test_invalid_key_explains_that_no_account_was_created(self):
        window = self.open_register()
        window.has_key.setChecked(True)
        self.fill(window)
        self.type_key(window, KEY)
        window.create.click()
        self.client.respond(http_error(422, "CHAVE_INVALIDA", "texto do servidor"))
        text = window.message.text()
        self.assertIn("não existe, já foi utilizada ou foi cancelada", text)
        self.assertIn("Nenhuma conta foi criada", text)
        self.assertNotIn("texto do servidor", text)
        self.assertEqual(self.paths(), ["/auth/register"])       # no login attempt
        self.assertTrue(window.create.isEnabled())
        self.assertEqual(window.key.text(), KEY)                 # kept so it can be corrected
        self.assertEqual(window.password.text(), "")


class RateLimitTests(RegisterKeyBase):
    def test_button_stays_disabled_during_the_retry_after_then_returns(self):
        window = self.open_register()
        window.has_key.setChecked(True)
        self.fill(window)
        self.type_key(window, KEY)
        window.create.click()
        self.client.respond(http_error(429, "MUITAS_TENTATIVAS", retry_after=3))
        self.assertIn("3 segundos", window.message.text())
        self.assertFalse(window.create.isEnabled())
        self.assertEqual(window.create.text(), "Aguarde 3 s")
        self.fill(window)
        window._submit()                                        # Enter is ignored too
        self.assertEqual(len(self.client.calls), 1)
        window._cooldown.tick()
        window._cooldown.tick()
        self.assertFalse(window.create.isEnabled())
        self.assertEqual(window.create.text(), "Aguarde 1 s")
        window._cooldown.tick()
        self.assertTrue(window.create.isEnabled())
        self.assertEqual(window.create.text(), "Criar conta e ativar chave")

    def test_cooldown_survives_a_new_failure_text_and_uses_a_default_without_header(self):
        window = self.open_register()
        self.submit_without_key(window)
        self.client.respond(http_error(429, "MUITAS_TENTATIVAS"))
        self.assertFalse(window.create.isEnabled())
        self.assertEqual(window._cooldown.left, 60)
        window.show_failure("outra mensagem")
        self.assertFalse(window.create.isEnabled())


if __name__ == "__main__":
    unittest.main()
