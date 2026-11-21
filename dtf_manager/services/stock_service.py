"""Stock rules: balance, bulk add, spreadsheet -> "futuro", finalizing and duplicate protection.

No Qt here. The controller decides what to ask the user and calls these methods; every
method that changes data does so in a single transaction."""
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from dtf_manager.models.stock import (
    MOVEMENT_BULK, MOVEMENT_FINALIZE, MOVEMENT_IMPORT, MOVEMENT_MANUAL,
    DuplicateInfo, FinalizeRow, FinalizeSummary, ImportResult, LineDecision, PendingRow,
    Preparation, SeparationRow, StockColor, StockSize, StockSnapshot, ValidationLine,
)
from dtf_manager.services.stock_parser import (
    COLOR_AMBIGUOUS, COLOR_FOUND, parse_variation, sku_color_candidates,
)
from dtf_manager.services.stock_repository import StockRepository, now_text
from dtf_manager.utils.stock_names import normalize_name

DUPLICATE_OVERLAP_LIMIT = 0.8      # more than 80% of the orders already imported


class StockError(ValueError):
    """Message meant to be shown to the user as is."""


@dataclass(slots=True)
class _Unresolved:
    item: object
    color_id: int | None
    color_issue: str | None            # None | "missing" | "unknown" | "ambiguous"
    color_hint: str
    size_ids: list
    size_issue: str | None             # None | "missing" | "unknown"
    sku_norm: str
    group_key: str


def signature_of(order_numbers) -> str:
    return hashlib.sha256("\n".join(sorted(set(order_numbers))).encode("utf-8")).hexdigest()


class StockService:
    def __init__(self, repository: StockRepository):
        self.repository = repository

    # ---- catalog -------------------------------------------------------------------
    def _maps(self, db=None):
        repo = self.repository
        colors, sizes = repo.colors(db), repo.sizes(db)
        color_map = {normalize_name(c.name): c.id for c in colors}
        size_map = {normalize_name(s.name): s.id for s in sizes}
        for kind, alias, target in repo.aliases(db):
            (color_map if kind == "color" else size_map).setdefault(alias, target)
        return colors, sizes, color_map, size_map

    def add_color(self, name: str, db=None) -> StockColor:
        name = " ".join((name or "").split())
        if not name:
            raise StockError("Informe o nome da cor.")
        with self.repository.tx(db) as c:
            _, _, color_map, _ = self._maps(c)
            if normalize_name(name) in color_map:
                raise StockError(f"A cor \"{name}\" já existe (ou já é uma equivalência).")
            return self.repository.add_color(name, db=c)

    def add_size(self, name: str, db=None) -> StockSize:
        name = " ".join((name or "").split())
        if not name:
            raise StockError("Informe o nome do tamanho.")
        with self.repository.tx(db) as c:
            _, _, _, size_map = self._maps(c)
            if normalize_name(name) in size_map:
                raise StockError(f"O tamanho \"{name}\" já existe (ou já é uma equivalência).")
            return self.repository.add_size(name, db=c)

    def _get_or_add_color(self, value, db) -> int:
        if isinstance(value, int):
            return value
        _, _, color_map, _ = self._maps(db)
        found = color_map.get(normalize_name(value))
        return found if found is not None else self.repository.add_color(
            " ".join(value.split()), db=db).id

    def _get_or_add_size(self, value, db) -> int:
        if isinstance(value, int):
            return value
        _, _, _, size_map = self._maps(db)
        found = size_map.get(normalize_name(value))
        return found if found is not None else self.repository.add_size(
            " ".join(value.split()), db=db).id

    def preview_delete_color(self, color_id: int):
        """(name, units in stock, units in the futuro) of a color that is about to be removed."""
        repo = self.repository
        with repo.tx() as db:
            color = next((c for c in repo.colors(db) if c.id == color_id), None)
            if color is None:
                raise StockError("Essa cor não existe mais.")
            stock = sum(q for (cid, _), q in repo.levels(db).items() if cid == color_id)
            future = sum(q for (cid, _), (q, _) in repo.future(db).items() if cid == color_id)
        return color.name, stock, future

    def delete_color(self, color_id: int) -> tuple[str, int, int]:
        """Removes a color with its stock, futuro, SKU mappings and equivalences (one
        transaction). What it held is logged as manual adjustments to 0 so the history keeps it.
        Past movements keep the color name as text."""
        repo = self.repository
        with repo.tx() as db:
            name, stock, future = self.preview_delete_color(color_id)
            sizes = {s.id: s.name for s in repo.sizes(db)}
            for (cid, sid), quantity in sorted(repo.levels(db).items()):
                if cid == color_id and quantity > 0:
                    repo.add_movement(MOVEMENT_MANUAL, "estoque", name, sizes[sid], quantity, 0,
                                      note="Cor excluída", db=db)
            for (cid, sid), (quantity, _) in sorted(repo.future(db).items()):
                if cid == color_id:
                    repo.add_movement(MOVEMENT_IMPORT, "futuro", name, sizes[sid], quantity, 0,
                                      note="Cor excluída", db=db)
            repo.delete_color(color_id, db=db)
        return name, stock, future

    def replace_aliases(self, rows) -> None:
        """rows: (kind, text, target_id). Text is normalized; empty or duplicate rows ignored."""
        clean = {}
        with self.repository.tx() as db:
            colors = {c.id for c in self.repository.colors(db)}
            sizes = {s.id for s in self.repository.sizes(db)}
            for kind, text, target in rows:
                alias = normalize_name(text)
                valid = colors if kind == "color" else sizes
                if alias and target in valid:
                    clean[(kind, alias)] = target
            self.repository.replace_aliases(
                [(kind, alias, target) for (kind, alias), target in clean.items()], db=db)

    # ---- snapshot --------------------------------------------------------------------
    def snapshot(self) -> StockSnapshot:
        repo = self.repository
        with repo.tx() as db:
            colors, sizes = repo.colors(db), repo.sizes(db)
            stock, future = repo.levels(db), repo.future(db)
            pending = tuple(repo.pending(db))
            note = repo.get_state("import_note", db=db)
        names_c = {c.id: c.name for c in colors}
        names_s = {s.id: s.name for s in sizes}
        order = {c.id: i for i, c in enumerate(colors)}
        order_s = {s.id: i for i, s in enumerate(sizes)}
        rows = []
        for (cid, sid), (quantity, separated) in sorted(
                future.items(), key=lambda kv: (order[kv[0][0]], order_s[kv[0][1]])):
            available = stock.get((cid, sid), 0)
            rows.append(SeparationRow(cid, sid, names_c[cid], names_s[sid], quantity, available,
                                      max(0, quantity - available), separated))
        return StockSnapshot(tuple(colors), tuple(sizes), dict(stock),
                             {k: v[0] for k, v in future.items()}, tuple(rows), pending, note)

    # ---- manual changes -----------------------------------------------------------------
    @staticmethod
    def parse_quantity(value) -> int:
        text = str(value).strip()
        if not text.isdigit():
            raise StockError("Informe um número inteiro igual ou maior que zero.")
        return int(text)

    def set_stock(self, color_id: int, size_id: int, value) -> bool:
        """Manual edit of one cell. Returns False when nothing changed."""
        quantity = self.parse_quantity(value)
        repo = self.repository
        with repo.tx() as db:
            names = self._names(db)
            before = repo.levels(db).get((color_id, size_id), 0)
            if before == quantity:
                return False
            repo.set_level(color_id, size_id, quantity, db=db)
            repo.add_movement(MOVEMENT_MANUAL, "estoque", names[0][color_id],
                              names[1][size_id], before, quantity, db=db)
        return True

    def _names(self, db):
        return ({c.id: c.name for c in self.repository.colors(db)},
                {s.id: s.name for s in self.repository.sizes(db)})

    def preview_bulk(self, quantity: int, color_id, size_ids):
        """[(color, size, before, after)] for what a bulk add would change."""
        if quantity <= 0:
            raise StockError("A quantidade a adicionar deve ser maior que zero.")
        repo = self.repository
        with repo.tx() as db:
            colors, sizes = repo.colors(db), repo.sizes(db)
            levels = repo.levels(db)
        picked_sizes = [s for s in sizes if size_ids is None or s.id in size_ids]
        picked_colors = [c for c in colors if color_id is None or c.id == color_id]
        return [(c, s, levels.get((c.id, s.id), 0), levels.get((c.id, s.id), 0) + quantity)
                for c in picked_colors for s in picked_sizes]

    def bulk_add(self, quantity: int, color_id=None, size_ids=None) -> int:
        changes = self.preview_bulk(quantity, color_id, size_ids)
        if not changes:
            raise StockError("Selecione ao menos uma cor e um tamanho.")
        with self.repository.tx() as db:
            for color, size, before, after in changes:
                self.repository.set_level(color.id, size.id, after, db=db)
                self.repository.add_movement(MOVEMENT_BULK, "estoque", color.name, size.name,
                                             before, after, db=db)
        return len(changes)

    def set_separated(self, color_id: int, size_id: int, value: bool) -> None:
        self.repository.set_separated(color_id, size_id, value)

    # ---- spreadsheet -> futuro -------------------------------------------------------------
    def duplicate_lines(self, orders) -> int:
        """Extra lines that are identical to another one of the same order."""
        counts = Counter(
            (item.platform_order_number, item.listing_id, item.sku, item.variant_id,
             item.variation_normalized, item.product_quantity)
            for order in orders for item in order.items)
        return sum(n - 1 for n in counts.values() if n > 1)

    def _classify(self, item, color_map, size_map, sku_colors) -> _Unresolved:
        parsed = parse_variation(item.variation_raw, set(size_map))
        sku_norm = normalize_name(item.sku)
        group_key = sku_norm or f"{item.listing_id}|{item.variant_id or ''}"
        color_id, issue, hint = None, None, ""
        if parsed.color_state == COLOR_FOUND:
            hint = parsed.color
            color_id = color_map.get(parsed.color)
            issue = None if color_id is not None else "unknown"
        else:
            hint = parsed.color if parsed.color_state == COLOR_AMBIGUOUS else ""
            issue = "ambiguous" if parsed.color_state == COLOR_AMBIGUOUS else "missing"
            if sku_norm and sku_norm in sku_colors:
                color_id, issue = sku_colors[sku_norm], None
            elif parsed.color_state != COLOR_AMBIGUOUS:
                candidates = sku_color_candidates(item.sku, color_map)
                if len(candidates) == 1:
                    color_id, issue = next(iter(candidates)), None
                elif len(candidates) > 1:
                    issue = "ambiguous"
        size_ids, size_issue = [], None
        if not parsed.sizes_ok:
            size_issue = "missing"
        else:
            for token in parsed.sizes:
                if token in size_map:
                    size_ids.append(size_map[token])
                else:
                    size_issue = "unknown"
        return _Unresolved(item, color_id, issue, hint, size_ids, size_issue, sku_norm, group_key)

    def prepare_import(self, orders, excluded_numbers=()) -> Preparation:
        """Reads every counted item; resolved ones go to the totals, the rest to validation."""
        excluded = set(excluded_numbers)
        with self.repository.tx() as db:
            _, sizes, color_map, size_map = self._maps(db)
            sku_colors = self.repository.sku_colors(db)
        size_names = {s.id: s.name for s in sizes}
        totals: dict = defaultdict(int)
        unresolved: dict[str, list[_Unresolved]] = {}
        counted, left_out = [], []
        for order in orders:
            number = order.platform_order_number
            if number in excluded:
                left_out.append(number)
                continue
            counted.append(number)
            for item in order.items:
                entry = self._classify(item, color_map, size_map, sku_colors)
                if entry.color_issue is None and entry.size_issue is None:
                    for size_id in entry.size_ids:
                        totals[(entry.color_id, size_id)] += item.product_quantity
                    continue
                sub = (item.variation_normalized
                       if entry.size_issue or entry.color_issue in ("unknown", "ambiguous") else "")
                unresolved.setdefault(f"{entry.group_key}\x1f{sub}", []).append(entry)
        lines = [self._line(key, entries, size_names) for key, entries in unresolved.items()]
        all_numbers = [o.platform_order_number for o in orders]
        return Preparation(dict(totals), lines, unresolved, counted, left_out, all_numbers,
                           self.duplicate_lines(orders), signature_of(all_numbers))

    @staticmethod
    def _line(key: str, entries, size_names) -> ValidationLine:
        first = entries[0]
        shirts = sum(e.item.product_quantity * max(1, len(e.size_ids)) for e in entries)
        variations = list(dict.fromkeys(
            e.item.variation_raw.strip() for e in entries if e.item.variation_raw.strip()))
        sizes = list(dict.fromkeys(
            " - ".join(size_names[s] for s in e.size_ids) for e in entries if e.size_ids))
        needs_color = any(e.color_issue for e in entries)
        needs_size = any(e.size_issue for e in entries)
        reason = {"missing": "sem cor", "unknown": "cor não reconhecida",
                  "ambiguous": "cor ambígua"}.get(first.color_issue or "", "")
        if needs_size:
            reason = (reason + " e " if reason else "") + "sem tamanho reconhecido"
        return ValidationLine(
            key=key, product_name=first.item.product_name, sku=first.item.sku,
            variation=" | ".join(variations), sizes_text=" | ".join(sizes), shirts=shirts,
            needs_color=needs_color, needs_size=needs_size,
            color_hint=first.color_hint, reason=reason,
            image_url=next((e.item.product_image_url for e in entries
                            if e.item.product_image_url), "") or "")

    def commit_import(self, prep: Preparation, decisions: dict, file_name: str,
                      file_hash: str) -> ImportResult:
        """Applies the user's choices and REPLACES the futuro (never accumulates).

        `decisions`: line key -> LineDecision; missing/incomplete lines stay pending."""
        repo = self.repository
        totals = defaultdict(int, prep.totals)
        pending = []
        with repo.tx() as db:
            for key, entries in prep.unresolved.items():
                decision: LineDecision | None = decisions.get(key)
                for entry in entries:
                    colors_ok = self._apply_decision(entry, decision, db, totals)
                    if colors_ok is not None:
                        pending.append(colors_ok)
            old_future = repo.future(db)
            names = self._names(db)
            repo.replace_future(totals, db=db)
            repo.replace_pending(pending, db=db)
            for cell in sorted(set(old_future) | {k for k, v in totals.items() if v > 0}):
                before = old_future.get(cell, (0, False))[0]
                after = totals.get(cell, 0)
                if before != after:
                    repo.add_movement(MOVEMENT_IMPORT, "futuro", names[0][cell[0]],
                                      names[1][cell[1]], before, after,
                                      note=f"Planilha {file_name}", db=db)
            import_id = repo.add_import(file_name, file_hash, prep.all_orders, db=db)
            repo.set_state("current_import_id", str(import_id), db=db)
            repo.set_state("counted_orders", json.dumps(prep.counted_orders), db=db)
            repo.set_state("signature", prep.signature, db=db)
            note = f"Importado de {file_name}: {len(prep.all_orders)} pedidos"
            if prep.excluded_orders:
                note += f" ({len(prep.excluded_orders)} já finalizados, fora do futuro)"
            repo.set_state("import_note", note, db=db)
        return ImportResult(sum(totals.values()), sum(p.quantity for p in pending),
                            prep.repeated_lines, len(prep.excluded_orders))

    def _apply_decision(self, entry: _Unresolved, decision, db, totals):
        """Resolves one item with the user's choice; returns a PendingRow if still unresolved."""
        item = entry.item
        names = self._names(db)
        color_id, size_ids, sizes_given = entry.color_id, list(entry.size_ids), False
        if decision is not None:
            if entry.color_issue and decision.color not in (None, ""):
                color_id = self._get_or_add_color(decision.color, db)
                self._remember_color(entry, decision, color_id, db)
            if entry.size_issue and decision.sizes:
                size_ids = [self._get_or_add_size(s, db) for s in decision.sizes]
                sizes_given = True
        color_ok = color_id is not None
        size_ok = bool(size_ids) and (entry.size_issue is None or sizes_given)
        if color_ok and size_ok:
            for size_id in size_ids:
                totals[(color_id, size_id)] += item.product_quantity
            return None
        reasons = []
        if not color_ok:
            reasons.append({"missing": "sem cor", "unknown": "cor não reconhecida",
                            "ambiguous": "cor ambígua"}.get(entry.color_issue or "", "sem cor"))
        if not size_ok:
            reasons.append("sem tamanho reconhecido")
        shirts = item.product_quantity * max(1, len(entry.size_ids))
        return PendingRow(item.product_name, item.sku, item.variation_raw.strip(),
                          " - ".join(names[1][s] for s in entry.size_ids), shirts,
                          " e ".join(reasons))

    def _remember_color(self, entry: _Unresolved, decision, color_id: int, db) -> None:
        repo = self.repository
        if not decision.remember:
            return
        if entry.color_issue == "unknown" and entry.color_hint:
            # the text is itself a color name ("preto"): safe to remember by text
            repo.set_alias("color", entry.color_hint, color_id, db=db)
        elif entry.sku_norm:
            # never by Variação text ("P - M" is the same for every color): only by SKU
            repo.set_sku_color(entry.sku_norm, color_id, db=db)

    # ---- duplicate protection ---------------------------------------------------------------
    def check_duplicate(self, file_hash: str, order_numbers) -> DuplicateInfo | None:
        numbers = set(order_numbers)
        imports = self.repository.imports()
        known = set()
        for record in imports:
            known.update(record.orders)
        same = [r for r in imports if file_hash and r.file_hash == file_hash]
        overlap = len(numbers & known) / len(numbers) if numbers else 0.0
        if not same and overlap <= DUPLICATE_OVERLAP_LIMIT:
            return None
        if same:
            previous = same[-1]
        else:
            previous = max(imports, key=lambda r: (len(numbers & set(r.orders)), r.id))
        new_orders = tuple(sorted(numbers - known))
        return DuplicateInfo(previous, bool(same), overlap, new_orders,
                             len(numbers) - len(new_orders))

    def finalized_info(self, order_numbers) -> dict:
        return self.repository.finalized_orders(order_numbers)

    def known_orders(self) -> set:
        known = set()
        for record in self.repository.imports():
            known.update(record.orders)
        return known

    def needs_sync(self, order_numbers) -> bool:
        return self.repository.get_state("signature") != signature_of(order_numbers)

    def remember_signature(self, order_numbers) -> None:
        self.repository.set_state("signature", signature_of(order_numbers))

    # ---- finalizing -----------------------------------------------------------------------------
    def finalize_summary(self) -> FinalizeSummary | None:
        snapshot = self.snapshot()
        if not snapshot.has_future:
            return None
        colors = {c.id: c.name for c in snapshot.colors}
        sizes = {s.id: s.name for s in snapshot.sizes}
        rows = []
        for (cid, sid), future in sorted(snapshot.future.items()):
            have = snapshot.stock.get((cid, sid), 0)
            rows.append(FinalizeRow(colors[cid], sizes[sid], future, have,
                                    max(0, have - future), max(0, future - have)))
        return FinalizeSummary(tuple(rows), sum(p.quantity for p in snapshot.pending))

    def finalize(self) -> FinalizeSummary | None:
        """Deducts the futuro from the stock (never below zero) and clears it. One transaction.

        Returns what was done, or None when there is no futuro (nothing to do)."""
        repo = self.repository
        with repo.tx() as db:
            future = repo.future(db)
            if not any(q > 0 for q, _ in future.values()):
                return None
            levels = repo.levels(db)
            names = self._names(db)
            pending = repo.pending(db)
            rows = []
            for (cid, sid), (quantity, _) in sorted(future.items()):
                before = levels.get((cid, sid), 0)
                after = max(0, before - quantity)
                shortage = max(0, quantity - before)
                rows.append(FinalizeRow(names[0][cid], names[1][sid], quantity, before,
                                        after, shortage))
                repo.set_level(cid, sid, after, db=db)
                note = f"Pedidos finalizados: {quantity} camiseta(s)"
                if shortage:
                    note += f"; faltaram {shortage} no estoque (ficou em 0)"
                repo.add_movement(MOVEMENT_FINALIZE, "estoque", names[0][cid], names[1][sid],
                                  before, after, note=note, db=db)
            at = now_text()
            counted = json.loads(repo.get_state("counted_orders", "[]", db=db))
            import_id = repo.get_state("current_import_id", db=db)
            if import_id:
                repo.mark_import_finalized(int(import_id), at, db=db)
            repo.add_finalized(counted, at, int(import_id) if import_id else None, db=db)
            repo.replace_future({}, db=db)
            repo.replace_pending([], db=db)
            repo.set_state("counted_orders", "[]", db=db)
            repo.set_state("import_note", "", db=db)
        return FinalizeSummary(tuple(rows), sum(p.quantity for p in pending))

    # ---- history -----------------------------------------------------------------------------------
    def movements(self, limit: int = 1000):
        return self.repository.movements(limit)

    def imports(self):
        return list(reversed(self.repository.imports()))
