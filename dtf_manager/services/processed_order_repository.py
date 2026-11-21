from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

from dtf_manager.models.imported_order import ImportedOrder
from dtf_manager.services.import_history_analyzer import build_order_production_fingerprint
from dtf_manager.services.sqlite_database import DTFDatabase


@dataclass(frozen=True, slots=True)
class ProcessedOrderRecord:
    order_number: str
    fingerprint: str
    processed_at: str


def build_processed_order_fingerprint(order: ImportedOrder) -> str:
    canonical = build_order_production_fingerprint(order)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProcessedOrderRepository:
    def __init__(self, database: DTFDatabase):
        self.database = database

    @classmethod
    def default(cls, database: DTFDatabase | None = None):
        return cls(database or DTFDatabase.default())

    def get(self, order_number: str) -> ProcessedOrderRecord | None:
        with self.database.transaction() as db:
            row = db.execute(
                "SELECT * FROM processed_orders WHERE order_number=?", (order_number,)
            ).fetchone()
        return None if row is None else ProcessedOrderRecord(
            row["order_number"], row["fingerprint"], row["processed_at"]
        )

    def known_orders(self, numbers) -> set[str]:
        """Which of these order numbers were already mounted in a roll (one query per chunk)."""
        numbers = list(numbers)
        found: set[str] = set()
        with self.database.transaction() as db:
            for start in range(0, len(numbers), 500):
                chunk = numbers[start:start + 500]
                marks = ",".join("?" * len(chunk))
                found.update(row[0] for row in db.execute(
                    f"SELECT order_number FROM processed_orders WHERE order_number IN ({marks})",
                    chunk))
        return found

    def record(self, orders, processed_at: str | None = None) -> None:
        timestamp = processed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self.database.transaction() as db:
            db.executemany(
                """INSERT INTO processed_orders(order_number,fingerprint,processed_at) VALUES(?,?,?)
                   ON CONFLICT(order_number) DO UPDATE SET
                   fingerprint=excluded.fingerprint, processed_at=excluded.processed_at""",
                [(order.platform_order_number, build_processed_order_fingerprint(order), timestamp)
                 for order in orders],
            )

    def status(self, order: ImportedOrder) -> str:
        record = self.get(order.platform_order_number)
        if record is None:
            return "new"
        return "already_processed" if record.fingerprint == build_processed_order_fingerprint(order) else "changed"

    def migrate_history(self, batches) -> int:
        """Resume o JSON legado sem copiar detalhes, imagens ou lotes para o banco."""
        latest = {}
        for batch in batches:
            if batch.status != "mounted":
                continue
            timestamp = batch.mounted_at or batch.created_at
            for order in batch.orders:
                current = latest.get(order.platform_order_number)
                if current is None or timestamp > current[0]:
                    from dtf_manager.services.import_history_analyzer import build_historical_order_fingerprint
                    canonical = build_historical_order_fingerprint(order)
                    latest[order.platform_order_number] = (
                        timestamp, hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                    )
        with self.database.transaction() as db:
            existing = db.execute("SELECT COUNT(*) FROM processed_orders").fetchone()[0]
            if existing or not latest:
                return 0
            db.executemany(
                "INSERT INTO processed_orders(order_number,fingerprint,processed_at) VALUES(?,?,?)",
                [(number, fingerprint, timestamp)
                 for number, (timestamp, fingerprint) in latest.items()],
            )
        return len(latest)
