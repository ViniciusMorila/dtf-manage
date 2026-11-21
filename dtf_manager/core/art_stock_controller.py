"""Decides everything in the "Estoque de estampas" tab. The tab only shows data and emits
signals; the dialogs only ask questions (through `prompts`); the rules live in ArtStockService."""
import json
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from dtf_manager.services.art_directory_scanner import ArtDirectoryError
from dtf_manager.services.art_folder_listing import list_art_files
from dtf_manager.services.print_plan_service import ArtCopyCount, CountedArt, count_art_copies
from dtf_manager.services.stock_service import StockError

DUPLICATE_SCAN_DELAY_MS = 1500          # after the list is on screen: never delays opening the tab


class ArtStockController(QObject):
    changed = Signal()                  # the art stock or its futuro changed
    manual_consumed = Signal()          # finalize/cancel settled the hand-added copies

    def __init__(self, service, prompts, tab=None, orders_provider=None, folder_provider=None,
                 scanner=None, thumbs=None, listing=list_art_files, parent=None):
        super().__init__(parent)
        self.service = service
        self.prompts = prompts
        self.tab = tab
        self.thumbs = thumbs
        self._orders = orders_provider or (lambda: ())
        self._folder_provider = folder_provider or (lambda: None)
        self._scanner = scanner
        self._listing = listing
        self._folder: Path | None = None
        self._recalc_scheduled = False
        self._manual: dict[str, int] = {}     # arts added by hand on the roll: path -> copies
        self._had_manual = False
        self._applied: dict[str, int] = {}    # hand-added copies already inside the stored futuro
        self.identical_groups: list[list[str]] = []
        if scanner is not None:
            scanner.found.connect(self._identical_found)
        if tab is not None:
            tab.stock_edit_requested.connect(self.edit_stock)
            tab.separated_changed.connect(self.service.set_separated)
            tab.move_requested.connect(self.move_stock)
            tab.suggest_requested.connect(self.suggest_matches)
            tab.copy_missing_requested.connect(self.copy_missing)

    # ---- folder and view ---------------------------------------------------------------
    @property
    def has_future(self) -> bool:
        return self.service.has_future()

    def set_folder(self, folder: Path | None) -> None:
        """The art folder chosen in the DTF tab (or changed/refreshed there)."""
        self._folder = Path(folder) if folder else None
        listing = ()
        if self._folder is not None:
            try:
                listing = self._listing(self._folder)
            except ArtDirectoryError as error:
                self.prompts.warn("Estoque de estampas", str(error))
        self.service.sync_folder(self._folder, listing)
        self.refresh()
        if self._scanner is not None and listing:
            QTimer.singleShot(DUPLICATE_SCAN_DELAY_MS, self.start_duplicate_scan)

    def refresh_folder(self) -> None:
        """Re-reads the folder (the user opened the tab or pressed refresh)."""
        self.set_folder(self._folder or self._folder_provider())

    def refresh(self) -> None:
        snapshot = self.service.snapshot()
        if self.tab is not None:
            self.tab.render(snapshot, str(self._folder) if self._folder else "",
                            self.service.has_missing_with_stock())
        self.changed.emit()

    def _try(self, action, *args):
        try:
            return action(*args), True
        except StockError as error:
            self.prompts.warn("Estoque de estampas", str(error))
            return None, False

    # ---- editing --------------------------------------------------------------------------
    def edit_stock(self, art_id: int, text: str) -> None:
        self._try(self.service.set_stock, art_id, text)
        QTimer.singleShot(0, self.refresh)          # after the table finished its own edit signal

    # ---- futuro: recalculated whenever the links change ------------------------------------------
    def counted_orders(self):
        """Loaded orders that count: the same list the shirt stock decided on the import (finalized
        orders that were left out stay out)."""
        counted = set(json.loads(
            self.service.stock_repository.get_state("counted_orders", "[]") or "[]"))
        return [order for order in self._orders() if order.platform_order_number in counted]

    def recalculate(self, reset_marks: bool = False) -> bool:
        """Replaces the arts futuro with the copies of the linked items of the counted orders.
        Skipped while no order is loaded (cancel/finalize clear the futuro on their own)."""
        loaded = list(self._orders())
        counted = json.loads(self.service.stock_repository.get_state("counted_orders", "[]") or "[]")
        if not loaded and counted:
            # An operation is pending but its orders are not loaded (app reopened, "Continuar" not
            # pressed yet): keep its futuro as it is and only add/remove the hand-added copies.
            if not self._manual and not self._applied:
                return False
            count = self._with_manual(self._pending_count())
        else:
            if not loaded and not self._manual and not self._had_manual:
                return False
            if loaded and counted and not ({o.platform_order_number for o in loaded} & set(counted)):
                return False    # the loaded orders are not the ones the stock import counted
            count = self._with_manual(count_art_copies(self.counted_orders()))
        self._applied = dict(self._manual)
        self._had_manual = bool(self._manual)
        self.service.replace_future(count, reset_marks=reset_marks)
        self.refresh()
        return True

    def _pending_count(self) -> ArtCopyCount:
        """The futuro now stored, minus the hand-added copies already inside it."""
        repo = self.service.repository
        files = {f.id: f for f in repo.files()}
        arts: dict[str, CountedArt] = {}
        for art_id, (quantity, _) in repo.future().items():
            file = files.get(art_id)
            if file is not None and quantity > 0:
                arts[str(Path(file.absolute_path).resolve()).casefold()] = CountedArt(
                    file.name, file.absolute_path, quantity)
        for path, copies in self._applied.items():
            key = str(Path(path).resolve()).casefold()
            if key in arts:
                left = arts[key].copies - copies
                if left > 0:
                    arts[key] = CountedArt(arts[key].file_name, arts[key].file_reference, left)
                else:
                    del arts[key]
        unlinked = int(self.service.stock_repository.get_state("art_unlinked", "0") or 0)
        return ArtCopyCount(arts, unlinked, 0)

    def _with_manual(self, count: ArtCopyCount) -> ArtCopyCount:
        """Adds the copies of the arts the user put on the roll by hand."""
        if not self._manual:
            return count
        arts = dict(count.arts)
        for path, copies in self._manual.items():
            key = str(Path(path).resolve()).casefold()
            current = arts.get(key)
            arts[key] = CountedArt(
                current.file_name if current else Path(path).name,
                current.file_reference if current else path,
                (current.copies if current else 0) + copies)
        return ArtCopyCount(arts, count.unlinked_items, count.item_count)

    def set_manual_copies(self, copies) -> None:
        """Arts added by hand on the roll also leave the stock: they join the futuro."""
        copies = {path: int(amount) for path, amount in dict(copies).items() if int(amount) > 0}
        if copies == self._manual:
            return
        self._manual = copies
        self.schedule_recalc()

    def clear_manual(self) -> None:
        """Finalize/cancel already settled the futuro, hand-added copies included."""
        self._manual = {}
        self._applied = {}
        self._had_manual = False
        self.manual_consumed.emit()

    def schedule_recalc(self) -> None:
        """Called on every change of the orders/links: coalesces bursts into one recalculation."""
        if self._recalc_scheduled:
            return
        self._recalc_scheduled = True
        QTimer.singleShot(0, self._run_scheduled_recalc)

    def _run_scheduled_recalc(self) -> None:
        self._recalc_scheduled = False
        self.recalculate()

    # ---- move stock to another file -------------------------------------------------------------------
    def move_stock(self) -> None:
        sources = self.service.sources_with_stock()
        if not sources:
            self.prompts.info("Mover estoque", "Nenhuma arte tem estoque para mover.")
            return
        choice = self.prompts.choose_art_move(sources, self.service.candidates_to_receive)
        if choice is None:
            return
        from_id, to_id = choice
        moved, ok = self._try(self.service.move_stock, from_id, to_id)
        self.refresh()
        if ok:
            self.prompts.info("Mover estoque", f"{moved} unidade(s) movida(s).")

    def suggest_matches(self) -> None:
        """Proposes pairs by file name and moves ONLY what the user confirms."""
        suggestions = self.service.suggest_matches()
        if not suggestions:
            self.prompts.info("Sugerir correspondências",
                              "Nenhum arquivo da pasta tem o mesmo nome de um arquivo que sumiu.")
            return
        chosen = self.prompts.confirm_art_matches(suggestions)
        if not chosen:
            return
        moved = 0
        for match in chosen:
            amount, ok = self._try(self.service.move_stock, match.from_id, match.to_id)
            moved += amount or 0
        self.refresh()
        self.prompts.info("Sugerir correspondências",
                          f"{len(chosen)} arquivo(s) atualizado(s), {moved} unidade(s) movida(s).")

    # ---- shopping list ------------------------------------------------------------------------------
    def missing_text(self) -> str:
        rows = [r for r in self.service.snapshot().separation if r.shortage > 0]
        if not rows:
            return ""
        lines = ["Faltam (estampas):"] + [f"{r.name}: {r.shortage}" for r in rows]
        lines.append(f"Total: {sum(r.shortage for r in rows)}")
        return chr(10).join(lines)

    def copy_missing(self) -> None:
        text = self.missing_text()
        if not text:
            self.prompts.info("Lista de estampas", "Não falta nenhuma estampa.")
            return
        QGuiApplication.clipboard().setText(text)
        self.prompts.info("Lista de estampas", "Lista copiada. É só colar onde precisar.")

    # ---- identical files (warning only) ------------------------------------------------------------------
    def start_duplicate_scan(self) -> None:
        if self._scanner is None:
            return
        repo = self.service.repository
        try:
            self._scanner.start(self.service.present_files(), repo.hashes(), repo.save_hashes)
        except Exception:           # only a warning feature: never an error on screen
            return

    def _identical_found(self, groups) -> None:
        self.identical_groups = list(groups)
        if self.tab is not None:
            self.tab.set_identical(self.identical_groups)
