"""SQLite persistence for the stock tabs. All SQL lives here; every write is transactional.

Methods take an optional open connection `db` so the service can group several writes
into one transaction (everything is saved or nothing is)."""
import json
from contextlib import contextmanager
from datetime import datetime

from dtf_manager.models.stock import (
    ImportRecord, Movement, PendingRow, StockColor, StockSize,
)
from dtf_manager.services.sqlite_database import DTFDatabase
from dtf_manager.utils.stock_names import normalize_name

DEFAULT_COLORS = ("Preta", "Marrom", "Bege", "Branca")
DEFAULT_SIZES = ("P", "M", "G", "GG")
DEFAULT_COLOR_ALIASES = {"preto": "Preta", "branco": "Branca"}


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class StockRepository:
    def __init__(self, database: DTFDatabase):
        self.database = database
        self.ensure_defaults()

    @classmethod
    def default(cls, database: DTFDatabase | None = None):
        return cls(database or DTFDatabase.default())

    @contextmanager
    def tx(self, db=None):
        if db is not None:
            yield db
        else:
            with self.database.transaction() as connection:
                yield connection

    # ---- catalog -----------------------------------------------------------------
    def ensure_defaults(self) -> None:
        with self.tx() as db:
            if self.get_state("seeded", db=db):
                return
            for name in DEFAULT_COLORS:
                self.add_color(name, db=db)
            for name in DEFAULT_SIZES:
                self.add_size(name, db=db)
            ids = {color.name: color.id for color in self.colors(db=db)}
            for alias, target in DEFAULT_COLOR_ALIASES.items():
                self.set_alias("color", alias, ids[target], db=db)
            self.set_state("seeded", "1", db=db)

    def colors(self, db=None) -> list[StockColor]:
        with self.tx(db) as c:
            return [StockColor(r["id"], r["name"])
                    for r in c.execute("SELECT id, name FROM stock_colors ORDER BY id")]

    def sizes(self, db=None) -> list[StockSize]:
        with self.tx(db) as c:
            return [StockSize(r["id"], r["name"])
                    for r in c.execute("SELECT id, name FROM stock_sizes ORDER BY id")]

    def add_color(self, name: str, db=None) -> StockColor:
        with self.tx(db) as c:
            cursor = c.execute("INSERT INTO stock_colors(name, norm) VALUES(?,?)",
                               (name, normalize_name(name)))
            return StockColor(cursor.lastrowid, name)

    def delete_color(self, color_id: int, db=None) -> None:
        """Removes the color and everything that points to it."""
        with self.tx(db) as c:
            c.execute("DELETE FROM stock_levels WHERE color_id=?", (color_id,))
            c.execute("DELETE FROM stock_future WHERE color_id=?", (color_id,))
            c.execute("DELETE FROM stock_sku_colors WHERE color_id=?", (color_id,))
            c.execute("DELETE FROM stock_aliases WHERE kind='color' AND target_id=?", (color_id,))
            c.execute("DELETE FROM stock_colors WHERE id=?", (color_id,))

    def delete_size(self, size_id: int, db=None) -> None:
        """Removes the size and everything that points to it."""
        with self.tx(db) as c:
            c.execute("DELETE FROM stock_levels WHERE size_id=?", (size_id,))
            c.execute("DELETE FROM stock_future WHERE size_id=?", (size_id,))
            c.execute("DELETE FROM stock_aliases WHERE kind='size' AND target_id=?", (size_id,))
            c.execute("DELETE FROM stock_sizes WHERE id=?", (size_id,))

    def add_size(self, name: str, db=None) -> StockSize:
        with self.tx(db) as c:
            cursor = c.execute("INSERT INTO stock_sizes(name, norm) VALUES(?,?)",
                               (name, normalize_name(name)))
            return StockSize(cursor.lastrowid, name)

    # ---- stock and future ----------------------------------------------------------
    def levels(self, db=None) -> dict:
        with self.tx(db) as c:
            return {(r["color_id"], r["size_id"]): r["quantity"]
                    for r in c.execute("SELECT * FROM stock_levels")}

    def set_level(self, color_id: int, size_id: int, quantity: int, db=None) -> None:
        with self.tx(db) as c:
            c.execute(
                """INSERT INTO stock_levels(color_id,size_id,quantity) VALUES(?,?,?)
                   ON CONFLICT(color_id,size_id) DO UPDATE SET quantity=excluded.quantity""",
                (color_id, size_id, quantity))

    def future(self, db=None) -> dict:
        """(color_id, size_id) -> (quantity, separated)."""
        with self.tx(db) as c:
            return {(r["color_id"], r["size_id"]): (r["quantity"], bool(r["separated"]))
                    for r in c.execute("SELECT * FROM stock_future")}

    def replace_future(self, totals: dict, db=None) -> None:
        with self.tx(db) as c:
            c.execute("DELETE FROM stock_future")
            c.executemany(
                "INSERT INTO stock_future(color_id,size_id,quantity,separated) VALUES(?,?,?,0)",
                [(k[0], k[1], q) for k, q in totals.items() if q > 0])

    def set_separated(self, color_id: int, size_id: int, value: bool, db=None) -> None:
        with self.tx(db) as c:
            c.execute("UPDATE stock_future SET separated=? WHERE color_id=? AND size_id=?",
                      (1 if value else 0, color_id, size_id))

    # ---- equivalences ---------------------------------------------------------------
    def aliases(self, db=None) -> list[tuple[str, str, int]]:
        with self.tx(db) as c:
            return [(r["kind"], r["alias_norm"], r["target_id"])
                    for r in c.execute("SELECT * FROM stock_aliases ORDER BY kind, alias_norm")]

    def set_alias(self, kind: str, alias_norm: str, target_id: int, db=None) -> None:
        with self.tx(db) as c:
            c.execute(
                """INSERT INTO stock_aliases(kind,alias_norm,target_id) VALUES(?,?,?)
                   ON CONFLICT(kind,alias_norm) DO UPDATE SET target_id=excluded.target_id""",
                (kind, alias_norm, target_id))

    def replace_aliases(self, rows, db=None) -> None:
        with self.tx(db) as c:
            c.execute("DELETE FROM stock_aliases")
            c.executemany("INSERT INTO stock_aliases(kind,alias_norm,target_id) VALUES(?,?,?)",
                          list(rows))

    def sku_colors(self, db=None) -> dict:
        with self.tx(db) as c:
            return {r["sku_norm"]: r["color_id"]
                    for r in c.execute("SELECT * FROM stock_sku_colors")}

    def set_sku_color(self, sku_norm: str, color_id: int, db=None) -> None:
        with self.tx(db) as c:
            c.execute(
                """INSERT INTO stock_sku_colors(sku_norm,color_id) VALUES(?,?)
                   ON CONFLICT(sku_norm) DO UPDATE SET color_id=excluded.color_id""",
                (sku_norm, color_id))

    # ---- pending --------------------------------------------------------------------
    def pending(self, db=None) -> list[PendingRow]:
        with self.tx(db) as c:
            return [PendingRow(r["product_name"], r["sku"], r["variation"], r["sizes"],
                               r["quantity"], r["reason"])
                    for r in c.execute("SELECT * FROM stock_pending ORDER BY id")]

    def replace_pending(self, rows, db=None) -> None:
        with self.tx(db) as c:
            c.execute("DELETE FROM stock_pending")
            c.executemany(
                "INSERT INTO stock_pending(product_name,sku,variation,sizes,quantity,reason)"
                " VALUES(?,?,?,?,?,?)",
                [(r.product_name, r.sku, r.variation, r.sizes, r.quantity, r.reason)
                 for r in rows])

    # ---- history ---------------------------------------------------------------------
    def add_movement(self, kind, scope, color, size, before, after, note="", db=None,
                     at: str | None = None, produto: str = "camiseta") -> None:
        with self.tx(db) as c:
            c.execute(
                "INSERT INTO stock_movements(at,kind,scope,color,size,quantity,before,after,note,"
                "produto) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (at or now_text(), kind, scope, color, size, after - before, before, after, note,
                 produto))

    def movements(self, limit: int = 1000, db=None) -> list[Movement]:
        with self.tx(db) as c:
            return [Movement(r["id"], r["at"], r["kind"], r["scope"], r["color"], r["size"],
                             r["quantity"], r["before"], r["after"], r["note"], r["produto"])
                    for r in c.execute(
                        "SELECT * FROM stock_movements ORDER BY id DESC LIMIT ?", (limit,))]

    def imports(self, db=None) -> list[ImportRecord]:
        with self.tx(db) as c:
            return [self._import(r) for r in c.execute("SELECT * FROM stock_imports ORDER BY id")]

    def get_import(self, import_id: int, db=None) -> ImportRecord | None:
        with self.tx(db) as c:
            row = c.execute("SELECT * FROM stock_imports WHERE id=?", (import_id,)).fetchone()
        return None if row is None else self._import(row)

    @staticmethod
    def _import(row) -> ImportRecord:
        return ImportRecord(row["id"], row["at"], row["file_name"], row["file_hash"],
                            row["order_count"], tuple(json.loads(row["orders_json"])),
                            row["finalized_at"])

    def add_import(self, file_name, file_hash, orders, db=None) -> int:
        with self.tx(db) as c:
            return c.execute(
                "INSERT INTO stock_imports(at,file_name,file_hash,order_count,orders_json)"
                " VALUES(?,?,?,?,?)",
                (now_text(), file_name, file_hash, len(orders),
                 json.dumps(list(orders)))).lastrowid

    def delete_import(self, import_id: int, db=None) -> None:
        with self.tx(db) as c:
            c.execute("DELETE FROM stock_imports WHERE id=?", (import_id,))

    def mark_import_finalized(self, import_id: int, at: str, db=None) -> None:
        with self.tx(db) as c:
            c.execute("UPDATE stock_imports SET finalized_at=? WHERE id=?", (at, import_id))

    def finalized_orders(self, numbers, db=None) -> dict:
        numbers = list(numbers)
        found = {}
        with self.tx(db) as c:
            for start in range(0, len(numbers), 500):
                chunk = numbers[start:start + 500]
                marks = ",".join("?" * len(chunk))
                for r in c.execute(
                        f"SELECT order_number, finalized_at FROM stock_finalized_orders "
                        f"WHERE order_number IN ({marks})", chunk):
                    found[r["order_number"]] = r["finalized_at"]
        return found

    def add_finalized(self, numbers, at: str, import_id, db=None) -> None:
        with self.tx(db) as c:
            c.executemany(
                """INSERT INTO stock_finalized_orders(order_number,finalized_at,import_id)
                   VALUES(?,?,?) ON CONFLICT(order_number) DO UPDATE SET
                   finalized_at=excluded.finalized_at, import_id=excluded.import_id""",
                [(n, at, import_id) for n in numbers])

    # ---- state ---------------------------------------------------------------------------
    def get_state(self, key: str, default: str = "", db=None) -> str:
        with self.tx(db) as c:
            row = c.execute("SELECT value FROM stock_state WHERE key=?", (key,)).fetchone()
        return default if row is None else row["value"]

    def set_state(self, key: str, value: str, db=None) -> None:
        with self.tx(db) as c:
            c.execute("INSERT OR REPLACE INTO stock_state(key,value) VALUES(?,?)", (key, value))
