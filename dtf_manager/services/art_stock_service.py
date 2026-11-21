"""Art stock rules (estoque de estampas): list, stock, futuro, finalize, move. No Qt.

Identity of an art = its file inside the selected art folder (relative path, key "rel:..."), or
its absolute path when a manual link points outside the folder (key "abs:..."). Different SKUs
or sizes that use the same image add up in the same record: nothing here ever creates a row per
SKU, variation or size."""
from pathlib import Path

from dtf_manager.models.art_stock import (
    ArtFile, ArtFinalizeRow, ArtRow, ArtSeparationRow, ArtSnapshot, MatchSuggestion,
)
from dtf_manager.models.stock import MOVEMENT_FINALIZE, MOVEMENT_IMPORT, MOVEMENT_MANUAL
from dtf_manager.services.art_stock_repository import ArtStockRepository
from dtf_manager.services.stock_repository import StockRepository
from dtf_manager.services.stock_service import StockError

PRODUCT = "estampa"
ARTS_UNLINKED_KEY = "art_unlinked"
ARTS_FOLDER_KEY = "art_folder"


class ArtStockService:
    def __init__(self, repository: ArtStockRepository, stock_repository: StockRepository):
        self.repository = repository
        self.stock_repository = stock_repository     # shared history, state and transactions

    # ---- folder ---------------------------------------------------------------------
    @property
    def folder(self) -> Path | None:
        text = self.stock_repository.get_state(ARTS_FOLDER_KEY)
        return Path(text) if text else None

    def art_key(self, path: str, folder: Path | None = None):
        """(key, relative path or absolute path, outside the folder?) of a file."""
        folder = folder if folder is not None else self.folder
        resolved = Path(path).resolve()
        if folder is not None:
            try:
                relative = resolved.relative_to(folder.resolve()).as_posix()
                return "rel:" + relative.casefold(), relative, False
            except ValueError:
                pass
        return "abs:" + str(resolved).casefold(), str(resolved), True

    def sync_folder(self, folder: Path | None, listing) -> None:
        """Brings the registry in line with the folder. Files that vanished but have stock are
        kept and flagged as missing; nothing is ever deleted."""
        repo = self.repository
        with repo.tx() as db:
            self.stock_repository.set_state(ARTS_FOLDER_KEY, str(folder) if folder else "", db=db)
            present = set()
            for file in listing:
                key = "rel:" + file.relative_path.casefold()
                present.add(key)
                repo.upsert_file(key, file.name, file.relative_path, file.absolute_path,
                                 False, False, db=db)
            for row in repo.files(db):
                if row.key in present:
                    continue
                gone = not (row.outside_folder and Path(row.absolute_path).is_file())
                if row.missing != gone:
                    repo.set_missing(row.id, gone, db=db)

    # ---- view ----------------------------------------------------------------------------
    def snapshot(self) -> ArtSnapshot:
        repo = self.repository
        with repo.tx() as db:
            files, levels, future = repo.files(db), repo.levels(db), repo.future(db)
            unlinked = int(self.stock_repository.get_state(ARTS_UNLINKED_KEY, "0", db=db) or 0)
        rows = []
        for f in files:
            stock, (needed, _) = levels.get(f.id, 0), future.get(f.id, (0, False))
            if f.missing and not stock and not needed:
                continue                    # a vanished file with nothing registered: hide it
            rows.append(ArtRow(f.id, f.name, f.relative_path, f.absolute_path, stock, needed,
                               f.outside_folder, f.missing))
        rows.sort(key=lambda r: r.relative_path.casefold())
        by_id = {r.art_id: r for r in rows}
        separation = tuple(
            ArtSeparationRow(art_id, by_id[art_id].relative_path, by_id[art_id].absolute_path, quantity,
                             by_id[art_id].stock, separated)
            for art_id, (quantity, separated) in sorted(
                future.items(), key=lambda kv: by_id[kv[0]].relative_path.casefold())
            if quantity > 0 and art_id in by_id)
        return ArtSnapshot(tuple(rows), separation, unlinked)

    def has_future(self) -> bool:
        return any(q > 0 for q, _ in self.repository.future().values())

    # ---- manual stock ------------------------------------------------------------------------
    def _log(self, db, kind, scope, row, before, after, note=""):
        self.stock_repository.add_movement(kind, scope, row.relative_path, "", before, after,
                                           note=note, db=db, produto=PRODUCT)

    def set_stock(self, art_id: int, value) -> bool:
        quantity = self._quantity(value)
        repo = self.repository
        with repo.tx() as db:
            row = repo.get_file(art_id, db)
            if row is None:
                raise StockError("Essa arte não existe mais.")
            before = repo.levels(db).get(art_id, 0)
            if before == quantity:
                return False
            repo.set_level(art_id, quantity, db=db)
            self._log(db, MOVEMENT_MANUAL, "estoque", row, before, quantity)
        return True

    @staticmethod
    def _quantity(value) -> int:
        text = str(value).strip()
        if not text.isdigit():
            raise StockError("Informe um número inteiro igual ou maior que zero.")
        return int(text)

    def set_separated(self, art_id: int, value: bool) -> None:
        self.repository.set_separated(art_id, value)

    # ---- futuro ----------------------------------------------------------------------------------
    def replace_future(self, count, reset_marks: bool = False,
                       note: str = "Recalculado (vínculos)") -> int:
        """REPLACES the futuro with `count` (an ArtCopyCount); never accumulates. Logs only the net
        result: one movement per art whose futuro actually changed. Returns how many changed."""
        repo = self.repository
        changed = 0
        with repo.tx() as db:
            known = {row.key: row.id for row in repo.files(db)}
            totals: dict[int, int] = {}
            for art in count.arts.values():
                key, relative, outside = self.art_key(art.file_reference)
                art_id = known.get(key)
                if art_id is None:
                    art_id = repo.upsert_file(key, Path(art.file_reference).name, relative,
                                              art.file_reference, outside,
                                              not Path(art.file_reference).is_file(), db=db)
                    known[key] = art_id
                totals[art_id] = totals.get(art_id, 0) + art.copies
            old = repo.future(db)
            files = {f.id: f for f in repo.files(db)}
            for art_id in sorted(set(old) | set(totals)):
                before, after = old.get(art_id, (0, False))[0], totals.get(art_id, 0)
                if before != after:
                    changed += 1
                    self._log(db, MOVEMENT_IMPORT, "futuro", files[art_id], before, after, note)
            repo.replace_future(totals, keep_marks=not reset_marks, db=db)
            self.stock_repository.set_state(ARTS_UNLINKED_KEY, str(count.unlinked_items), db=db)
        return changed

    # ---- finalize / cancel (used inside the shirt-stock transaction) -----------------------------
    def finalize_preview(self, db=None) -> tuple[ArtFinalizeRow, ...]:
        repo = self.repository
        with repo.tx(db) as c:
            future, levels = repo.future(c), repo.levels(c)
            names = {f.id: f.relative_path for f in repo.files(c)}
        rows = []
        for art_id, (quantity, _) in sorted(future.items(), key=lambda kv: names[kv[0]].casefold()):
            have = levels.get(art_id, 0)
            rows.append(ArtFinalizeRow(names[art_id], quantity, have, max(0, have - quantity),
                                       max(0, quantity - have)))
        return tuple(rows)

    def finalize_apply(self, db) -> tuple[ArtFinalizeRow, ...]:
        """Deducts the futuro from the stock (never below zero), logs it and clears the futuro.
        Runs on the caller's connection so shirts and arts are saved together or not at all."""
        repo = self.repository
        future, levels = repo.future(db), repo.levels(db)
        files = {f.id: f for f in repo.files(db)}
        rows = []
        for art_id, (quantity, _) in sorted(future.items(),
                                            key=lambda kv: files[kv[0]].relative_path.casefold()):
            before = levels.get(art_id, 0)
            after = max(0, before - quantity)
            shortage = max(0, quantity - before)
            rows.append(ArtFinalizeRow(files[art_id].relative_path, quantity, before, after,
                                       shortage))
            repo.set_level(art_id, after, db=db)
            note = f"Pedidos finalizados: {quantity} cópia(s)"
            if shortage:
                note += f"; faltaram {shortage} no estoque (ficou em 0)"
            self._log(db, MOVEMENT_FINALIZE, "estoque", files[art_id], before, after, note)
        repo.replace_future({}, db=db)
        self.stock_repository.set_state(ARTS_UNLINKED_KEY, "0", db=db)
        return tuple(rows)

    def cancel_future(self, db) -> None:
        repo = self.repository
        files = {f.id: f for f in repo.files(db)}
        for art_id, (quantity, _) in sorted(repo.future(db).items()):
            self._log(db, MOVEMENT_IMPORT, "futuro", files[art_id], quantity, 0,
                      "Operação cancelada")
        repo.replace_future({}, db=db)
        self.stock_repository.set_state(ARTS_UNLINKED_KEY, "0", db=db)

    # ---- move stock to another file ----------------------------------------------------------------
    def move_stock(self, from_id: int, to_id: int) -> int:
        """Moves ALL the stock of one art record to another (renames, folder changes). Both
        sides are logged. Only ever called after the user confirmed."""
        if from_id == to_id:
            raise StockError("Escolha dois arquivos diferentes.")
        repo = self.repository
        with repo.tx() as db:
            source, target = repo.get_file(from_id, db), repo.get_file(to_id, db)
            if source is None or target is None:
                raise StockError("Essa arte não existe mais.")
            levels = repo.levels(db)
            moved = levels.get(from_id, 0)
            if moved <= 0:
                raise StockError("O arquivo de origem não tem estoque para mover.")
            before_to = levels.get(to_id, 0)
            repo.set_level(from_id, 0, db=db)
            repo.set_level(to_id, before_to + moved, db=db)
            self._log(db, MOVEMENT_MANUAL, "estoque", source, moved, 0,
                      f"Estoque movido para {target.relative_path}")
            self._log(db, MOVEMENT_MANUAL, "estoque", target, before_to, before_to + moved,
                      f"Estoque recebido de {source.relative_path}")
        return moved

    def suggest_matches(self) -> list[MatchSuggestion]:
        """Proposals only (never applied here): a missing file with stock and a file of the
        folder with the same file name. Names that match more than one file are left out."""
        repo = self.repository
        files, levels = repo.files(), repo.levels()
        present: dict[str, list] = {}
        for f in files:
            if not f.missing:
                present.setdefault(f.name.casefold(), []).append(f)
        suggestions, taken = [], set()
        for f in files:
            stock = levels.get(f.id, 0)
            if not f.missing or stock <= 0:
                continue
            candidates = [c for c in present.get(f.name.casefold(), []) if c.id not in taken]
            if len(candidates) == 1:
                taken.add(candidates[0].id)
                suggestions.append(MatchSuggestion(f.id, candidates[0].id, f.relative_path,
                                                   candidates[0].relative_path, stock))
        return suggestions

    def has_missing_with_stock(self) -> bool:
        levels = self.repository.levels()
        return any(f.missing and levels.get(f.id, 0) > 0 for f in self.repository.files())

    def candidates_to_receive(self, exclude_id: int):
        """Files that can receive a move: those present in the folder, except the source."""
        return [f for f in self.repository.files() if not f.missing and f.id != exclude_id]

    def sources_with_stock(self):
        levels = self.repository.levels()
        return [f for f in self.repository.files() if levels.get(f.id, 0) > 0]

    # ---- duplicates (warning only) ---------------------------------------------------------------------
    def present_files(self) -> list[ArtFile]:
        """Files currently in the folder, as light ArtFile entries (for the hash scan)."""
        files = []
        for f in self.repository.files():
            if f.missing:
                continue
            try:
                stat = Path(f.absolute_path).stat()
            except OSError:
                continue
            files.append(ArtFile(f.relative_path, f.absolute_path, f.name, stat.st_size,
                                 stat.st_mtime))
        return files
