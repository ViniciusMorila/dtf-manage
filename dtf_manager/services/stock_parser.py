"""Reads color and sizes from the UpSeller "Variação" (and, for the color, the SKU).

Pure text logic with no database: the caller says which names exist. Formats found in real
spreadsheets: "Preta,G", "Preto,M - G" (kit: one shirt per size), "G - GG,Preto",
"Kit Bege,P - G", "Marrom - Estampa Preta,P - G" (the color after "Estampa" belongs to the
print, never to the shirt), "P - M" and "GG" (no color).
"""
import re
from dataclasses import dataclass

from dtf_manager.utils.stock_names import normalize_name

# Result states for the color
COLOR_FOUND = "found"          # `color` is the raw text of the shirt color (not yet resolved)
COLOR_MISSING = "missing"      # nothing in the Variação / SKU
COLOR_AMBIGUOUS = "ambiguous"  # two possible colors and no way to tell which is the shirt's

_SIZE_PART = re.compile(r"^[a-z0-9]{1,4}( ?- ?[a-z0-9]{1,4})*$")
_PRINT_SUFFIX = re.compile(r"\s*-?\s*\bestampa\b.*$")
_KIT_PREFIX = re.compile(r"^kit\b\s*-?\s*")
_SHIRT_WORD = re.compile(r"^camisetas?\s+(?=[a-z0-9]{1,4}\b)")   # "Camiseta P" is just the size P


@dataclass(frozen=True, slots=True)
class ParsedVariation:
    color_state: str                     # COLOR_FOUND / COLOR_MISSING / COLOR_AMBIGUOUS
    color: str                           # normalized raw color text ("" unless found)
    sizes: tuple[str, ...]               # normalized size tokens, one shirt per token
    sizes_ok: bool                       # False: missing or unreadable sizes


def _split_sizes(part: str) -> list[str]:
    return [token.strip() for token in re.split(r"\s*-\s*", part) if token.strip()]


def _is_size_part(part: str, known_sizes: set[str]) -> bool:
    if not _SIZE_PART.match(part):
        return False
    tokens = _split_sizes(part)
    if all(token in known_sizes for token in tokens):
        return True
    # "P - XX": short tokens with at least one known size; the unknown one is reported
    return any(token in known_sizes for token in tokens)


def _clean_color(part: str) -> tuple[str, bool]:
    """Returns (color text, ambiguous)."""
    text = _PRINT_SUFFIX.sub("", part).strip(" -")
    text = _KIT_PREFIX.sub("", text).strip(" -")
    if not text:
        return "", False
    if re.search(r"\s-\s", text):      # "marrom - preto": two colors, which one is the shirt?
        return text, True
    return text, False


def parse_variation(variation: str, known_sizes: set[str]) -> ParsedVariation:
    """`known_sizes` holds normalized size names and aliases."""
    text = normalize_name(variation)
    parts = [_SHIRT_WORD.sub("", part.strip()).strip() for part in text.split(",") if part.strip()]
    parts = [part for part in parts if part]
    if not parts or len(parts) > 2:
        return ParsedVariation(COLOR_MISSING if not parts else COLOR_AMBIGUOUS, "", (), False)
    size_parts = [part for part in parts if _is_size_part(part, known_sizes)]
    other = [part for part in parts if part not in size_parts]
    if len(size_parts) > 1 or len(other) > 1:
        # e.g. "P,M": cannot tell color from size
        return ParsedVariation(COLOR_AMBIGUOUS, "", (), False)
    sizes = tuple(_split_sizes(size_parts[0])) if size_parts else ()
    if not other:
        return ParsedVariation(COLOR_MISSING, "", sizes, bool(sizes))
    color, ambiguous = _clean_color(other[0])
    if ambiguous:
        return ParsedVariation(COLOR_AMBIGUOUS, color, sizes, bool(sizes))
    if not color:
        return ParsedVariation(COLOR_MISSING, "", sizes, bool(sizes))
    return ParsedVariation(COLOR_FOUND, color, sizes, bool(sizes))


def sku_color_candidates(sku: str, known_colors: dict[str, int]) -> set[int]:
    """Color ids named by whole SKU segments ("X-DOCTOR DOOM-PRETO-M" -> {Preta}).

    `known_colors` maps normalized color names/aliases to color ids."""
    found: set[int] = set()
    for segment in re.split(r"[-_/|]", normalize_name(sku)):
        segment = segment.strip()
        if segment in known_colors:
            found.add(known_colors[segment])
    return found
