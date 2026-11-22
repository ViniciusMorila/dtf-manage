"""Decides everything in the stock tabs. The tab only shows data and emits signals; the
dialogs only ask questions (through `prompts`); the rules live in StockService."""
import hashlib
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from dtf_manager.models.stock import ImportDecision, ImportNotice, NoticeChoice
from dtf_manager.services.stock_service import StockError, StockService
from dtf_manager.utils.stock_format import short_date


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class StockController(QObject):
    changed = Signal(bool)          # True when there is a futuro to finalize

    def __init__(self, service: StockService, prompts, tab=None, mounted_lookup=None,
                 parent=None):
        super().__init__(parent)
        self.service = service
        self.prompts = prompts
        self.tab = tab
        self._mounted_lookup = mounted_lookup or (lambda numbers: set())
        self._busy = False
        self.arts = None                 # ArtStockController, set by the window when it exists
        if tab is not None:
            tab.new_color_requested.connect(self.new_color)
            tab.new_size_requested.connect(self.new_size)
            tab.delete_color_requested.connect(self.delete_color)
            tab.bulk_requested.connect(self.bulk_add)
            tab.history_requested.connect(self.show_history)
            tab.stock_edit_requested.connect(self.edit_stock)
            tab.separated_changed.connect(self.service.set_separated)
        self.refresh()

    # ---- view -----------------------------------------------------------------------
    @property
    def art_service(self):
        return self.arts.service if self.arts is not None else None

    @property
    def has_future(self) -> bool:
        """A futuro to finalize: shirts or arts."""
        return self.service.snapshot().has_future or (
            self.arts is not None and self.arts.has_future)

    def refresh(self) -> None:
        snapshot = self.service.snapshot()
        if self.tab is not None:
            self.tab.render(snapshot)
        if self.arts is not None:
            self.arts.refresh()
        self.changed.emit(snapshot.has_future or (
            self.arts is not None and self.arts.has_future))

    def _try(self, action, *args):
        """Runs a service call; the message of a StockError is shown to the user."""
        try:
            return action(*args), True
        except StockError as error:
            self.prompts.warn("Estoque", str(error))
            return None, False

    # ---- catalog --------------------------------------------------------------------
    def new_color(self) -> None:
        name = self.prompts.ask_name("Nova cor", "Nome da cor:")
        if name is None:
            return
        _, ok = self._try(self.service.add_color, name)
        if ok:
            self.refresh()

    def new_size(self) -> None:
        name = self.prompts.ask_name("Novo tamanho", "Nome do tamanho:")
        if name is None:
            return
        _, ok = self._try(self.service.add_size, name)
        if ok:
            self.refresh()

    def delete_color(self, color_id: int = -1) -> bool:
        """Removes a color. color_id -1 = ask which one. Always asks for confirmation and says
        what will be discarded."""
        snapshot = self.service.snapshot()
        if color_id < 0:
            color_id = self.prompts.choose_color(snapshot.colors)
            if color_id is None:
                return False
        preview, ok = self._try(self.service.preview_delete_color, color_id)
        if not ok:
            self.refresh()
            return False
        name, stock, future = preview
        if not self.prompts.confirm_delete_color(name, stock, future):
            return False
        _, ok = self._try(self.service.delete_color, color_id)
        self.refresh()
        return ok

    # ---- stock ------------------------------------------------------------------------
    def edit_stock(self, color_id: int, size_id: int, text: str) -> None:
        _, ok = self._try(self.service.set_stock, color_id, size_id, text)
        # re-render after the table finished handling its own edit signal
        QTimer.singleShot(0, self.refresh)

    def bulk_add(self) -> None:
        snapshot = self.service.snapshot()
        request = self.prompts.bulk(snapshot.colors, snapshot.sizes, self.service.preview_bulk)
        if request is None:
            return
        quantity, color_id, size_ids = request
        count, ok = self._try(self.service.bulk_add, quantity, color_id, size_ids)
        if ok:
            self.refresh()
            self.prompts.info("Estoque em massa", f"Estoque atualizado em {count} combinação(ões).")

    def show_history(self) -> None:
        self.prompts.show_history(self.service.movements(), self.service.imports())

    # ---- import -----------------------------------------------------------------------
    def review_import(self, path: Path, orders) -> ImportDecision | None:
        """Runs BEFORE the spreadsheet is processed. None = the user cancelled the import."""
        numbers = [o.platform_order_number for o in orders]
        file_hash = file_sha256(Path(path))
        duplicate = self.service.check_duplicate(file_hash, numbers)
        finalized = self.service.finalized_info(numbers)
        mounted = self._mounted_lookup(numbers)
        loaded = list(orders)
        include = False
        if duplicate is not None or finalized or mounted:
            latest = max(finalized.values()) if finalized else ""
            notice = ImportNotice(duplicate, len(finalized),
                                  short_date(latest) if latest else "", len(mounted))
            choice: NoticeChoice = self.prompts.import_notice(notice)
            if choice.action == "cancel":
                return None
            include = choice.include_finalized
            if choice.action == "only_new" and duplicate is not None:
                fresh = set(duplicate.new_orders)
                loaded = [o for o in orders if o.platform_order_number in fresh]
        return ImportDecision(loaded, Path(path).name, file_hash, include)

    def apply_import(self, decision: ImportDecision) -> bool:
        """Computes the futuro of the loaded orders. False = cancelled (futuro untouched)."""
        orders = decision.orders
        numbers = [o.platform_order_number for o in orders]
        excluded = [] if decision.include_finalized else list(
            self.service.finalized_info(numbers))
        return self._compute(orders, excluded, decision.file_name, decision.file_hash)

    def sync_loaded_orders(self, orders) -> None:
        """Orders came back without a new import (operation restored): recompute only when the
        stored futuro was made for a different set of orders. Finalized orders stay out."""
        numbers = [o.platform_order_number for o in orders]
        if not self.service.needs_sync(numbers):
            return
        finalized = self.service.finalized_info(numbers)
        if len(finalized) == len(set(numbers)):          # everything already deducted
            self.service.remember_signature(numbers)
            return
        self._compute(orders, list(finalized), "Operação restaurada", "")

    def _compute(self, orders, excluded, file_name: str, file_hash: str) -> bool:
        prep = self.service.prepare_import(orders, excluded)
        decisions = {}
        if prep.lines:
            snapshot = self.service.snapshot()
            decisions = self.prompts.validate(prep.lines, snapshot.colors, snapshot.sizes)
            if decisions is None:
                return False
        result = self.service.commit_import(prep, decisions, file_name, file_hash)
        if self.arts is not None:
            self.arts.recalculate(reset_marks=True)      # a new import replaces the arts futuro
        self.refresh()
        notes = []
        if result.pending:
            notes.append(f"{result.pending} camiseta(s) pendentes ficaram fora da conta.")
        if result.excluded_orders:
            notes.append(f"{result.excluded_orders} pedido(s) já finalizados ficaram fora do futuro.")
        if result.repeated_lines:
            notes.append(f"{result.repeated_lines} linha(s) idênticas repetidas foram somadas.")
        if notes:
            self.prompts.info("Estoque: importação", "\n".join(notes))
        return True

    def cancel_import(self) -> bool:
        """The operation was cancelled: forget its futuro and its import record."""
        done = self.service.cancel_current_import(self.art_service)
        if self.arts is not None:
            self.arts.clear_manual()
        self.refresh()
        return done

    # ---- finalize ----------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self._busy

    def finalize(self) -> bool:
        """"Finalizar pedido". Ignores a second call while one is running."""
        if self._busy:
            return False
        self._busy = True
        self.changed.emit(False)                 # disables the button during the operation
        done = False
        try:
            summary = self.service.finalize_summary(self.art_service)
            if summary is None:
                return False
            if not self.prompts.confirm_finalize(summary):
                return False
            done = self.service.finalize(self.art_service) is not None
            if done and self.arts is not None:
                self.arts.clear_manual()
            return done
        finally:
            self._busy = False
            self.refresh()
