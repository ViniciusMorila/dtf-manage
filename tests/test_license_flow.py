"""License flows through the controller: sign-up, activation, periodic checks, grace, blocking."""
from datetime import timedelta
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from dtf_manager.core import config
from dtf_manager.services.api_client import ApiResult
from dtf_manager.services.offline_grace import OfflineGrace
from tests.license_fakes import (
    FakeClient, ROTATED, TOKENS, active, build_controller, dispose_controller, http_error,
    license_data, status_body)
from tests.session_fakes import MACHINE_ID, FakeLicenseStore, FakeSessionStorage
from tests.test_offline_grace import Clock, status as cache_status

CONTROLLER = "dtf_manager.core.application_controller.QMessageBox"


class FakeMain(QWidget):
    logout_requested = Signal()
    renew_requested = Signal()
    plans_requested = Signal()

    def __init__(self):
        super().__init__()
        self.saves = 0
        self.states = []

    def save_for_license_lock(self):
        self.saves += 1
        return True

    def set_license_state(self, info, offline_remaining=None):
        self.states.append((info, offline_remaining))

    def prepare_logout(self):
        return True


class LicenseFlowBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.client = FakeClient()
        self.storage = FakeSessionStorage("saved-refresh")
        self.store = FakeLicenseStore()
        self.clock = Clock()
        self.grace = OfflineGrace(self.store, clock=self.clock, monotonic=self.clock.monotonic)
        self.main = FakeMain()
        self.factory = Mock(return_value=self.main)
        self.opener = Mock()
        self.controller = build_controller(self.app, self.client, storage=self.storage,
                                           factory=self.factory, store=self.store,
                                           grace=self.grace, url_opener=self.opener)
        for name in ("warning", "information", "question"):
            patcher = patch(f"{CONTROLLER}.{name}")
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: dispose_controller(self.app, self.controller, self.main))

    def sign_in(self):
        """Interactive login that ends with the main window open."""
        self.storage.token = None
        self.controller.start()
        self.controller.login("user@example.com", "Exemplo123")
        self.client.respond(ApiResult(200, TOKENS))
        self.client.respond(active())
        self.assertTrue(self.main.isVisible())

    def restore_start(self):
        self.controller.start()

    def paths(self):
        return self.client.paths()


class RegistrationTests(LicenseFlowBase):
    def fill(self, window):
        window.name.setText("Maria Silva")
        window.phone.setText("(11) 91234-5678")
        window.email.setText("maria@example.com")
        window.password.setText("Exemplo123")
        window.confirm.setText("Exemplo123")

    def test_first_open_registers_then_logs_in_checks_license_and_opens_main(self):
        self.storage.token = None
        self.controller.start()
        self.assertTrue(self.controller.login_window.isVisible())
        self.controller.login_window.register.click()
        window = self.controller.register_window
        self.assertTrue(window.isVisible())
        self.assertFalse(self.controller.login_window.isVisible())
        self.fill(window)
        window.create.click()
        path, payload, _ = self.client.calls[-1]
        self.assertEqual(path, "/auth/register")
        self.assertEqual(payload, {"nome": "Maria Silva", "telefone": "11912345678",
                                   "email": "maria@example.com", "senha": "Exemplo123",
                                   "id_maquina": MACHINE_ID})
        self.assertNotIn("cpf", payload)
        self.assertNotIn("plan_code", payload)
        self.client.respond(ApiResult(201, {"user": {}, "subscription": None,
                                             "licenca": license_data(plano="TESTE", dias_restantes=7)}))
        path, payload, _ = self.client.calls[-1]
        self.assertEqual((path, payload["email"], payload["senha"]),
                         ("/auth/login", "maria@example.com", "Exemplo123"))
        self.client.respond(ApiResult(200, TOKENS))
        self.assertEqual(self.client.calls[-1][0], "/licencas/status")
        self.client.respond(active(plano="TESTE", dias_restantes=7, vitalicia=False))
        self.assertTrue(self.main.isVisible())
        self.assertFalse(window.isVisible())
        self.assertEqual(self.main.states[-1][0].plano, "TESTE")
        self.assertIsNotNone(self.store.snapshot)

    def test_form_validates_before_any_request(self):
        self.storage.token = None
        self.controller.start()
        self.controller.show_register()
        window = self.controller.register_window
        for field, value, text in [("phone", "123", "Telefone inválido"),
                                   ("email", "sem-arroba", "e-mail válido"),
                                   ("password", "curta1", "mínimo 8"),
                                   ("name", "  ", "nome")]:
            with self.subTest(field=field):
                self.fill(window)
                getattr(window, field).setText(value)
                if field == "password":
                    window.confirm.setText(value)
                window.create.click()
                self.assertIn(text, window.message.text())
        self.fill(window)
        window.confirm.setText("Outra1234")
        window.create.click()
        self.assertIn("não conferem", window.message.text())
        self.assertEqual(self.client.calls, [])

    def test_phone_mask_is_applied_while_typing(self):
        self.storage.token = None
        self.controller.start()
        self.controller.show_register()
        window = self.controller.register_window
        QTest.keyClicks(window.phone, "11912345678")
        self.assertEqual(window.phone.text(), "(11) 91234-5678")

    def test_trial_already_used(self):
        self.storage.token = None
        self.controller.start()
        self.controller.show_register()
        window = self.controller.register_window
        self.fill(window)
        window.create.click()
        self.client.respond(http_error(409, "TESTE_JA_UTILIZADO", "texto do servidor"))
        self.assertIn("período de teste já foi utilizado", window.message.text())
        self.assertNotIn("texto do servidor", window.message.text())
        self.assertTrue(window.create.isEnabled())
        self.assertEqual(self.paths(), ["/auth/register"])

    def test_invalid_phone_and_rate_limit_from_the_server(self):
        self.storage.token = None
        self.controller.start()
        self.controller.show_register()
        window = self.controller.register_window
        for result, text in [(http_error(422, "TELEFONE_INVALIDO"), "Telefone inválido"),
                             (http_error(409, "EMAIL_ALREADY_EXISTS"), "Já existe"),
                             (http_error(429, "MUITAS_TENTATIVAS", retry_after=3600), "1 hora")]:
            with self.subTest(code=result.error_code):
                self.fill(window)
                window.create.click()
                self.client.respond(result)
                self.assertIn(text, window.message.text())

    def test_back_returns_to_login(self):
        self.storage.token = None
        self.controller.start()
        self.controller.show_register()
        self.controller.register_window.back.click()
        self.assertTrue(self.controller.login_window.isVisible())
        self.assertFalse(self.controller.register_window.isVisible())


class RefusalTests(LicenseFlowBase):
    def test_login_on_another_machine_explains_how_to_ask_for_the_switch(self):
        self.storage.token = None
        self.controller.start()
        self.controller.login("user@example.com", "Exemplo123")
        self.client.respond(http_error(403, "MAQUINA_DIFERENTE"))
        text = self.controller.login_window.message.text()
        self.assertIn("outro computador", text)
        self.assertIn("suporte", text)
        self.factory.assert_not_called()

    def test_support_contact_comes_from_configuration(self):
        with patch.dict(os.environ, {"DTF_SUPPORT_CONTACT": "suporte@example.com"}):
            self.storage.token = None
            self.controller.start()
            self.controller.login("user@example.com", "Exemplo123")
            self.client.respond(http_error(403, "MAQUINA_DIFERENTE"))
            self.assertIn("suporte@example.com", self.controller.login_window.message.text())

    def test_session_ended_on_another_computer_is_explained(self):
        self.storage.token = "saved-refresh"
        self.restore_start()
        self.client.respond(http_error(401, "INVALID_REFRESH_TOKEN"))
        text = self.controller.login_window.message.text()
        self.assertIn("outro computador", text)
        self.assertIsNone(self.storage.token)
        self.factory.assert_not_called()

    def test_refresh_refusal_for_machine_keeps_the_saved_token(self):
        self.restore_start()
        self.client.respond(http_error(403, "MAQUINA_DIFERENTE"))
        self.assertEqual(self.storage.token, "saved-refresh")
        self.assertEqual(self.storage.deletions, 0)
        self.assertEqual(self.controller.login_window.enter.text(), "Tentar novamente")
        self.assertIn("outro computador", self.controller.login_window.message.text())

    def test_blocked_license_never_opens_main(self):
        self.restore_start()
        self.client.respond(ApiResult(200, ROTATED))
        self.client.respond(http_error(403, "LICENCA_BLOQUEADA"))
        self.assertIn("bloqueada", self.controller.login_window.message.text())
        self.factory.assert_not_called()

    def test_status_200_with_non_active_state_is_a_refusal(self):
        self.restore_start()
        self.client.respond(ApiResult(200, ROTATED))
        self.client.respond(active(status="BLOQUEADA", dias_restantes=0))
        self.factory.assert_not_called()
        self.assertTrue(self.controller.login_window.isVisible())


class ActivationTests(LicenseFlowBase):
    def expired_login(self):
        self.storage.token = None
        self.controller.start()
        self.controller.login("user@example.com", "Exemplo123")
        self.client.respond(http_error(403, "LICENCA_EXPIRADA"))

    def test_expired_license_opens_the_key_screen_with_plans(self):
        self.expired_login()
        window = self.controller.activation_window
        self.assertTrue(window.isVisible())
        self.assertFalse(self.controller.login_window.isVisible())
        self.assertFalse(window.session_mode)
        self.assertEqual(window.email.text(), "user@example.com")
        self.assertIn("expirou", window.message.text())
        window.plans.click()
        self.opener.assert_called_once_with(config.DEFAULT_PAYMENT_URL)
        self.factory.assert_not_called()

    def test_account_without_license_also_asks_for_a_key(self):
        self.storage.token = None
        self.controller.start()
        self.controller.login("user@example.com", "Exemplo123")
        self.client.respond(http_error(404, "LICENCA_NAO_ENCONTRADA"))
        self.assertTrue(self.controller.activation_window.isVisible())

    def test_valid_key_is_applied_with_email_and_password_then_signs_in(self):
        self.expired_login()
        window = self.controller.activation_window
        window.password.setText("Exemplo123")
        window.key.setText("k7qm-2xta-9phd-wr4e")
        window.activate.click()
        path, payload, _ = self.client.calls[-1]
        self.assertEqual(path, "/licencas/ativar-chave")
        self.assertEqual(payload, {"chave": "k7qm-2xta-9phd-wr4e", "id_maquina": MACHINE_ID,
                                   "email": "user@example.com", "senha": "Exemplo123"})
        self.assertIsNone(self.client.bearers[-1])
        self.client.respond(ApiResult(200, {**status_body(), "plano_ativado": "MENSAL"}))
        self.assertEqual(self.client.calls[-1][0], "/auth/login")
        self.client.respond(ApiResult(200, TOKENS))
        self.assertEqual(self.client.calls[-1][0], "/licencas/status")
        self.client.respond(active())
        self.assertTrue(self.main.isVisible())
        self.assertFalse(window.isVisible())
        self.assertEqual(window.password.text(), "")

    def test_invalid_key_shows_error_and_does_not_log_in(self):
        self.expired_login()
        window = self.controller.activation_window
        window.password.setText("Exemplo123")
        window.key.setText("XXXX")
        window.activate.click()
        self.client.respond(http_error(422, "CHAVE_INVALIDA", "texto do servidor"))
        self.assertIn("Chave de ativação inválida", window.message.text())
        self.assertNotIn("texto do servidor", window.message.text())
        self.assertTrue(window.activate.isEnabled())
        self.assertNotIn("/auth/login", self.paths()[2:])
        self.factory.assert_not_called()

    def test_activation_errors_have_specific_texts(self):
        self.expired_login()
        window = self.controller.activation_window
        for result, text in [(http_error(409, "LICENCA_JA_VITALICIA"), "já é vitalícia"),
                             (http_error(403, "MAQUINA_DIFERENTE"), "outro computador"),
                             (http_error(403, "LICENCA_BLOQUEADA"), "bloqueada"),
                             (http_error(401, "INVALID_CREDENTIALS"), "E-mail ou senha inválidos"),
                             (http_error(429, "MUITAS_TENTATIVAS", retry_after=120), "2 minutos"),
                             (ApiResult(error="network"), "conectar")]:
            with self.subTest(code=result.error_code, kind=result.error):
                window.password.setText("Exemplo123")
                window.key.setText("K7QM-2XTA-9PHD-WR4E")
                window.activate.click()
                self.client.respond(result)
                self.assertIn(text, window.message.text())

    def test_key_screen_requires_email_password_and_key(self):
        self.expired_login()
        window = self.controller.activation_window
        calls = len(self.client.calls)
        window.activate.click()
        self.assertIn("chave", window.message.text())
        window.key.setText("K7QM")
        window.activate.click()
        self.assertIn("senha", window.message.text())
        self.assertEqual(len(self.client.calls), calls)

    def test_back_to_login_from_the_key_screen(self):
        self.expired_login()
        self.controller.activation_window.back.click()
        self.assertTrue(self.controller.login_window.isVisible())
        self.assertFalse(self.controller.activation_window.isVisible())

    def test_have_a_key_link_on_the_login_screen(self):
        self.storage.token = None
        self.controller.start()
        self.controller.login_window.have_key.click()
        self.assertTrue(self.controller.activation_window.isVisible())

    def test_early_renewal_uses_the_session_bearer_and_keeps_working(self):
        self.sign_in()
        self.main.renew_requested.emit()
        window = self.controller.activation_window
        self.assertTrue(window.isVisible())
        self.assertTrue(window.session_mode)
        self.assertTrue(window.cancel.isVisibleTo(window))
        self.assertFalse(window.email.isVisibleTo(window))
        window.key.setText("K7QM-2XTA-9PHD-WR4E")
        window.activate.click()
        path, payload, _ = self.client.calls[-1]
        self.assertEqual((path, payload), ("/licencas/ativar-chave",
                                           {"chave": "K7QM-2XTA-9PHD-WR4E", "id_maquina": MACHINE_ID}))
        self.assertEqual(self.client.bearers[-1], "private-access")
        self.client.respond(ApiResult(200, {**status_body(plano="ANUAL", dias_restantes=365),
                                            "plano_ativado": "ANUAL"}))
        self.assertFalse(window.isVisible())
        self.assertTrue(self.main.isEnabled())
        self.assertEqual(self.main.states[-1][0].plano, "ANUAL")
        self.assertEqual(self.store.snapshot.info.plano, "ANUAL")
        self.information.assert_called_once()
        self.assertNotIn("/auth/logout", self.paths())

    def test_early_renewal_with_expired_access_token_refreshes_once_and_retries(self):
        self.sign_in()
        self.main.renew_requested.emit()
        window = self.controller.activation_window
        window.key.setText("K7QM-2XTA-9PHD-WR4E")
        window.activate.click()
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        self.assertEqual(self.client.calls[-1][0], "/auth/refresh")
        self.assertEqual(self.client.calls[-1][1]["id_maquina"], MACHINE_ID)
        self.client.respond(ApiResult(200, ROTATED))
        self.assertEqual(self.client.calls[-1][0], "/licencas/ativar-chave")
        self.assertEqual(self.client.bearers[-1], "fake-new-access")
        self.client.respond(ApiResult(200, {**status_body(), "plano_ativado": "MENSAL"}))
        self.assertFalse(window.isVisible())

    def test_cancelling_the_renewal_keeps_the_app_running(self):
        self.sign_in()
        self.main.renew_requested.emit()
        self.controller.activation_window.cancel.click()
        self.assertFalse(self.controller.activation_window.isVisible())
        self.assertTrue(self.main.isEnabled())
        self.assertFalse(self.controller._stopped)
        self.main.renew_requested.emit()
        self.controller.activation_window.close()
        self.assertFalse(self.controller._stopped)

    def test_plans_menu_action_opens_the_payment_link(self):
        self.sign_in()
        self.main.plans_requested.emit()
        self.opener.assert_called_once_with(config.DEFAULT_PAYMENT_URL)


class PeriodicValidationTests(LicenseFlowBase):
    def test_timer_runs_every_hour_while_the_main_window_is_open(self):
        self.assertEqual(self.controller._license_timer.interval(), 60 * 60 * 1000)
        self.assertFalse(self.controller._license_timer.isActive())
        self.sign_in()
        self.assertTrue(self.controller._license_timer.isActive())

    def test_periodic_check_without_401_does_not_refresh(self):
        self.sign_in()
        calls = len(self.client.calls)
        self.controller._periodic_check()
        self.assertEqual(self.client.calls[calls][0], "/licencas/status")
        self.assertEqual(self.client.headers[-1], {"X-Id-Maquina": MACHINE_ID})
        self.client.respond(active(dias_restantes=36))
        self.assertEqual(len(self.client.calls), calls + 1)
        self.assertEqual(self.main.states[-1][0].dias_restantes, 36)
        self.assertTrue(self.main.isEnabled())

    def test_periodic_check_with_401_refreshes_with_machine_id_and_retries_once(self):
        self.sign_in()
        calls = len(self.client.calls)
        self.controller._periodic_check()
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        self.assertEqual(self.client.calls[-1][:2], ("/auth/refresh", {"refresh_token": "private-refresh",
                                                                        "id_maquina": MACHINE_ID}))
        self.client.respond(ApiResult(200, ROTATED))
        self.assertEqual(self.client.calls[-1][:2], ("/licencas/status", "fake-new-access"))
        self.client.respond(active())
        self.assertEqual(len(self.client.calls), calls + 3)
        self.assertTrue(self.main.isEnabled())
        self.assertEqual(self.storage.token, "fake-refresh-B")

    def test_periodic_check_is_skipped_while_busy_or_logging_out(self):
        self.sign_in()
        self.controller._periodic_check()
        calls = len(self.client.calls)
        self.controller._periodic_check()   # previous request still pending
        self.assertEqual(len(self.client.calls), calls)

    def test_license_that_expires_during_use_saves_warns_then_blocks(self):
        self.sign_in()
        observed = []
        self.warning.side_effect = lambda *args: observed.append((self.main.saves, self.main.isEnabled()))
        self.controller._periodic_check()
        self.client.respond(http_error(403, "LICENCA_EXPIRADA"))
        self.assertEqual(observed, [(1, True)])           # saved first, warned while still enabled
        self.assertIn("salvo automaticamente", self.warning.call_args.args[2])
        self.assertFalse(self.main.isEnabled())
        self.assertTrue(self.controller.activation_window.isVisible())
        self.assertTrue(self.controller.activation_window.session_mode)
        self.assertIsNone(self.store.snapshot)
        self.assertFalse(self.controller._license_timer.isActive())

    def test_blocked_license_during_use_saves_and_blocks(self):
        self.sign_in()
        self.controller._periodic_check()
        self.client.respond(http_error(403, "LICENCA_BLOQUEADA"))
        self.assertEqual(self.main.saves, 1)
        self.assertFalse(self.main.isEnabled())
        self.assertTrue(self.controller.login_window.isVisible())

    def test_activating_a_key_after_blocking_reopens_the_same_window(self):
        self.sign_in()
        self.controller._periodic_check()
        self.client.respond(http_error(403, "LICENCA_EXPIRADA"))
        window = self.controller.activation_window
        window.key.setText("K7QM-2XTA-9PHD-WR4E")
        window.activate.click()
        self.assertEqual(self.client.bearers[-1], "private-access")
        self.client.respond(ApiResult(200, {**status_body(), "plano_ativado": "MENSAL"}))
        self.assertTrue(self.main.isEnabled())
        self.assertIs(self.controller.main_window, self.main)
        self.factory.assert_called_once()
        self.assertTrue(self.controller._license_timer.isActive())

    def test_second_401_during_use_blocks_and_asks_for_login(self):
        self.sign_in()
        self.controller._periodic_check()
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        self.client.respond(ApiResult(200, ROTATED))
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        self.assertEqual(self.main.saves, 1)
        self.assertFalse(self.main.isEnabled())
        self.assertTrue(self.controller.login_window.isVisible())

    def test_refresh_rejected_during_use_locks_after_saving(self):
        self.sign_in()
        self.controller._periodic_check()
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        self.client.respond(http_error(401, "INVALID_REFRESH_TOKEN"))   # logged in elsewhere
        self.assertEqual(self.main.saves, 1)
        self.assertFalse(self.main.isEnabled())
        self.assertIn("outro computador", self.controller.login_window.message.text())

    def test_rate_limit_on_the_status_call_never_releases_a_blocked_window(self):
        self.sign_in()
        self.controller._periodic_check()
        self.client.respond(http_error(429, "MUITAS_TENTATIVAS", retry_after=45))
        self.assertIn("45 segundos", self.controller.login_window.message.text())
        self.assertFalse(self.main.isEnabled())


class OfflineGraceFlowTests(LicenseFlowBase):
    def with_cache(self):
        self.grace.record_success(cache_status())

    def test_api_down_at_startup_inside_72_hours_opens_with_a_visible_warning(self):
        self.with_cache()
        self.clock.advance(hours=20)
        self.restore_start()
        self.client.respond(ApiResult(error="network"))
        self.assertTrue(self.main.isVisible())
        info, remaining = self.main.states[-1]
        self.assertEqual(info.plano, "MENSAL")
        self.assertEqual(remaining, timedelta(hours=52))
        self.assertEqual(self.storage.token, "saved-refresh")   # refresh preserved
        self.assertNotIn("/licencas/status", self.paths())

    def test_server_error_without_a_contract_code_also_counts_as_unreachable(self):
        self.with_cache()
        self.restore_start()
        self.client.respond(ApiResult(502, error="http"))
        self.assertTrue(self.main.isVisible())

    def test_outside_72_hours_requires_a_connection(self):
        self.with_cache()
        self.clock.advance(hours=73)
        self.restore_start()
        self.client.respond(ApiResult(error="timeout"))
        self.factory.assert_not_called()
        self.assertIn("72 horas", self.controller.login_window.message.text())
        self.assertEqual(self.controller.login_window.enter.text(), "Tentar novamente")

    def test_rolled_back_clock_does_not_count_the_grace(self):
        self.with_cache()
        self.clock.advance(hours=30)
        self.assertTrue(self.grace.evaluate().allowed)     # high-water mark = T0 + 30h
        self.clock.now -= timedelta(hours=25)              # user sets the clock back
        self.restore_start()
        self.client.respond(ApiResult(error="network"))
        self.factory.assert_not_called()
        self.assertIn("relógio", self.controller.login_window.message.text())

    def test_no_cache_means_no_grace(self):
        self.restore_start()
        self.client.respond(ApiResult(error="network"))
        self.factory.assert_not_called()
        self.assertIn("conectar", self.controller.login_window.message.text())

    def test_contract_coded_503_is_never_released(self):
        self.with_cache()
        self.restore_start()
        self.client.respond(ApiResult(200, ROTATED))
        self.client.respond(http_error(503, "LICENCA_INDISPONIVEL"))
        self.factory.assert_not_called()
        self.assertIn("temporariamente indisponível", self.controller.login_window.message.text())

    def test_a_server_refusal_beats_the_grace_and_clears_the_cache(self):
        self.with_cache()
        self.restore_start()
        self.client.respond(ApiResult(200, ROTATED))
        self.client.respond(http_error(403, "MAQUINA_DIFERENTE"))
        self.factory.assert_not_called()
        self.assertIsNone(self.store.snapshot)

    def test_hourly_check_leaves_the_grace_when_the_api_returns(self):
        self.with_cache()
        self.clock.advance(hours=10)
        self.restore_start()
        self.client.respond(ApiResult(error="network"))
        self.assertIsNotNone(self.main.states[-1][1])
        self.clock.advance(hours=1)
        self.controller._periodic_check()
        self.assertEqual(self.client.calls[-1][0], "/auth/refresh")     # no access token yet
        self.client.respond(ApiResult(200, ROTATED))
        self.client.respond(active(dias_restantes=30))
        self.assertIsNone(self.main.states[-1][1])
        self.assertEqual(self.main.states[-1][0].dias_restantes, 30)
        self.assertFalse(self.controller._in_grace)

    def test_grace_ends_during_use_saves_and_blocks(self):
        self.sign_in()                                  # validated at T0
        self.clock.advance(hours=71)
        self.controller._periodic_check()
        self.client.respond(ApiResult(error="network"))
        self.assertTrue(self.main.isEnabled())          # still inside the grace
        self.assertEqual(self.main.states[-1][1], timedelta(hours=1))
        self.clock.advance(hours=2)
        self.controller._periodic_check()
        self.client.respond(ApiResult(error="network"))
        self.assertEqual(self.main.saves, 1)
        self.assertFalse(self.main.isEnabled())
        self.assertIn("72 horas", self.controller.login_window.message.text())

    def test_successful_validation_refreshes_the_cache(self):
        self.sign_in()
        self.assertEqual(self.store.snapshot.info.plano, "MENSAL")
        self.assertEqual(self.store.snapshot.server_now, "2026-11-20T12:00:00Z")


class LogoutCacheTests(LicenseFlowBase):
    def test_logout_clears_token_and_license_cache_but_keeps_the_machine_id(self):
        self.sign_in()
        self.assertIsNotNone(self.store.snapshot)
        machine = self.controller._get_machine_id()
        self.main.logout_requested.emit()
        self.client.respond(ApiResult(200, {"status": "ok"}))
        self.assertIsNone(self.storage.token)
        self.assertIsNone(self.store.snapshot)
        self.assertEqual(self.controller._get_machine_id(), machine)
        self.assertFalse(self.controller._license_timer.isActive())

    def test_session_ended_elsewhere_clears_the_cache(self):
        self.grace.record_success(cache_status())
        self.restore_start()
        self.client.respond(http_error(401, "INVALID_REFRESH_TOKEN"))
        self.assertIsNone(self.store.snapshot)


if __name__ == "__main__":
    unittest.main()
