from contextlib import contextmanager
from pathlib import Path
import sqlite3

from PySide6.QtCore import QStandardPaths


SCHEMA_VERSION = 3
STOCK_BACKUP_SUFFIX = ".antes-do-estoque.bak"
ART_STOCK_BACKUP_SUFFIX = ".antes-das-estampas.bak"


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

    def _backup_before_stock_migration(self) -> None:
        """Copy an existing database next to the original before the stock tables are added.

        Runs once: only when the file already exists, has no stock tables yet and no backup exists."""
        backup = self.path.with_name(self.path.name + STOCK_BACKUP_SUFFIX)
        if not self.path.exists() or self.path.stat().st_size == 0 or backup.exists():
            return
        source = sqlite3.connect(self.path, timeout=10)
        try:
            has_stock = source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_colors'"
            ).fetchone()
            has_tables = source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table'"
            ).fetchone()
            if has_stock or not has_tables:
                return
            temporary = backup.with_name(backup.name + ".tmp")
            target = sqlite3.connect(temporary)
            try:
                source.backup(target)      # consistent copy, WAL included
            finally:
                target.close()
            temporary.replace(backup)
        finally:
            source.close()

    def _backup_before_art_stock_migration(self) -> None:
        """Second safety copy, before the art-stock tables are added to a database that already
        has the shirt-stock tables. Once only; an existing copy is never overwritten."""
        backup = self.path.with_name(self.path.name + ART_STOCK_BACKUP_SUFFIX)
        if not self.path.exists() or self.path.stat().st_size == 0 or backup.exists():
            return
        source = sqlite3.connect(self.path, timeout=10)
        try:
            names = {row[0] for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "stock_colors" not in names or "stock_art_files" in names:
                return
            temporary = backup.with_name(backup.name + ".tmp")
            target = sqlite3.connect(temporary)
            try:
                source.backup(target)
            finally:
                target.close()
            temporary.replace(backup)
        finally:
            source.close()

    def _initialize(self) -> None:
        self._backup_before_stock_migration()
        self._backup_before_art_stock_migration()
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
                CREATE TABLE IF NOT EXISTS stock_colors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    norm TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS stock_sizes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    norm TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS stock_levels (
                    color_id INTEGER NOT NULL REFERENCES stock_colors(id),
                    size_id INTEGER NOT NULL REFERENCES stock_sizes(id),
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
                    PRIMARY KEY(color_id, size_id)
                );
                CREATE TABLE IF NOT EXISTS stock_future (
                    color_id INTEGER NOT NULL REFERENCES stock_colors(id),
                    size_id INTEGER NOT NULL REFERENCES stock_sizes(id),
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    separated INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(color_id, size_id)
                );
                CREATE TABLE IF NOT EXISTS stock_aliases (
                    kind TEXT NOT NULL CHECK(kind IN ('color','size')),
                    alias_norm TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    PRIMARY KEY(kind, alias_norm)
                );
                CREATE TABLE IF NOT EXISTS stock_sku_colors (
                    sku_norm TEXT PRIMARY KEY,
                    color_id INTEGER NOT NULL REFERENCES stock_colors(id)
                );
                CREATE TABLE IF NOT EXISTS stock_pending (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_name TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    variation TEXT NOT NULL,
                    sizes TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    reason TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stock_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'estoque',
                    color TEXT NOT NULL,
                    size TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    before INTEGER NOT NULL,
                    after INTEGER NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS stock_imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    order_count INTEGER NOT NULL,
                    orders_json TEXT NOT NULL,
                    finalized_at TEXT
                );
                CREATE TABLE IF NOT EXISTS stock_finalized_orders (
                    order_number TEXT PRIMARY KEY,
                    finalized_at TEXT NOT NULL,
                    import_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS stock_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stock_art_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    absolute_path TEXT NOT NULL,
                    outside_folder INTEGER NOT NULL DEFAULT 0,
                    missing INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS stock_art_levels (
                    art_id INTEGER PRIMARY KEY REFERENCES stock_art_files(id),
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0)
                );
                CREATE TABLE IF NOT EXISTS stock_art_future (
                    art_id INTEGER PRIMARY KEY REFERENCES stock_art_files(id),
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    separated INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS stock_art_hashes (
                    path TEXT PRIMARY KEY,
                    size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    sha256 TEXT NOT NULL
                );
                """
            )
            db.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            movement_columns = {
                row[1] for row in db.execute("PRAGMA table_info(stock_movements)").fetchall()
            }
            if "produto" not in movement_columns:        # additive: old rows are shirts
                db.execute(
                    "ALTER TABLE stock_movements ADD COLUMN produto TEXT NOT NULL DEFAULT 'camiseta'")
            art_columns = {
                row[1] for row in db.execute("PRAGMA table_info(product_link_arts)").fetchall()
            }
            if "color_mode" not in art_columns:
                db.execute(
                    "ALTER TABLE product_link_arts ADD COLUMN color_mode TEXT NOT NULL DEFAULT 'original'"
                )
