from dataclasses import replace
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from dtf_manager.models.automatic_link import ArtCandidate, AutomaticLinkOutcome, AutoLinkResult
from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.utils.art_matching import (
    GENERIC_PRODUCT_TOKENS,
    PAIR_SUFFIXES,
    STRUCTURAL_SUFFIXES,
    contains_token_sequence,
    matching_tokens,
    normalize_for_matching,
)
from dtf_manager.services.link_memory_service import ArtLinkMemoryService


def _result(
    item: ImportedOrderItem,
    status: Literal["linked", "not_found", "ambiguous", "preserved"],
    confidence: Literal["high", "medium", "low"],
    candidates: tuple[ArtCandidate, ...],
    reason: str,
) -> AutoLinkResult:
    return AutoLinkResult(
        item_id=item.id,
        status=status,
        confidence=confidence,
        candidate_count=len(candidates),
        reason=reason,
        linked_candidate_ids=tuple(candidate.id for candidate in candidates) if status == "linked" else (),
        link_origin="automatic" if status == "linked" else None,
    )


def _related_structural_group(
    candidates: tuple[ArtCandidate, ...], identifier_tokens: tuple[str, ...], item: ImportedOrderItem
) -> bool:
    if len(candidates) < 2:
        return False
    suffixes: list[str] = []
    for candidate in candidates:
        if not contains_token_sequence(candidate.tokens, identifier_tokens):
            return False
        remaining = list(candidate.tokens)
        for index in range(len(remaining) - len(identifier_tokens) + 1):
            if tuple(remaining[index:index + len(identifier_tokens)]) == identifier_tokens:
                del remaining[index:index + len(identifier_tokens)]
                break
        if len(remaining) != 1:
            return False
        suffixes.append(remaining[0])
    unique_suffixes = set(suffixes)
    if len(unique_suffixes) != len(suffixes):
        return False
    if unique_suffixes <= STRUCTURAL_SUFFIXES:
        return True
    item_tokens = set(matching_tokens(f"{item.sku} {item.product_name} {item.variation_raw}"))
    return unique_suffixes == PAIR_SUFFIXES and PAIR_SUFFIXES <= item_tokens


def _strong_identifier_match(
    item: ImportedOrderItem,
    candidates: tuple[ArtCandidate, ...],
    identifier: str | None,
    label: str,
) -> tuple[tuple[ArtCandidate, ...], AutoLinkResult | None]:
    normalized = normalize_for_matching(identifier or "")
    tokens = matching_tokens(identifier or "")
    if not normalized or not tokens:
        return (), None
    exact = tuple(candidate for candidate in candidates if candidate.normalized_name == normalized)
    if len(exact) == 1:
        return exact, _result(item, "linked", "high", exact, f"Exact {label} match")
    if len(exact) > 1:
        return exact, _result(item, "ambiguous", "high", exact, f"Duplicate exact {label} matches")
    token_matches = tuple(candidate for candidate in candidates if contains_token_sequence(candidate.tokens, tokens))
    if len(token_matches) == 1:
        return token_matches, _result(item, "linked", "high", token_matches, f"Complete {label} token match")
    if _related_structural_group(token_matches, tokens, item):
        return token_matches, _result(item, "linked", "high", token_matches, f"Related structural files by {label}")
    if token_matches:
        return token_matches, _result(item, "ambiguous", "high", token_matches, f"Multiple {label} candidates")
    return (), None


def find_automatic_art_match(
    item: ImportedOrderItem, candidates: tuple[ArtCandidate, ...]
) -> tuple[tuple[ArtCandidate, ...], AutoLinkResult]:
    if item.link_status == "linked" and item.linked_arts:
        return (), _result(item, "preserved", "high", (), "Existing link preserved")

    sku_candidates, sku_result = _strong_identifier_match(item, candidates, item.sku, "SKU")
    if sku_result is not None and sku_result.status == "linked":
        return sku_candidates, sku_result

    variant_candidates, variant_result = _strong_identifier_match(item, candidates, item.variant_id, "variant ID")
    if variant_result is not None and variant_result.status == "linked":
        return variant_candidates, variant_result
    if sku_result is not None:
        return (), sku_result
    if variant_result is not None:
        return (), variant_result

    listing_tokens = matching_tokens(item.listing_id)
    name_tokens = set(matching_tokens(item.product_name)) - GENERIC_PRODUCT_TOKENS
    variation_tokens = set(matching_tokens(item.variation_raw)) - GENERIC_PRODUCT_TOKENS
    review_candidates = tuple(candidate for candidate in candidates if (
        contains_token_sequence(candidate.tokens, listing_tokens)
        or (len(name_tokens) >= 2 and name_tokens <= set(candidate.tokens))
        or (name_tokens and variation_tokens and name_tokens | variation_tokens <= set(candidate.tokens))
    ))
    if review_candidates:
        return (), _result(
            item, "ambiguous", "medium", review_candidates,
            "Only listing ID or descriptive name signals matched; manual review required",
        )
    return (), _result(item, "not_found", "low", (), "No reliable candidate found")


def _linked_art(candidate: ArtCandidate) -> LinkedArt:
    return LinkedArt(
        id=str(uuid5(NAMESPACE_URL, f"linked-art:{candidate.file_reference}")),
        file_name=candidate.file_name,
        file_reference=candidate.file_reference,
        copies_per_product=1,
        link_method="automatic",
    )


def auto_link_orders(
    orders: tuple[ImportedOrder, ...] | list[ImportedOrder],
    candidates: tuple[ArtCandidate, ...],
    memory_service: ArtLinkMemoryService | None = None,
    arts_root: str | None = None,
) -> AutomaticLinkOutcome:
    results: list[AutoLinkResult] = []
    updated_orders: list[ImportedOrder] = []
    for order in orders:
        updated_items: list[ImportedOrderItem] = []
        for item in order.items:
            if item.link_status == "linked" and item.linked_arts:
                _, result = find_automatic_art_match(item, candidates)
                results.append(result)
                updated_items.append(item)
                continue
            memory_diagnostic = None
            if memory_service is not None:
                memory_match = memory_service.find_and_resolve(item, arts_root)
                if memory_match.status == "matched":
                    results.append(AutoLinkResult(
                        item_id=item.id,
                        status="linked",
                        confidence="high",
                        candidate_count=0,
                        reason="Exact confirmed link memory match",
                        link_origin="memory",
                    ))
                    updated_items.append(replace(
                        item, linked_arts=list(memory_match.arts), link_status="linked"
                    ))
                    continue
                if memory_match.status == "memory_file_missing":
                    memory_diagnostic = "memory_file_missing"
            matches, result = find_automatic_art_match(item, candidates)
            if memory_diagnostic:
                result = replace(result, memory_diagnostic=memory_diagnostic)
            results.append(result)
            if result.status == "linked":
                arts = [_linked_art(candidate) for candidate in matches]
                updated_items.append(replace(item, linked_arts=arts, link_status="linked"))
            else:
                updated_items.append(item)
        updated_orders.append(replace(order, items=updated_items))
    return AutomaticLinkOutcome(updated_orders, tuple(results))
