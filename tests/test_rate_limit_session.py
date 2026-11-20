"""HTTP 429 on refresh, logout and status is a temporary failure: the session survives."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dtf_manager.services.api_client import ApiResult
from dtf_manager.core.application_controller import THROTTLE_MAX_RETRIES
from tests.license_fakes import TOKENS, active, http_error
from tests.test_license_flow import LicenseFlowBase
from tests.test_offline_grace import status as cache_status

THROTTLED = http_error(429, "MUITAS_TENTATIVAS", retry_after=45)


class StatusThrottleTests(LicenseFlowBase):
    def test_429_on_the_status_call_during_use_keeps_working_without_locking(self):
        self.sign_in()
        snapshot, token = self.store.snapshot, self.storage.token
        calls = len(self.client.calls)
        self.controller._periodic_check()
        self.client.respond(THROTTLED)
        self.assertTrue(self.main.isEnabled())
        self.assertEqual(self.main.saves, 0)                  # nothing to save: no lock
        self.warning.assert_not_called()
        self.assertFalse(self.controller.login_window.isVisible())
        self.assertIs(self.store.snapshot, snapshot)           # the cache is untouched
        self.assertEqual(self.storage.token, token)            # the session is kept
        self.assertEqual(len(self.client.calls), calls + 1)    # no retry loop
        self.assertIn("45 segundos", self.main.notices[-1])
        self.assertIn("sessão continua válida", self.main.notices[-1])
        self.assertTrue(self.controller._license_timer.isActive())

    def test_one_retry_after_the_retry_after_and_never_a_loop(self):
        self.sign_in()
        self.controller._periodic_check()
        self.client.respond(THROTTLED)
        timer = self.controller._throttle_timer
        self.assertTrue(timer.isActive())
        self.assertGreaterEqual(timer.interval(), 45_000)       # waits for Retry-After first
        for _ in range(THROTTLE_MAX_RETRIES):
            self.assertTrue(timer.isActive())
            calls = len(self.client.calls)
            timer.stop()
            self.controller._throttle_retry()                    # what the timer does
            self.assertEqual(len(self.client.calls), calls + 1)  # exactly one request
            self.client.respond(THROTTLED)
        self.assertFalse(timer.isActive())                       # the hourly check takes over
        self.assertTrue(self.main.isEnabled())

    def test_a_successful_retry_clears_the_wait(self):
        self.sign_in()
        self.controller._periodic_check()
        self.client.respond(THROTTLED)
        self.controller._throttle_timer.stop()
        self.controller._throttle_retry()
        self.client.respond(active())
        self.assertEqual(self.controller._throttle_retries, 0)
        self.assertTrue(self.main.isEnabled())

    def test_a_blocked_window_is_never_released_by_a_429(self):
        self.sign_in()
        self.controller._periodic_check()
        self.client.respond(http_error(403, "LICENCA_BLOQUEADA"))
        self.assertFalse(self.main.isEnabled())
        self.controller.check_license()
        self.client.respond(THROTTLED)
        self.assertFalse(self.main.isEnabled())
        self.assertIn("Muitas tentativas", self.controller.login_window.message.text())

    def test_status_429_at_startup_inside_the_grace_opens_with_the_cache(self):
        self.grace.record_success(cache_status())
        self.restore_start()
        self.client.respond(ApiResult(200, TOKENS))
        self.client.respond(THROTTLED)
        self.assertTrue(self.main.isVisible())
        self.assertIsNotNone(self.main.states[-1][1])           # grace remaining is shown
        self.assertIsNotNone(self.store.snapshot)
        self.assertIn("45 segundos", self.main.notices[-1])


class RefreshThrottleTests(LicenseFlowBase):
    def test_429_on_refresh_during_use_does_not_end_the_session(self):
        self.sign_in()
        token, snapshot = self.storage.token, self.store.snapshot
        self.controller._periodic_check()
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        self.assertEqual(self.client.calls[-1][0], "/auth/refresh")
        self.client.respond(THROTTLED)
        self.assertTrue(self.main.isEnabled())
        self.assertEqual(self.main.saves, 0)
        self.warning.assert_not_called()
        self.assertEqual(self.storage.token, token)             # refresh token not deleted
        self.assertIs(self.store.snapshot, snapshot)
        self.assertFalse(self.controller.login_window.isVisible())
        self.assertIn("45 segundos", self.main.notices[-1])
        self.assertTrue(self.controller._throttle_timer.isActive())

    def test_the_retry_reuses_the_saved_refresh_token(self):
        self.sign_in()
        self.controller._periodic_check()
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        self.client.respond(THROTTLED)
        saved = self.storage.token
        self.controller._throttle_timer.stop()
        self.controller._throttle_retry()
        path, payload, _ = self.client.calls[-1]
        self.assertEqual((path, payload["refresh_token"]), ("/auth/refresh", saved))

    def test_refresh_429_at_startup_inside_the_grace_uses_the_cache(self):
        self.grace.record_success(cache_status())
        self.clock.advance(hours=10)
        self.restore_start()
        self.client.respond(THROTTLED)
        self.assertTrue(self.main.isVisible())
        self.assertIsNotNone(self.main.states[-1][1])
        self.assertEqual(self.storage.token, "saved-refresh")
        self.assertIsNotNone(self.store.snapshot)
        self.assertEqual(self.paths(), ["/auth/refresh"])        # no loop, no status call

    def test_refresh_429_at_startup_without_cache_waits_with_a_disabled_retry_button(self):
        self.restore_start()
        self.client.respond(THROTTLED)
        window = self.controller.login_window
        self.assertTrue(window.isVisible())
        self.assertFalse(self.main.isVisible())
        self.assertIn("Muitas tentativas", window.message.text())
        self.assertIn("sessão continua válida", window.message.text())
        self.assertEqual(self.storage.token, "saved-refresh")
        self.assertFalse(window.enter.isEnabled())
        self.assertEqual(window.enter.text(), "Aguarde 45 s")
        for _ in range(45):
            window._cooldown.tick()
        self.assertTrue(window.enter.isEnabled())
        self.assertEqual(window.enter.text(), "Tentar novamente")
        window.enter.click()                                     # manual retry, once
        self.assertEqual(self.paths(), ["/auth/refresh", "/auth/refresh"])

    def test_activation_renewal_with_a_throttled_refresh_keeps_the_session(self):
        self.sign_in()
        self.controller.show_renewal()
        window = self.controller.activation_window
        window.key.setText("K7QM-2XTA-9PHD-WR4E")
        window.activate.click()
        self.client.respond(http_error(401, "INVALID_ACCESS_TOKEN"))
        self.client.respond(THROTTLED)
        self.assertTrue(window.session_mode)                     # still asks only for the key
        self.assertIn("Muitas tentativas", window.message.text())
        self.assertTrue(self.main.isEnabled())


class LogoutThrottleTests(LicenseFlowBase):
    def test_429_on_logout_keeps_the_session_and_does_not_offer_a_local_exit(self):
        self.sign_in()
        token = self.storage.token
        self.controller.logout()
        self.assertEqual(self.client.calls[-1][0], "/auth/logout")
        self.client.respond(THROTTLED)
        self.assertTrue(self.main.isEnabled())
        self.assertEqual(self.storage.token, token)
        self.question.assert_not_called()                        # no "sair só neste computador"
        self.assertIn("continua conectado", self.main.notices[-1])
        self.assertIn("45 segundos", self.main.notices[-1])
        self.assertTrue(self.controller._license_timer.isActive())


if __name__ == "__main__":
    unittest.main()
