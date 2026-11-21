import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dtf_manager.core import self_check
from tests.test_release_check import GOOD_APP, GOOD_PLANS, clean_env, make_tree


def run_self_check(folder):
    report = Path(folder) / "report.json"
    result = subprocess.run([sys.executable, "app.py", "--self-check", str(report)], cwd=folder,
                            env=clean_env(), capture_output=True, text=True, timeout=60)
    return result, json.loads(report.read_text(encoding="utf-8"))


@unittest.skipUnless(sys.platform == "win32", "SMBIOS and DPAPI are Windows only")
class SelfCheckCommandTests(unittest.TestCase):
    def test_passes_and_reads_the_packaged_number_without_any_environment_variable(self):
        with TemporaryDirectory() as folder:
            make_tree(folder)
            result, data = run_self_check(folder)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["release_problems"], [])
        self.assertTrue(data["packaged_whatsapp_read_without_env"])
        self.assertTrue(data["packaged_support_read_without_env"])
        self.assertTrue(data["dpapi_round_trip"] and data["dpapi_binds_entropy"])
        self.assertGreaterEqual(len(data["machine_components"]), 2)
        from dtf_manager.services.machine_id import get_machine_id
        text = json.dumps(data)
        self.assertNotIn(get_machine_id(), text)
        self.assertNotIn(GOOD_APP["whatsapp_numero"], text)       # the report holds no contact data

    def test_fails_with_the_problem_listed_for_each_blocking_condition(self):
        cases = [("empty number", {**GOOD_APP, "whatsapp_numero": ""}, GOOD_PLANS, "whatsapp_numero está vazio"),
                 ("malformed", {**GOOD_APP, "whatsapp_numero": "x1"}, GOOD_PLANS, "malformado"),
                 ("example number", {**GOOD_APP, "whatsapp_numero": "5511999999999"}, GOOD_PLANS, "valor de exemplo"),
                 ("example plans", GOOD_APP, {**GOOD_PLANS, "exemplo": True}, '"exemplo": true'),
                 ("empty support", {**GOOD_APP, "contato_suporte": ""}, GOOD_PLANS, "contato_suporte está vazio")]
        for name, app, plans, text in cases:
            with self.subTest(name), TemporaryDirectory() as folder:
                make_tree(folder, app, plans)
                result, data = run_self_check(folder)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(data["ok"])
                self.assertTrue(any(text in p for p in data["release_problems"]), data["release_problems"])

    def test_environment_override_does_not_hide_a_bad_package(self):
        with TemporaryDirectory() as folder:
            make_tree(folder, {"whatsapp_numero": "", "contato_suporte": ""})
            report = Path(folder) / "report.json"
            env = {**clean_env(), "DTF_WHATSAPP_NUMBER": "5521988887777", "DTF_SUPPORT_CONTACT": "dev@x.com"}
            result = subprocess.run([sys.executable, "app.py", "--self-check", str(report)], cwd=folder,
                                    env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(json.loads(report.read_text(encoding="utf-8"))["packaged_whatsapp_read_without_env"])


class SelfCheckUnitTests(unittest.TestCase):
    def test_failure_is_reported_with_a_non_zero_exit_code(self):
        with TemporaryDirectory() as folder, \
             patch.object(self_check, "collect", return_value={"ok": False}):
            report = Path(folder) / "report.json"
            self.assertEqual(self_check.run(str(report)), 1)
            self.assertFalse(json.loads(report.read_text(encoding="utf-8"))["ok"])


if __name__ == "__main__":
    unittest.main()
