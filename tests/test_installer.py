"""Version single source, installer script rules and the app mutex (no Qt window needed)."""
import re
import sys
import unittest
import uuid
from pathlib import Path

from dtf_manager import __version__
from dtf_manager.core import app_mutex
from dtf_manager.core.version import APP_VERSION

ROOT = Path(__file__).resolve().parent.parent
ISS = (ROOT / "installer.iss").read_text(encoding="utf-8")
BUILD = (ROOT / "build.ps1").read_text(encoding="utf-8")
FIXED_APP_ID = "C4111349-E156-43E9-BD99-978D3DB85F41"


class VersionTests(unittest.TestCase):
    def test_single_source_of_the_version(self):
        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(__version__, APP_VERSION)

    def test_build_script_reads_the_same_file_with_a_matching_pattern(self):
        self.assertIn(r"dtf_manager\core\version.py", BUILD)
        text = (ROOT / "dtf_manager" / "core" / "version.py").read_text(encoding="utf-8")
        self.assertRegex(text, re.compile(r'^APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"', re.MULTILINE))


class InstallerScriptTests(unittest.TestCase):
    def test_fixed_app_id(self):
        self.assertIn("AppId={{" + FIXED_APP_ID + "}", ISS)

    def test_per_user_install_and_output_names(self):
        self.assertIn("PrivilegesRequired=lowest", ISS)
        self.assertIn("DefaultDirName={autopf}\{#MyAppName}", ISS)
        self.assertIn("OutputDir=installer_output", ISS)
        self.assertIn("OutputBaseFilename=DTFManager-Setup-{#AppVersion}", ISS)
        self.assertIn("#error", ISS)                      # refuses to build without /DAppVersion

    def test_copies_the_pyinstaller_folder_and_creates_shortcuts(self):
        self.assertIn('Source: "dist\DTFManager\*"', ISS)
        self.assertIn("recursesubdirs", ISS)
        self.assertIn("{autoprograms}", ISS)
        self.assertIn("{autodesktop}", ISS)
        self.assertIn('Name: "desktopicon"', ISS)

    def test_mutex_name_matches_the_app(self):
        self.assertIn(f'#define MyAppMutex "{app_mutex.APP_MUTEX_NAME}"', ISS)
        self.assertIn("AppMutex={#MyAppMutex}", ISS)
        self.assertIn("CloseApplications=yes", ISS)
        self.assertIn("RestartApplications=yes", ISS)

    def test_reopens_the_app_after_install_and_after_a_silent_update(self):
        runs = [line for line in ISS.splitlines() if line.startswith("Filename:")]
        self.assertEqual(len(runs), 2)
        self.assertIn("postinstall", runs[0])
        self.assertIn("skipifsilent", runs[0])
        self.assertIn("nowait", runs[1])
        self.assertIn("Check: WizardSilent", runs[1])

    def test_user_data_is_never_deleted(self):
        code = chr(10).join(line for line in ISS.splitlines() if not line.lstrip().startswith(";"))
        self.assertNotIn("[UninstallDelete]", code)
        self.assertNotIn("[InstallDelete]", code)
        self.assertNotIn("deletedirs", code.lower())

    def test_build_makes_the_installer_after_the_release_gate_and_writes_the_hash(self):
        self.assertLess(BUILD.index("--release-check"), BUILD.index("/DAppVersion="))
        self.assertLess(BUILD.index("--self-check"), BUILD.index("/DAppVersion="))
        self.assertIn("Get-FileHash -Algorithm SHA256", BUILD)
        self.assertIn(".sha256", BUILD)
        self.assertIn("ISCC.exe", BUILD)
        self.assertIn("Inno Setup 6 nao encontrado", BUILD)

    def test_installer_output_is_ignored_by_git(self):
        self.assertIn("installer_output/", (ROOT / ".gitignore").read_text(encoding="utf-8"))


@unittest.skipUnless(sys.platform == "win32", "Windows mutex")
class AppMutexTests(unittest.TestCase):
    def test_acquire_makes_the_mutex_visible_to_other_processes(self):
        name = "DTFManager-Test-" + uuid.uuid4().hex
        self.assertFalse(app_mutex.exists(name))
        self.assertTrue(app_mutex.acquire(name))
        self.assertTrue(app_mutex.exists(name))


if __name__ == "__main__":
    unittest.main()
