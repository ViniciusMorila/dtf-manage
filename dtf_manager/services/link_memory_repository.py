from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from PySide6.QtCore import QStandardPaths

from dtf_manager.models.link_memory import ArtLinkMemory, ProductLinkIdentity, RememberedArt
from dtf_manager.services.sqlite_database import DTFDatabase


SCHEMA_VERSION = 1


class LinkMemoryStorageError(OSError):
    pass


def build_product_memory_key(identity: ProductLinkIdentity) -> str:
    variant = (
        {"state": "null"}
        if identity.variant_id is None
        else {"state": "value", "value": identity.variant_id}
    )
    return json.dumps(
        {
            "listingId": identity.listing_id,
            "sku": identity.sku,
            "variantId": variant,
            "variationNormalized": identity.variation_normalized,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def build_reduced_memory_key(identity: ProductLinkIdentity) -> str:
    return json.dumps(
        [identity.listing_id, identity.sku, identity.variation_normalized],
        ensure_ascii=False,
        separators=(",", ":"),
    )


class ProductLinkMemoryRepository:
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.load_warning: str | None = None
        self._by_key: dict[str, ArtLinkMemory] = {}
        self._by_reduced_key: dict[str, list[ArtLinkMemory]] = {}
        self._load()

    @classmethod
    def default(cls) -> "ProductLinkMemoryRepository":
        data_folder = Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        )
        return cls(data_folder / "art_link_memory.json")

    def _reindex(self) -> None:
        reduced: dict[str, list[ArtLinkMemory]] = {}
        for memory in self._by_key.values():
            reduced.setdefault(build_reduced_memory_key(memory.identity), []).append(memory)
        self._by_reduced_key = reduced

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if payload.get("schemaVersion") != SCHEMA_VERSION or not isinstance(payload.get("memories"), list):
                raise ValueError("unsupported memory schema")
            for raw in payload["memories"]:
                identity = ProductLinkIdentity(**raw["identity"])
                memory = ArtLinkMemory(
                    id=raw["id"],
                    identity=identity,
                    product_name=raw.get("product_name", ""),
                    arts=tuple(RememberedArt(**art) for art in raw["arts"]),
                    created_at=raw["created_at"],
                    updated_at=raw["updated_at"],
                    source=raw["source"],
                )
                self._by_key[build_product_memory_key(identity)] = memory
            self._reindex()
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = self.storage_path.with_suffix(f".corrupt-{timestamp}.bak")
            try:
                shutil.copy2(self.storage_path, backup)
                backup_message = f" Uma cópia foi preservada em {backup.name}."
            except OSError:
                backup_message = ""
            self.load_warning = "A memória de vínculos não pôde ser carregada." + backup_message
            self._by_key.clear()
            self._reindex()

    def _persist(self) -> None:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "memories": [asdict(memory) for memory in self._by_key.values()],
        }
        temporary = self.storage_path.with_suffix(".tmp")
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.storage_path)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise LinkMemoryStorageError("Não foi possível salvar a memória de vínculos.") from error

    def list_all(self) -> tuple[ArtLinkMemory, ...]:
        return tuple(sorted(self._by_key.values(), key=lambda value: value.updated_at, reverse=True))

    def find_for_identity(self, identity: ProductLinkIdentity) -> ArtLinkMemory | None:
        exact = self._by_key.get(build_product_memory_key(identity))
        if exact is not None:
            return exact
        candidates = self._by_reduced_key.get(build_reduced_memory_key(identity), [])
        compatible = [
            memory for memory in candidates
            if memory.identity.variant_id is None or identity.variant_id is None
        ]
        return compatible[0] if len(compatible) == 1 else None

    def upsert(self, memory: ArtLinkMemory) -> None:
        previous = dict(self._by_key)
        previous_key = next(
            (key for key, value in self._by_key.items() if value.id == memory.id), None
        )
        if previous_key is not None:
            self._by_key.pop(previous_key)
        self._by_key[build_product_memory_key(memory.identity)] = memory
        self._reindex()
        try:
            self._persist()
        except LinkMemoryStorageError:
            self._by_key = previous
            self._reindex()
            raise

    def delete_by_identity(self, identity: ProductLinkIdentity) -> bool:
        previous = dict(self._by_key)
        removed = self._by_key.pop(build_product_memory_key(identity), None)
        if removed is None:
            return False
        self._reindex()
        try:
            self._persist()
        except LinkMemoryStorageError:
            self._by_key = previous
            self._reindex()
            raise
        return True

    def delete(self, memory_id: str) -> bool:
        previous = dict(self._by_key)
        key = next((key for key, value in self._by_key.items() if value.id == memory_id), None)
        if key is None:
            return False
        self._by_key.pop(key)
        self._reindex()
        try:
            self._persist()
        except LinkMemoryStorageError:
            self._by_key = previous
            self._reindex()
            raise
        return True

    def clear(self) -> None:
        previous = dict(self._by_key)
        self._by_key.clear()
        self._reindex()
        try:
            self._persist()
        except LinkMemoryStorageError:
            self._by_key = previous
            self._reindex()
            raise


class SqliteProductLinkMemoryRepository:
    """Memória global normalizada; os arquivos de arte continuam fora do banco."""

    def __init__(self, database: DTFDatabase, legacy_path: Path | None = None):
        self.database = database
        self.load_warning: str | None = None
        if legacy_path is not None:
            self._migrate_legacy(legacy_path)

    @classmethod
    def default(cls, database: DTFDatabase | None = None):
        db = database or DTFDatabase.default()
        return cls(db, db.path.with_name("art_link_memory.json"))

    @staticmethod
    def _identity_params(identity: ProductLinkIdentity):
        return (
            identity.listing_id, identity.sku, identity.variant_id or "",
            identity.variation_normalized,
        )

    def _decode(self, row, arts) -> ArtLinkMemory:
        return ArtLinkMemory(
            id=row["id"],
            identity=ProductLinkIdentity(
                listing_id=row["listing_id"], sku=row["sku"],
                variant_id=row["variant_id"], variation_raw=row["variation_raw"],
                variation_normalized=row["variation_normalized"],
            ),
            product_name=row["product_name"],
            arts=tuple(RememberedArt(
                file_name=art["file_name"], file_reference=art["file_reference"],
                relative_path=art["relative_path"], copies_per_product=art["quantity"],
                width_cm=art["width_cm"], height_cm=art["height_cm"],
                color_mode=art["color_mode"],
            ) for art in arts),
            created_at=row["created_at"], updated_at=row["updated_at"], source=row["source"],
        )

    def list_all(self) -> tuple[ArtLinkMemory, ...]:
        with self.database.transaction() as db:
            rows = db.execute("SELECT * FROM product_link_memory ORDER BY updated_at DESC").fetchall()
            result = []
            for row in rows:
                arts = db.execute(
                    "SELECT * FROM product_link_arts WHERE memory_id=? ORDER BY position", (row["id"],)
                ).fetchall()
                result.append(self._decode(row, arts))
            return tuple(result)

    def find_for_identity(self, identity: ProductLinkIdentity) -> ArtLinkMemory | None:
        listing_id, sku, variant_key, variation = self._identity_params(identity)
        with self.database.transaction() as db:
            row = db.execute(
                "SELECT * FROM product_link_memory WHERE listing_id=? AND sku=? AND variant_key=? AND variation_normalized=?",
                (listing_id, sku, variant_key, variation),
            ).fetchone()
            if row is None:
                candidates = db.execute(
                    "SELECT * FROM product_link_memory WHERE listing_id=? AND sku=? AND variation_normalized=? "
                    "AND (variant_key='' OR ?='')",
                    (listing_id, sku, variation, variant_key),
                ).fetchall()
                row = candidates[0] if len(candidates) == 1 else None
            if row is None:
                return None
            arts = db.execute(
                "SELECT * FROM product_link_arts WHERE memory_id=? ORDER BY position", (row["id"],)
            ).fetchall()
            return self._decode(row, arts)

    def upsert(self, memory: ArtLinkMemory) -> None:
        identity = memory.identity
        try:
            with self.database.transaction() as db:
                existing = db.execute(
                    "SELECT id FROM product_link_memory WHERE listing_id=? AND sku=? AND variant_key=? AND variation_normalized=?",
                    self._identity_params(identity),
                ).fetchone()
                if existing and existing["id"] != memory.id:
                    db.execute("DELETE FROM product_link_memory WHERE id=?", (existing["id"],))
                db.execute("DELETE FROM product_link_memory WHERE id=?", (memory.id,))
                db.execute(
                    "INSERT INTO product_link_memory VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (memory.id, identity.listing_id, identity.sku, identity.variant_id,
                     identity.variant_id or "", identity.variation_raw,
                     identity.variation_normalized, memory.product_name,
                     memory.created_at, memory.updated_at, memory.source),
                )
                db.executemany(
                    "INSERT INTO product_link_arts(memory_id,position,file_name,file_reference,relative_path,width_cm,height_cm,quantity,color_mode) VALUES(?,?,?,?,?,?,?,?,?)",
                    [(memory.id, position, art.file_name, art.file_reference, art.relative_path,
                      art.width_cm, art.height_cm, art.copies_per_product, art.color_mode)
                     for position, art in enumerate(memory.arts)],
                )
        except OSError:
            raise
        except Exception as error:
            raise LinkMemoryStorageError("Não foi possível salvar a memória de vínculos.") from error

    def delete_by_identity(self, identity: ProductLinkIdentity) -> bool:
        with self.database.transaction() as db:
            cursor = db.execute(
                "DELETE FROM product_link_memory WHERE listing_id=? AND sku=? AND variant_key=? AND variation_normalized=?",
                self._identity_params(identity),
            )
            return cursor.rowcount > 0

    def delete(self, memory_id: str) -> bool:
        with self.database.transaction() as db:
            return db.execute("DELETE FROM product_link_memory WHERE id=?", (memory_id,)).rowcount > 0

    def clear(self) -> None:
        with self.database.transaction() as db:
            db.execute("DELETE FROM product_link_memory")

    def _migrate_legacy(self, legacy_path: Path) -> None:
        with self.database.transaction() as db:
            if db.execute("SELECT 1 FROM product_link_memory LIMIT 1").fetchone():
                return
        if not legacy_path.exists():
            return
        legacy = ProductLinkMemoryRepository(legacy_path)
        if legacy.load_warning:
            self.load_warning = legacy.load_warning
            return
        for memory in legacy.list_all():
            self.upsert(memory)
