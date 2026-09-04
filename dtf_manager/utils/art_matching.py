from pathlib import Path
import re
import unicodedata


STRUCTURAL_SUFFIXES = frozenset(("frente", "front", "costas", "verso", "back", "manga", "sleeve"))
PAIR_SUFFIXES = frozenset(("boy", "girl"))
GENERIC_PRODUCT_TOKENS = frozenset((
    "camiseta", "camisa", "blusa", "kit", "feminina", "masculina", "unissex",
    "algodao", "premium", "estampa", "preta", "branca", "bege", "marrom",
    "p", "m", "g", "gg",
))


def normalize_for_matching(value: str, remove_extension: bool = False) -> str:
    text = Path(value).stem if remove_extension else value
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", without_accents)).strip()


def matching_tokens(value: str, remove_extension: bool = False) -> tuple[str, ...]:
    normalized = normalize_for_matching(value, remove_extension)
    return tuple(normalized.split()) if normalized else ()


def contains_token_sequence(container: tuple[str, ...], sequence: tuple[str, ...]) -> bool:
    if not sequence or len(sequence) > len(container):
        return False
    width = len(sequence)
    return any(container[index:index + width] == sequence for index in range(len(container) - width + 1))

