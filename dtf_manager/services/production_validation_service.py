from collections import defaultdict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from dtf_manager.models.imported_order import ImportedOrder
from dtf_manager.models.print_plan import DTFOrderPlan
from dtf_manager.models.production_validation import ProductionIssue, ProductionValidationResult


HIGH_COPY_WARNING_THRESHOLD = 20
HIGH_COPIES_PER_PRODUCT_THRESHOLD = 8


def _positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _issue(severity: str, code: str, message: str, *, item=None, order=None, art=None,
           action: str | None = None) -> ProductionIssue:
    identity = ":".join((code, getattr(item, "id", ""), getattr(art, "id", "")))
    return ProductionIssue(
        id=str(uuid5(NAMESPACE_URL, f"production-issue:{identity}")),
        severity=severity, code=code, message=message,
        item_id=getattr(item, "id", None), order_id=getattr(order, "id", None),
        art_id=getattr(art, "id", None), file_reference=getattr(art, "file_reference", None),
        product_name=getattr(item, "product_name", None),
        art_name=getattr(art, "file_name", None), action=action,
    )


def validate_production_plan(
    imported_orders: tuple[ImportedOrder, ...] | list[ImportedOrder],
    print_plan: DTFOrderPlan | None,
    *, validate_files: bool = True,
    high_copy_threshold: int = HIGH_COPY_WARNING_THRESHOLD,
    high_copies_per_product_threshold: int = HIGH_COPIES_PER_PRODUCT_THRESHOLD,
) -> ProductionValidationResult:
    """Audit orders and the exact plan that will be applied to the DTF roll."""
    errors: list[ProductionIssue] = []
    warnings: list[ProductionIssue] = []
    info: list[ProductionIssue] = []
    filenames: dict[str, set[str]] = defaultdict(set)
    copies_by_file: dict[str, set[int]] = defaultdict(set)

    for order in imported_orders:
        for item in order.items:
            if item.link_status == "unlinked":
                errors.append(_issue("error", "UNLINKED_ITEM", "Existe um produto sem arte vinculada.", item=item, order=order, action="CORRIGIR VÍNCULO"))
            elif not item.linked_arts:
                errors.append(_issue("error", "EMPTY_LINKED_ARTS", "Um produto está marcado como vinculado, mas não possui nenhuma arte.", item=item, order=order, action="CORRIGIR VÍNCULO"))
            if not _positive_integer(item.product_quantity):
                errors.append(_issue("error", "INVALID_PRODUCT_QUANTITY", "A quantidade deste produto é inválida.", item=item, order=order, action="CORRIGIR VÍNCULO"))
            seen: set[str] = set()
            for art in item.linked_arts:
                reference = (art.file_reference or "").strip()
                path_key = str(Path(reference).resolve()).casefold() if reference else ""
                reference_key = f"{path_key}|{art.color_mode}" if path_key else ""
                if not _positive_integer(art.copies_per_product):
                    errors.append(_issue("error", "INVALID_COPIES_PER_PRODUCT", "A quantidade desta arte por produto é inválida.", item=item, order=order, art=art, action="CORRIGIR VÍNCULO"))
                final_copies = item.product_quantity * art.copies_per_product if _positive_integer(item.product_quantity) and _positive_integer(art.copies_per_product) else None
                if not _positive_integer(final_copies):
                    errors.append(_issue("error", "INVALID_FINAL_COPIES", "Não foi possível calcular uma quantidade final válida para esta arte.", item=item, order=order, art=art, action="CORRIGIR VÍNCULO"))
                if not reference:
                    errors.append(_issue("error", "MISSING_FILE_REFERENCE", "Uma arte vinculada não possui referência de arquivo.", item=item, order=order, art=art, action="CORRIGIR VÍNCULO"))
                elif validate_files and not Path(reference).is_file():
                    errors.append(_issue("error", "FILE_NOT_FOUND", "Uma arte vinculada não foi encontrada no computador.", item=item, order=order, art=art, action="CORRIGIR VÍNCULO"))
                if reference_key and reference_key in seen:
                    errors.append(_issue("error", "DUPLICATE_LINKED_ART", "A mesma arte foi adicionada mais de uma vez ao produto. Ajuste a quantidade usando 'Quantidade desta arte'.", item=item, order=order, art=art, action="CORRIGIR VÍNCULO"))
                seen.add(reference_key)
                if art.link_method == "automatic" and not item.automatic_links_confirmed:
                    warnings.append(_issue("warning", "UNCONFIRMED_AUTO_LINK", "Esta arte foi vinculada automaticamente e ainda não foi conferida.", item=item, order=order, art=art, action="CONFERIR"))
                if _positive_integer(art.copies_per_product) and art.copies_per_product >= high_copies_per_product_threshold:
                    warnings.append(_issue("warning", "HIGH_COPIES_PER_PRODUCT", f"Este produto utiliza {art.copies_per_product} cópias da mesma arte por unidade.", item=item, order=order, art=art, action="CONFERIR"))
                if reference_key:
                    filenames[Path(reference).name.casefold()].add(reference_key)
                    copies_by_file[reference_key].add(art.copies_per_product)

    if print_plan is None or not print_plan.arts or print_plan.total_print_copies <= 0:
        errors.append(_issue("error", "EMPTY_PRINT_PLAN", "O plano de impressão não possui artes válidas para produção."))
    else:
        calculated_total = sum(art.total_copies for art in print_plan.arts)
        if calculated_total != print_plan.total_print_copies:
            errors.append(_issue("error", "PRINT_PLAN_TOTAL_MISMATCH", "Foi encontrada uma inconsistência no cálculo das quantidades."))
        for art in print_plan.arts:
            if not _positive_integer(art.total_copies):
                errors.append(_issue("error", "INVALID_PLAN_COPIES", "O plano contém uma quantidade de estampas inválida."))
            elif art.total_copies >= high_copy_threshold:
                warnings.append(ProductionIssue(
                    id=str(uuid5(NAMESPACE_URL, f"production-issue:HIGH_TOTAL_COPIES:{art.id}")),
                    severity="warning", code="HIGH_TOTAL_COPIES",
                    message=f"Esta arte possui {art.total_copies} cópias. Confira a quantidade.",
                    art_id=art.id, file_reference=art.file_reference, art_name=art.file_name,
                ))
    for name, references in filenames.items():
        if len(references) > 1:
            warnings.append(ProductionIssue(
                id=str(uuid5(NAMESPACE_URL, f"production-issue:DUPLICATE_FILENAME:{name}")),
                severity="warning", code="DUPLICATE_FILENAME_DIFFERENT_FILE",
                message="Existem duas artes diferentes com o mesmo nome de arquivo.", art_name=name,
            ))
    for reference, quantities in copies_by_file.items():
        if len(quantities) > 1:
            info.append(ProductionIssue(
                id=str(uuid5(NAMESPACE_URL, f"production-issue:DIFFERENT_COPIES:{reference}")),
                severity="info", code="SAME_ART_DIFFERENT_COPIES",
                message="A mesma arte possui configurações de cópia diferentes entre produtos.",
                file_reference=reference,
            ))
    return ProductionValidationResult(tuple(errors), tuple(warnings), tuple(info))


def validate_production_files(imported_orders, print_plan) -> ProductionValidationResult:
    return validate_production_plan(imported_orders, print_plan, validate_files=True)
