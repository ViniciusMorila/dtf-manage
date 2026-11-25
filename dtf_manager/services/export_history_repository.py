"""History of exported documents: one short summary per export (date, length used, project value).

Stored as a small JSON file in the application data folder, outside the production database."""
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
from uuid import uuid4

from PySide6.QtCore import QStandardPaths

SCHEMA_VERSION = 1
WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sábado", "domingo")


class ExportHistoryStorageError(OSError):
    pass


@dataclass(frozen=True, slots=True)
class ExportRecord:
    id: str
    exported_at: str            # local time, ISO 8601 without zone: 2026-11-24T14:32:05
    name: str                   # name the user gave the exported document
    used_length_m: float
    cost_per_meter: float
    project_value: float        # used length x price per meter, the "Valor do projeto" of the summary
    parts: int                  # how many PNG files the export produced

    @classmethod
    def new(cls, name: str, used_length_m: float, cost_per_meter: float, parts: int = 1,
            when: datetime | None = None) -> "ExportRecord":
        moment = (when or datetime.now()).replace(microsecond=0)
        return cls(str(uuid4()), moment.isoformat(), name.strip(), round(float(used_length_m), 4),
                   round(float(cost_per_meter), 4), round(float(used_length_m) * float(cost_per_meter), 2),
                   max(1, int(parts)))

    @property
    def moment(self) -> datetime:
        return datetime.fromisoformat(self.exported_at)

    @property
    def weekday(self) -> str:
        return WEEKDAYS[self.moment.weekday()]


class ExportHistoryRepository:
    def __init__(self, storage_path: Path):
        self.storage_path = Path(storage_path)
        self.load_warning: str | None = None
        self._records: list[ExportRecord] = []
        self._load()

    @classmethod
    def default(cls) -> "ExportHistoryRepository":
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        return cls(folder / "export_history.json")

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if payload.get("schemaVersion") != SCHEMA_VERSION:
                raise ValueError("schema")
            for raw in payload.get("exports", []):
                try:
                    record = ExportRecord(**raw)
                    record.moment                       # validates the date
                    self._records.append(record)
                except (TypeError, ValueError):
                    self.load_warning = "Um registro inválido do histórico foi ignorado."
        except (OSError, ValueError, TypeError, AttributeError):
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            try:
                shutil.copy2(self.storage_path, self.storage_path.with_suffix(f".corrupt-{stamp}.bak"))
            except OSError:
                pass
            self._records = []
            self.load_warning = "O histórico de exportações não pôde ser carregado; o arquivo original foi preservado."

    def _persist(self) -> None:
        payload = {"schemaVersion": SCHEMA_VERSION, "exports": [asdict(record) for record in self._records]}
        temporary = self.storage_path.with_suffix(".tmp")
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.storage_path)
        except OSError as error:
            raise ExportHistoryStorageError("Não foi possível gravar o histórico de exportações.") from error

    def add(self, record: ExportRecord) -> None:
        self._records.append(record)
        try:
            self._persist()
        except ExportHistoryStorageError:
            self._records.remove(record)
            raise

    def remove(self, record_id: str) -> None:
        """Deletes one record. Memory only changes when the file was written."""
        previous = self._records
        self._records = [record for record in previous if record.id != record_id]
        try:
            self._persist()
        except OSError:
            self._records = previous
            raise

    def clear(self) -> None:
        """Deletes every record. Memory is only emptied when the file was written."""
        previous, self._records = self._records, []
        try:
            self._persist()
        except OSError:
            self._records = previous
            raise

    def list_all(self) -> list[ExportRecord]:
        """Newest first."""
        return sorted(self._records, key=lambda record: record.exported_at, reverse=True)
