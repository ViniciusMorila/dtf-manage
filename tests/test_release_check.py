"""Packaged configuration (WhatsApp number, support contact) and the release gate."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dtf_manager.core import config
from dtf_manager.core.release_check import release_problems

ROOT = Path(__file__).resolve().parents[1]
GOOD_APP = {"whatsapp_numero": "5521988887777", "contato_suporte": "suporte@example.com"}
GOOD_PLANS = {"exemplo": False, "planos": [
    {"codigo": "MENSAL", "nome": "Mensal", "duracao": "1 mês", "preco": "R$ 10,00"}]}


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("DTF_")}


def make_tree(folder, app=None, plans=None):
    """Copy of the application files that the gate reads, with the given JSON content."""
    folder = Path(folder)
    shutil.copy(ROOT / "app.py", folder / "app.py")
    shutil.copy(ROOT / "build.ps1", folder / "build.ps1")
    shutil.copytree(ROOT / "dtf_manager", folder / "dtf_manager",
                    ignore=shutil.ignore_patterns("__pycache__"))
    data = folder / "dtf_manager" / "data"
    (data / "app_config.json").write_text(json.dumps(GOOD_APP if app is None else app), encoding="utf-8")
    (data / "planos.json").write_text(json.dumps(GOOD_PLANS if plans is None else plans), encoding="utf-8")
    return folder


class PackagedConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "app_config.json"
        patcher = patch.object(config, "APP_CONFIG_FILE", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, clean_env(), clear=True)
        env.start()
        self.addCleanup(env.stop)

    def write(self, **data):
        self.file.write_text(json.dumps(data), encoding="utf-8")

    def test_number_and_contact_come_from_the_packaged_file_without_environment(self):
        self.write(**GOOD_APP)
        self.assertEqual(config.whatsapp_number(), "5521988887777")
        self.assertEqual(config.support_contact(), "suporte@example.com")

    def test_environment_only_overrides(self):
        self.write(**GOOD_APP)
        with patch.dict(os.environ, {"DTF_WHATSAPP_NUMBER": "5531977776666",
                                     "DTF_SUPPORT_CONTACT": "dev@example.com"}):
            self.assertEqual(config.whatsapp_number(), "5531977776666")
            self.assertEqual(config.support_contact(), "dev@example.com")
        self.assertEqual(config.whatsapp_number(), "5521988887777")

    def test_invalid_override_is_not_replaced_by_the_packaged_value(self):
        self.write(**GOOD_APP)
        with patch.dict(os.environ, {"DTF_WHATSAPP_NUMBER": "+5531977776666"}):
            self.assertIsNone(config.whatsapp_number())

    def test_example_empty_malformed_or_missing_file_means_not_configured(self):
        for data in [{"whatsapp_numero": config.EXAMPLE_WHATSAPP}, {"whatsapp_numero": ""},
                     {"whatsapp_numero": "+5511"}, {"whatsapp_numero": 5521988887777}, {}]:
            with self.subTest(data=data):
                self.write(**data)
                self.assertIsNone(config.whatsapp_number())
        self.file.write_text("{nope", encoding="utf-8")
        self.assertIsNone(config.whatsapp_number())
        self.assertEqual(config.support_contact(), "")
        self.file.unlink()
        self.assertIsNone(config.whatsapp_number())

    def test_example_number_is_still_accepted_as_a_development_override(self):
        with patch.dict(os.environ, {"DTF_WHATSAPP_NUMBER": config.EXAMPLE_WHATSAPP}):
            self.assertEqual(config.whatsapp_number(), config.EXAMPLE_WHATSAPP)

    def test_file_saved_with_a_utf8_bom_is_still_read(self):
        # Windows editors (Notepad, PowerShell Set-Content) add a BOM.
        self.file.write_bytes(b"\xef\xbb\xbf" + json.dumps(GOOD_APP).encode("utf-8"))
        self.assertEqual(config.whatsapp_number(), "5521988887777")
        plans_file = Path(self.temp.name) / "p.json"
        plans_file.write_bytes(b"\xef\xbb\xbf" + json.dumps(GOOD_PLANS).encode("utf-8"))
        self.assertEqual(release_problems(self.file, plans_file), [])

    def test_contact_is_limited_in_size(self):
        self.write(contato_suporte="x" * 500)
        self.assertEqual(len(config.support_contact()), 120)


class ReleaseProblemsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app, self.plans = Path(self.temp.name, "a.json"), Path(self.temp.name, "p.json")

    def problems(self, app=GOOD_APP, plans=GOOD_PLANS):
        self.app.write_text(json.dumps(app), encoding="utf-8")
        self.plans.write_text(json.dumps(plans), encoding="utf-8")
        return release_problems(self.app, self.plans)

    def test_real_values_have_no_problems(self):
        self.assertEqual(self.problems(), [])

    def test_each_blocking_condition_is_reported_with_a_clear_message(self):
        cases = [
            ({**GOOD_APP, "whatsapp_numero": ""}, GOOD_PLANS, "whatsapp_numero está vazio"),
            ({**GOOD_APP, "whatsapp_numero": "   "}, GOOD_PLANS, "whatsapp_numero está vazio"),
            ({**GOOD_APP, "whatsapp_numero": "+55 11 99999"}, GOOD_PLANS, "malformado"),
            ({**GOOD_APP, "whatsapp_numero": "123"}, GOOD_PLANS, "malformado"),
            ({**GOOD_APP, "whatsapp_numero": "5511999999999"}, GOOD_PLANS, "valor de exemplo"),
            (GOOD_APP, {**GOOD_PLANS, "exemplo": True}, '"exemplo": true'),
            ({**GOOD_APP, "contato_suporte": ""}, GOOD_PLANS, "contato_suporte está vazio"),
            ({"whatsapp_numero": "5521988887777"}, GOOD_PLANS, "contato_suporte está vazio"),
        ]
        for app, plans, text in cases:
            with self.subTest(text=text, app=app):
                found = self.problems(app, plans)
                self.assertEqual(len(found), 1, found)
                self.assertIn(text, found[0])

    def test_all_problems_are_listed_together(self):
        self.assertEqual(len(self.problems({"whatsapp_numero": "5511999999999"},
                                           {**GOOD_PLANS, "exemplo": True})), 3)

    def test_missing_or_corrupt_files_block_the_release(self):
        self.assertTrue(release_problems(Path(self.temp.name, "none.json"), Path(self.temp.name, "none2.json")))
        self.app.write_text("{nope", encoding="utf-8")
        self.assertTrue(any("inválido" in p for p in release_problems(self.app, self.plans)))

    def test_gate_ignores_environment_overrides(self):
        with patch.dict(os.environ, {"DTF_WHATSAPP_NUMBER": "5521988887777",
                                     "DTF_SUPPORT_CONTACT": "dev@example.com"}):
            self.assertTrue(self.problems({"whatsapp_numero": "", "contato_suporte": ""}))

    def test_shipped_files_are_ready_for_release(self):
        # The files in the repository hold the real number, contact and prices: the gate must pass.
        self.assertEqual(release_problems(), [])


class ReleaseGateCommandTests(unittest.TestCase):
    """`app.py --release-check` and build.ps1 on a copy of the project."""

    def run_check(self, folder):
        return subprocess.run([sys.executable, "app.py", "--release-check"], cwd=folder, env=clean_env(),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_command_passes_with_real_values_and_fails_for_each_condition(self):
        cases = [("good", GOOD_APP, GOOD_PLANS, 0, ""),
                 ("empty number", {**GOOD_APP, "whatsapp_numero": ""}, GOOD_PLANS, 1, "whatsapp_numero está vazio"),
                 ("malformed", {**GOOD_APP, "whatsapp_numero": "abc"}, GOOD_PLANS, 1, "malformado"),
                 ("example number", {**GOOD_APP, "whatsapp_numero": "5511999999999"}, GOOD_PLANS, 1, "valor de exemplo"),
                 ("example plans", GOOD_APP, {**GOOD_PLANS, "exemplo": True}, 1, '"exemplo": true'),
                 ("empty support", {**GOOD_APP, "contato_suporte": ""}, GOOD_PLANS, 1, "contato_suporte está vazio")]
        for name, app, plans, code, text in cases:
            with self.subTest(name), TemporaryDirectory() as folder:
                make_tree(folder, app, plans)
                result = self.run_check(folder)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn(text, result.stderr)
                if code:
                    self.assertIn("RELEASE BLOQUEADO", result.stderr)

    @unittest.skipUnless(sys.platform == "win32", "build.ps1 needs Windows PowerShell")
    def test_build_script_fails_before_building_for_each_condition(self):
        cases = [("empty number", {**GOOD_APP, "whatsapp_numero": ""}, GOOD_PLANS, "whatsapp_numero está vazio"),
                 ("malformed", {**GOOD_APP, "whatsapp_numero": "12ab"}, GOOD_PLANS, "malformado"),
                 ("example number", {**GOOD_APP, "whatsapp_numero": "5511999999999"}, GOOD_PLANS, "valor de exemplo"),
                 ("example plans", GOOD_APP, {**GOOD_PLANS, "exemplo": True}, '"exemplo": true'),
                 ("empty support", {**GOOD_APP, "contato_suporte": ""}, GOOD_PLANS, "contato_suporte está vazio")]
        for name, app, plans, text in cases:
            with self.subTest(name), TemporaryDirectory() as folder:
                make_tree(folder, app, plans)
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "build.ps1",
                     "-Python", sys.executable], cwd=folder, env=clean_env(), capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=120)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn("Build abortado", output)
                self.assertIn(text, output)
                self.assertFalse((Path(folder) / "dist").exists())     # PyInstaller never ran
                self.assertFalse((Path(folder) / "build" / "_work").exists())


if __name__ == "__main__":
    unittest.main()
