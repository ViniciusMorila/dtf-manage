from dataclasses import asdict
import json
from pathlib import Path

from dtf_manager.models.active_operation import ActiveProductionOperation
from dtf_manager.services.active_operation_repository import (
    ActiveOperationRepository, ActiveOperationStorageError,
    JsonActiveOperationRepository, _decode_operation,
)
from dtf_manager.services.sqlite_database import DTFDatabase


class SqliteActiveOperationRepository(ActiveOperationRepository):
    """Persiste exatamente uma operação ativa no registro singleton 1."""

    def __init__(self, database: DTFDatabase, legacy_path: Path | None = None):
        self.database = database
        self.load_warning: str | None = None
        if legacy_path is not None:
            self._migrate_legacy(legacy_path)

    @classmethod
    def default(cls, database: DTFDatabase | None = None):
        db = database or DTFDatabase.default()
        return cls(db, db.path.with_name("active_operation.json"))

    def load_active(self) -> ActiveProductionOperation | None:
        try:
            with self.database.transaction() as db:
                row = db.execute("SELECT payload_json FROM active_operation WHERE singleton_id=1").fetchone()
            if row is None:
                return None
            operation = _decode_operation(json.loads(row["payload_json"]))
            self.load_warning = None
            return operation
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.load_warning = "A operação em andamento não pôde ser carregada do banco local."
            return None

    def save_active(self, operation: ActiveProductionOperation) -> None:
        try:
            payload = json.dumps(asdict(operation), ensure_ascii=False, separators=(",", ":"))
            with self.database.transaction() as db:
                db.execute(
                    """INSERT INTO active_operation(
                       singleton_id,operation_id,import_fingerprint,source_file_name,
                       created_at,updated_at,workflow_stage,current_view,payload_json
                       ) VALUES(1,?,?,?,?,?,?,?,?)
                       ON CONFLICT(singleton_id) DO UPDATE SET
                       operation_id=excluded.operation_id, import_fingerprint=excluded.import_fingerprint,
                       source_file_name=excluded.source_file_name, created_at=excluded.created_at,
                       updated_at=excluded.updated_at, workflow_stage=excluded.workflow_stage,
                       current_view=excluded.current_view, payload_json=excluded.payload_json""",
                    (operation.id, operation.import_fingerprint, operation.source_file_name,
                     operation.created_at, operation.updated_at, operation.workflow_stage,
                     operation.current_view, payload),
                )
            self.load_warning = None
        except Exception as error:
            raise ActiveOperationStorageError("Não foi possível salvar a operação em andamento.") from error

    def clear_active(self) -> None:
        try:
            with self.database.transaction() as db:
                db.execute("DELETE FROM active_operation WHERE singleton_id=1")
        except Exception as error:
            raise ActiveOperationStorageError("Não foi possível concluir a operação em andamento.") from error

    def _migrate_legacy(self, legacy_path: Path) -> None:
        with self.database.transaction() as db:
            if db.execute("SELECT 1 FROM active_operation WHERE singleton_id=1").fetchone():
                return
        legacy = JsonActiveOperationRepository(legacy_path)
        operation = legacy.load_active()
        if legacy.load_warning:
            self.load_warning = legacy.load_warning
        elif operation is not None:
            self.save_active(operation)
