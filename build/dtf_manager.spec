# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for DTF Manager (one-folder build). Use build.ps1 at the repo root.
# It produces dist/DTFManager/DTFManager.exe. No installer is generated.
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # Default plans/prices; users can override with DTF_PLANS_FILE without rebuilding.
    datas=[
        (str(ROOT / "dtf_manager" / "data" / "planos.json"), "dtf_manager/data"),
        # WhatsApp number and support contact shipped inside the executable.
        (str(ROOT / "dtf_manager" / "data" / "app_config.json"), "dtf_manager/data"),
        # Window/taskbar icon, loaded at runtime from assets/icon (see core/constants.py ICON_FILE).
        (str(ROOT / "assets" / "icon" / "layera.ico"), "assets/icon"),
    ],
    # win32ctypes backends are loaded dynamically; the PyInstaller hook also collects them.
    hiddenimports=["win32ctypes.pywin32.win32cred"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Development-only or unused by the application code.
        "watchdog", "gspread", "google", "tkinter", "matplotlib", "IPython", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtPdf",
        "PySide6.QtPdfWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DTFManager",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    # Icon of DTFManager.exe (Explorer, taskbar, shortcuts).
    icon=str(ROOT / "assets" / "icon" / "layera.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DTFManager")
