from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from PySide6.QtCore import QStandardPaths

from dtf_manager.models.production_history import (
    BatchArtSnapshot, BatchItemArtSnapshot, BatchOrderItemSnapshot, BatchOrderSnapshot,
    BatchRollSettingsSnapshot, BatchSummary, BatchValidationIssueSnapshot,
    BatchValidationSnapshot, ProductionBatchHistory,
)


SCHEMA_VERSION = 1


class ProductionHistoryStorageError(OSError):
    pass


def _decode(raw: dict) -> ProductionBatchHistory:
    orders = tuple(BatchOrderSnapshot(
        order["platform_order_number"], order.get("upseller_order_number"), order.get("platform"), order.get("store_name"),
        tuple(BatchOrderItemSnapshot(
            item["product_name"], item["listing_id"], item["sku"], item["variation_raw"], item.get("variant_id"),
            item["product_quantity"], tuple(BatchItemArtSnapshot(**art) for art in item["arts"]),
        ) for item in order["items"]),
    ) for order in raw["orders"])
    return ProductionBatchHistory(
        id=raw["id"], operation_id=raw["operation_id"], batch_number=raw["batch_number"],
        created_at=raw["created_at"], mounted_at=raw.get("mounted_at"), status=raw["status"],
        summary=BatchSummary(**raw["summary"]), orders=orders,
        arts=tuple(BatchArtSnapshot(**art) for art in raw["arts"]),
        validation=BatchValidationSnapshot(
            raw["validation"]["error_count"], raw["validation"]["warning_count"], raw["validation"]["info_count"],
            tuple(BatchValidationIssueSnapshot(**issue) for issue in raw["validation"].get("warnings", [])),
        ),
        roll_settings=BatchRollSettingsSnapshot(**raw["roll_settings"]),
    )


class ProductionHistoryRepository:
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.load_warning: str | None = None
        self._batches: dict[str, ProductionBatchHistory] = {}
        self._load()

    @classmethod
    def default(cls):
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        return cls(folder / "production_batch_history.json")

    def _load(self):
        if not self.storage_path.exists(): return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if payload.get("schemaVersion") != SCHEMA_VERSION: raise ValueError("schema")
            for raw in payload.get("batches", []):
                try:
                    batch = _decode(raw); self._batches[batch.id] = batch
                except (KeyError, TypeError, ValueError):
                    self.load_warning = "Um registro inválido do histórico foi ignorado."
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            try: shutil.copy2(self.storage_path, self.storage_path.with_suffix(f".corrupt-{stamp}.bak"))
            except OSError: pass
            self.load_warning = "O histórico de lotes não pôde ser carregado; o arquivo original foi preservado."

    def _persist(self):
        payload = {"schemaVersion": SCHEMA_VERSION, "batches": [asdict(value) for value in self._batches.values()]}
        temporary = self.storage_path.with_suffix(".tmp")
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.storage_path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise ProductionHistoryStorageError("Não foi possível salvar o histórico.") from error

    def list_all(self):
        return tuple(sorted(self._batches.values(), key=lambda value: value.mounted_at or value.created_at, reverse=True))

    def get_by_id(self, batch_id): return self._batches.get(batch_id)

    def next_batch_number(self, moment: datetime | None = None):
        date = (moment or datetime.now()).strftime("%Y%m%d")
        prefix = f"DTF-{date}-"
        used = {batch.batch_number for batch in self._batches.values()}
        sequence = 1
        while f"{prefix}{sequence:03d}" in used: sequence += 1
        return f"{prefix}{sequence:03d}"

    def save(self, batch):
        existing = next((value for value in self._batches.values() if value.operation_id == batch.operation_id), None)
        if existing: return existing
        self._batches[batch.id] = batch
        try: self._persist()
        except Exception:
            self._batches.pop(batch.id, None); raise
        self.load_warning = None
        return batch

    def delete(self, batch_id):
        previous = self._batches.pop(batch_id, None)
        if previous is None: return False
        try: self._persist()
        except Exception: self._batches[batch_id] = previous; raise
        return True

    def clear(self):
        previous = dict(self._batches); self._batches.clear()
        try: self._persist(); self.load_warning = None
        except Exception: self._batches = previous; raise
