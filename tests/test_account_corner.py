"""Greeting in the top corner and the key-only renewal screen."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dtf_manager.services.api_client import ApiResult
from tests.license_fakes import http_error
from tests.test_license_flow import FakeMain, LicenseFlowBase
from tests.test_offline_grace import status as cache_status


class NamedMain(FakeMain):
    def __init__(self):
        super().__init__()
        self.names = []

    def set_user_name(self, name):
        self.names.append(name)


class GreetingTests(LicenseFlowBase):
    def setUp(self):
        super().setUp()
        self.main.deleteLater()
        self.main = NamedMain()
        self.factory.return_value = self.main

    def test_unknown_name_is_fetched_once_from_me_after_the_license_check(self):
        self.sign_in()
        self.assertEqual(self.main.names, [""])
        path, token, _ = self.client.calls[-1]
        self.assertEqual(path, "/me")
        self.assertEqual(token, self.controller.auth.access_token)
        self.client.respond(ApiResult(200, {"id": "1", "name": "  Maria Silva ", "email": "m@x.com"}))
        self.assertEqual(self.main.names[-1], "Maria Silva")
        self.assertEqual(self.controller._contact["name"], "Maria Silva")
        self.assertEqual(self.paths().count("/me"), 1)

    def test_a_failed_profile_request_is_silent_and_does_not_block(self):
        self.sign_in()
        self.client.respond(http_error(500, "ERRO"))
        self.assertEqual(self.main.names, [""])
        self.assertTrue(self.main.isEnabled())
        self.warning.assert_not_called()

    def test_name_cached_with_the_license_needs_no_request(self):
        self.grace.record_success(cache_status(), {"name": "Ana Paula"})
        self.sign_in()
        self.assertEqual(self.main.names[-1], "Ana Paula")
        self.assertNotIn("/me", self.paths())

    def test_name_from_sign_up_needs_no_request(self):
        self.controller._contact["name"] = "Joana"
        self.controller._last_email = "user@example.com"
        self.sign_in()
        self.assertEqual(self.main.names[-1], "Joana")
        self.assertNotIn("/me", self.paths())

    def test_another_account_is_never_greeted_with_the_previous_name(self):
        self.controller._contact["name"] = "Joana"
        self.controller._last_email = "joana@example.com"
        self.sign_in()                       # signs in as user@example.com
        self.assertEqual(self.main.names[0], "")
        self.assertEqual(self.client.calls[-1][0], "/me")


class RenewalScreenTests(LicenseFlowBase):
    def test_renewal_asks_only_for_the_key(self):
        self.sign_in()
        self.main.renew_requested.emit()
        window = self.controller.activation_window
        window.set_payment_site(True)
        self.assertTrue(window.key.isVisibleTo(window))
        self.assertTrue(window.activate.isVisibleTo(window))
        self.assertFalse(window.subscribe.isVisibleTo(window))
        self.assertFalse(window.plans.isVisibleTo(window))
        self.assertFalse(window.plans_text.isVisibleTo(window))

    def test_expired_license_screen_still_offers_to_subscribe(self):
        self.sign_in()
        self.main.renew_requested.emit()
        window = self.controller.activation_window
        window.set_payment_site(True)
        window.set_mode(session=False, trial_ended=True)
        self.assertTrue(window.subscribe.isVisibleTo(window))
        self.assertTrue(window.plans.isVisibleTo(window))
        self.assertTrue(window.plans_text.isVisibleTo(window))


if __name__ == "__main__":
    unittest.main()
