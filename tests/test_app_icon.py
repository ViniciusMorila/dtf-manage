"""Layera icon: valid .ico file, loadable QIcon and references in the build/installer configuration."""
import os
from pathlib import Path
import struct
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from dtf_manager.core.constants import ICON_FILE

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "assets" / "icon"
EXPECTED_SIZES = {16, 24, 32, 48, 256}


def ico_sizes(path):
    data = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), "not an .ico file"
    sizes = set()
    for index in range(count):
        width, height = struct.unpack("<BB", data[6 + 16 * index:8 + 16 * index])
        sizes.add((width or 256, height or 256))
    return sizes


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class IconFileTests(unittest.TestCase):
    def test_the_icon_files_exist_where_the_app_loads_them(self):
        self.assertEqual(ICON_FILE, ICON_DIR / "layera.ico")
        for name in ("layera.ico", "layera.svg", "layera-512.png"):
            self.assertTrue((ICON_DIR / name).is_file(), name)

    def test_the_ico_is_valid_and_has_the_expected_sizes(self):
        self.assertEqual(ico_sizes(ICON_FILE), {(s, s) for s in EXPECTED_SIZES})

    def test_qt_loads_the_icon(self):
        QApplication.instance() or QApplication([])
        icon = QIcon(str(ICON_FILE))
        self.assertFalse(icon.isNull())
        self.assertFalse(icon.pixmap(32, 32).isNull())


class ConfigurationTests(unittest.TestCase):
    def test_the_executable_uses_the_icon_and_ships_it_as_data(self):
        spec = read("build", "dtf_manager.spec")
        self.assertIn('icon=str(ROOT / "assets" / "icon" / "layera.ico")', spec)
        self.assertIn('(str(ROOT / "assets" / "icon" / "layera.ico"), "assets/icon")', spec)

    def test_the_build_script_checks_the_icon_before_packaging(self):
        script = read("build.ps1")
        self.assertIn(r"assets\icon\layera.ico", script)
        self.assertLess(script.index(r"assets\icon\layera.ico"), script.index("PyInstaller --noconfirm"))

    def test_the_installer_uses_the_icon(self):
        iss = read("installer.iss")
        self.assertIn(r"SetupIconFile=assets\icon\layera.ico", iss)
        self.assertIn(r"UninstallDisplayIcon={app}\{#MyAppExeName}", iss)
        shortcuts = [line for line in iss.splitlines() if line.startswith("Name: \"{auto")]
        self.assertEqual(len(shortcuts), 2)
        for line in shortcuts:
            self.assertIn(r'IconFilename: "{app}\{#MyAppExeName}"', line)

    def test_the_installer_identity_did_not_change(self):
        iss = read("installer.iss")
        self.assertIn("AppId={{C4111349-E156-43E9-BD99-978D3DB85F41}", iss)
        self.assertIn("AppMutex={#MyAppMutex}", iss)

    def test_the_bootstrap_sets_the_window_icon_and_the_taskbar_identity(self):
        bootstrap = read("dtf_manager", "core", "bootstrap.py")
        self.assertIn("app.setWindowIcon(QIcon(str(ICON_FILE)))", bootstrap)
        self.assertIn('SetCurrentProcessExplicitAppUserModelID("Layera.App")', bootstrap)
        call = bootstrap.index("    _set_app_user_model_id()")
        self.assertLess(call, bootstrap.index("QApplication.instance()"))   # before any window exists


if __name__ == "__main__":
    unittest.main()
