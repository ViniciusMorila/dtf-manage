"""DTF_MACHINE_ID_OVERRIDE and DTF_VALIDATION_INTERVAL_SECONDS: development only."""
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dtf_manager.core import config
from dtf_manager.core.application_controller import LICENSE_CHECK_INTERVAL_MS
from dtf_manager.services import machine_id as mid
from tests.license_fakes import FakeClient, build_controller, dispose_controller

OVERRIDE = "pc-teste-02"
OPT_IN = {"DTF_ALLOW_NO_AUTH": "1"}


def env(**values):
    return patch.dict("os.environ", values, clear=True)


def frozen():
    return patch.object(sys, "frozen", True, create=True)


class MachineIdOverrideTests(unittest.TestCase):
    def setUp(self):
        mid.reset_cache()
        self.addCleanup(mid.reset_cache)

    def test_applies_with_the_development_opt_in(self):
        for opt_in in ({"DTF_ALLOW_NO_AUTH": "1"}, {"DTF_ALLOW_DEV_OVERRIDES": "1"}):
            with self.subTest(opt_in=opt_in), env(DTF_MACHINE_ID_OVERRIDE=OVERRIDE, **opt_in):
                self.assertEqual(mid.get_machine_id(), OVERRIDE)

    def test_is_normalized_like_the_api_does(self):
        with env(DTF_MACHINE_ID_OVERRIDE="  PC-Teste-02 ", **OPT_IN):
            self.assertEqual(mid.get_machine_id(), OVERRIDE)

    def test_ignored_without_the_opt_in(self):
        with env(DTF_MACHINE_ID_OVERRIDE=OVERRIDE), patch.object(
                mid, "build_machine_id", return_value="hardware-id"):
            self.assertIsNone(config.machine_id_override())
            self.assertEqual(mid.get_machine_id(), "hardware-id")
        with env(DTF_MACHINE_ID_OVERRIDE=OVERRIDE, DTF_ALLOW_NO_AUTH="true"):
            self.assertIsNone(config.machine_id_override())

    def test_ignored_in_the_frozen_executable_even_with_the_opt_in(self):
        with env(DTF_MACHINE_ID_OVERRIDE=OVERRIDE, DTF_ALLOW_NO_AUTH="1",
                 DTF_ALLOW_DEV_OVERRIDES="1"), frozen(), patch.object(
                mid, "build_machine_id", return_value="hardware-id"):
            self.assertFalse(config.dev_overrides_allowed())
            self.assertIsNone(config.machine_id_override())
            self.assertEqual(mid.get_machine_id(), "hardware-id")

    def test_malformed_value_is_refused_instead_of_sent_to_the_api(self):
        for bad in ("curto", "tem espaço no meio", "x" * 129, "acentuação-ok"):
            with self.subTest(bad=bad), env(DTF_MACHINE_ID_OVERRIDE=bad, **OPT_IN):
                with self.assertRaises(mid.MachineIdError):
                    mid.get_machine_id()

    def test_override_does_not_change_the_cached_hardware_id(self):
        with env(DTF_MACHINE_ID_OVERRIDE=OVERRIDE, **OPT_IN):
            mid.get_machine_id()
        with env(), patch.object(mid, "build_machine_id", return_value="hardware-id"):
            self.assertEqual(mid.get_machine_id(), "hardware-id")


class ValidationIntervalTests(unittest.TestCase):
    def test_default_is_one_hour(self):
        with env():
            self.assertEqual(config.validation_interval_seconds(), 3600)
        self.assertEqual(LICENSE_CHECK_INTERVAL_MS, 3_600_000)

    def test_shortened_with_the_development_opt_in(self):
        with env(DTF_VALIDATION_INTERVAL_SECONDS="15", **OPT_IN):
            self.assertEqual(config.validation_interval_seconds(), 15)

    def test_ignored_without_the_opt_in_and_in_the_frozen_executable(self):
        with env(DTF_VALIDATION_INTERVAL_SECONDS="15"):
            self.assertEqual(config.validation_interval_seconds(), 3600)
        with env(DTF_VALIDATION_INTERVAL_SECONDS="15", **OPT_IN), frozen():
            self.assertEqual(config.validation_interval_seconds(), 3600)

    def test_invalid_values_fall_back_to_the_default(self):
        for bad in ("abc", "0", "-5", "nan", "inf"):
            with self.subTest(bad=bad), env(DTF_VALIDATION_INTERVAL_SECONDS=bad, **OPT_IN):
                self.assertEqual(config.validation_interval_seconds(), 3600)


class ControllerIntervalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def interval(self, **values):
        with env(**values):
            controller = build_controller(self.app, FakeClient())
        try:
            return controller._license_timer.interval()
        finally:
            dispose_controller(self.app, controller)

    def test_timer_uses_the_shortened_interval_only_in_development(self):
        self.assertEqual(self.interval(), 3_600_000)
        self.assertEqual(self.interval(DTF_VALIDATION_INTERVAL_SECONDS="20", **OPT_IN), 20_000)
        self.assertEqual(self.interval(DTF_VALIDATION_INTERVAL_SECONDS="20"), 3_600_000)
        with frozen():
            self.assertEqual(
                self.interval(DTF_VALIDATION_INTERVAL_SECONDS="20", **OPT_IN), 3_600_000)


if __name__ == "__main__":
    unittest.main()
