from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from PySide6.QtCore import QStandardPaths

from dtf_manager.models.active_operation import (
    ActiveOperationMetadata,
    ActiveProductionOperation,
    ManualLinkingSessionSnapshot,
)
from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt


class ActiveOperationStorageError(OSError):
    pass


class ActiveOperationRepository(ABC):
    @abstractmethod
    def load_active(self) -> ActiveProductionOperation | None: ...

    @abstractmethod
    def save_active(self, operation: ActiveProductionOperation) -> None: ...

    @abstractmethod
    def clear_active(self) -> None: ...

    def has_active(self) -> bool:
        return self.load_active() is not None


def _decode_order(raw) -> ImportedOrder:
    items = [ImportedOrderItem(
        id=item["id"], order_id=item["order_id"],
        platform_order_number=item["platform_order_number"],
        product_name=item["product_name"], listing_id=item["listing_id"], sku=item["sku"],
        variation_raw=item["variation_raw"], variation_normalized=item["variation_normalized"],
        variant_id=item.get("variant_id"), product_image_url=item.get("product_image_url"),
        product_price=item.get("product_price"), product_quantity=item["product_quantity"],
        linked_arts=[LinkedArt(**art) for art in item.get("linked_arts", [])],
        link_status=item.get("link_status", "unlinked"),
        automatic_links_confirmed=item.get("automatic_links_confirmed", False),
    ) for item in raw.get("items", [])]
    return ImportedOrder(
        raw["id"], raw["platform_order_number"], raw.get("upseller_order_number"),
        raw.get("platform"), raw.get("store_name"), items,
    )


def _decode_operation(raw) -> ActiveProductionOperation:
    return ActiveProductionOperation(
        schema_version=raw["schema_version"], id=raw["id"],
        import_fingerprint=raw["import_fingerprint"],
        source_file_name=raw.get("source_file_name"), created_at=raw["created_at"],
        updated_at=raw["updated_at"], workflow_stage=raw["workflow_stage"],
        current_view=raw.get("current_view"),
        imported_orders=tuple(_decode_order(order) for order in raw["imported_orders"]),
        manual_linking_state=(
            ManualLinkingSessionSnapshot(**raw["manual_linking_state"])
            if raw.get("manual_linking_state") else None
        ),
        metadata=ActiveOperationMetadata(**raw["metadata"]),
    )


class JsonActiveOperationRepository(ActiveOperationRepository):
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.backup_path = storage_path.with_name("active_operation.backup.json")
        self.load_warning: str | None = None

    @classmethod
    def default(cls):
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        return cls(folder / "active_operation.json")

    def load_active(self) -> ActiveProductionOperation | None:
        if not self.storage_path.exists():
            return None
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if raw.get("schema_version") != 1:
                raise ValueError("unsupported schema")
            operation = _decode_operation(raw)
            self.load_warning = None
            return operation
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.load_warning = "A operação em andamento não pôde ser carregada. O arquivo foi preservado."
            return None

    def save_active(self, operation: ActiveProductionOperation) -> None:
        temporary = self.storage_path.with_suffix(".tmp")
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(asdict(operation), ensure_ascii=False, indent=2), encoding="utf-8")
            if self.storage_path.exists():
                shutil.copy2(self.storage_path, self.backup_path)
            temporary.replace(self.storage_path)
            self.load_warning = None
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise ActiveOperationStorageError("Não foi possível salvar a operação em andamento.") from error

    def clear_active(self) -> None:
        try:
            self.storage_path.unlink(missing_ok=True)
        except OSError as error:
            raise ActiveOperationStorageError("Não foi possível concluir a operação em andamento.") from error
