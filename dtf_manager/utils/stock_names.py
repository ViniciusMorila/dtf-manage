"""Name normalization shared by the stock catalog, aliases and the spreadsheet parser."""
import re
import unicodedata


def normalize_name(value) -> str:
    """Lowercase, no accents, single spaces: "  PRÉTA  " -> "preta"."""
    text = unicodedata.normalize("NFKD", "" if value is None else str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().casefold()
