from pathlib import Path

APP_NAME = "Layera"
# Packaged next to the code (PyInstaller datas "assets/icon"), so this path works in development and frozen.
ICON_FILE = Path(__file__).resolve().parents[2] / "assets" / "icon" / "layera.ico"
DEFAULT_FILM_WIDTH_MM = 570.0
DEFAULT_ROLL_LENGTH_M = 30.0
DEFAULT_DPI = 300
DEFAULT_GAP_MM = 5.0
DEFAULT_COST_PER_METER = 19.90
DOWNLOADS_PATH = Path.home() / "Downloads"
