"""SQLite persistence of the art stock (tables stock_art_*). Same pattern as StockRepository:
every method takes an optional open connection so several writes can share one transaction."""
from contextlib import contextmanager

from dtf_manager.models.art_stock import ArtFileRow
from dtf_manager.services.sqlite_database import DTFDatabase


class ArtStockRepository:
    def __init__(self, database: DTFDatabase):
        self.database = database

    @contextmanager
    def tx(self, db=None):
        if db is not None:
            yield db
        else:
            with self.database.transaction() as connection:
                yield connection

    # ---- files ---------------------------------------------------------------------
    @staticmethod
    def _file(row) -> ArtFileRow:
        return ArtFileRow(row["id"], row["key"], row["name"], row["relative_path"],
                          row["absolute_path"], bool(row["outside_folder"]), bool(row["missing"]))

    def files(self, db=None) -> list[ArtFileRow]:
        with self.tx(db) as c:
            return [self._file(r) for r in c.execute("SELECT * FROM stock_art_files ORDER BY id")]

    def get_file(self, art_id: int, db=None) -> ArtFileRow | None:
        with self.tx(db) as c:
            row = c.execute("SELECT * FROM stock_art_files WHERE id=?", (art_id,)).fetchone()
        return None if row is None else self._file(row)

    def upsert_file(self, key, name, relative_path, absolute_path, outside, missing, db=None) -> int:
        with self.tx(db) as c:
            c.execute(
                """INSERT INTO stock_art_files(key,name,relative_path,absolute_path,outside_folder,missing)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET name=excluded.name,
                   relative_path=excluded.relative_path, absolute_path=excluded.absolute_path,
                   outside_folder=excluded.outside_folder, missing=excluded.missing""",
                (key, name, relative_path, absolute_path, 1 if outside else 0, 1 if missing else 0))
            return c.execute("SELECT id FROM stock_art_files WHERE key=?", (key,)).fetchone()["id"]

    def set_missing(self, art_id: int, missing: bool, db=None) -> None:
        with self.tx(db) as c:
            c.execute("UPDATE stock_art_files SET missing=? WHERE id=?",
                      (1 if missing else 0, art_id))

    # ---- stock and future ----------------------------------------------------------------
    def levels(self, db=None) -> dict:
        with self.tx(db) as c:
            return {r["art_id"]: r["quantity"] for r in c.execute("SELECT * FROM stock_art_levels")}

    def set_level(self, art_id: int, quantity: int, db=None) -> None:
        with self.tx(db) as c:
            c.execute(
                """INSERT INTO stock_art_levels(art_id,quantity) VALUES(?,?)
                   ON CONFLICT(art_id) DO UPDATE SET quantity=excluded.quantity""",
                (art_id, quantity))

    def future(self, db=None) -> dict:
        """art_id -> (quantity, separated)."""
        with self.tx(db) as c:
            return {r["art_id"]: (r["quantity"], bool(r["separated"]))
                    for r in c.execute("SELECT * FROM stock_art_future")}

    def replace_future(self, totals: dict, keep_marks: bool = False, db=None) -> None:
        with self.tx(db) as c:
            marks = {}
            if keep_marks:
                marks = {r["art_id"]: r["separated"]
                         for r in c.execute("SELECT art_id, separated FROM stock_art_future")}
            c.execute("DELETE FROM stock_art_future")
            c.executemany(
                "INSERT INTO stock_art_future(art_id,quantity,separated) VALUES(?,?,?)",
                [(art_id, quantity, marks.get(art_id, 0))
                 for art_id, quantity in totals.items() if quantity > 0])

    def set_separated(self, art_id: int, value: bool, db=None) -> None:
        with self.tx(db) as c:
            c.execute("UPDATE stock_art_future SET separated=? WHERE art_id=?",
                      (1 if value else 0, art_id))

    # ---- content hashes (cache) ------------------------------------------------------------
    def hashes(self, db=None) -> dict:
        with self.tx(db) as c:
            return {r["path"]: (r["size"], r["mtime"], r["sha256"])
                    for r in c.execute("SELECT * FROM stock_art_hashes")}

    def save_hashes(self, rows, db=None) -> None:
        with self.tx(db) as c:
            c.executemany(
                """INSERT INTO stock_art_hashes(path,size,mtime,sha256) VALUES(?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,
                   sha256=excluded.sha256""", list(rows))
