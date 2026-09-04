from contextlib import contextmanager
from pathlib import Path
import sqlite3

from PySide6.QtCore import QStandardPaths


SCHEMA_VERSION = 1


class DTFDatabase:
    """Conexão local única do aplicativo e criação idempotente do schema."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def default(cls) -> "DTFDatabase":
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        return cls(folder / "dtf_manager.db")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.transaction() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS product_link_memory (
                    id TEXT PRIMARY KEY,
                    listing_id TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    variant_id TEXT,
                    variant_key TEXT NOT NULL,
                    variation_raw TEXT NOT NULL,
                    variation_normalized TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    UNIQUE(listing_id, sku, variant_key, variation_normalized)
                );
                CREATE INDEX IF NOT EXISTS idx_product_link_reduced
                    ON product_link_memory(listing_id, sku, variation_normalized);
                CREATE TABLE IF NOT EXISTS product_link_arts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL REFERENCES product_link_memory(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    file_reference TEXT NOT NULL,
                    relative_path TEXT,
                    width_cm REAL,
                    height_cm REAL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    UNIQUE(memory_id, position)
                );
                CREATE TABLE IF NOT EXISTS active_operation (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    operation_id TEXT NOT NULL,
                    import_fingerprint TEXT NOT NULL,
                    source_file_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    workflow_stage TEXT NOT NULL,
                    current_view TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_orders (
                    order_number TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );
                """
            )
            db.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            art_columns = {
                row[1] for row in db.execute("PRAGMA table_info(product_link_arts)").fetchall()
            }
            if "color_mode" not in art_columns:
                db.execute(
                    "ALTER TABLE product_link_arts ADD COLUMN color_mode TEXT NOT NULL DEFAULT 'original'"
                )
