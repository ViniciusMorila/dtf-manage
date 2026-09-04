import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any


def normalize_header(value: Any) -> str:
    return re.sub(r"\s+", " ", text_value(value).lstrip("\ufeff")).strip()


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        if value.is_integer():
            return str(int(value))
    return str(value).strip()


def nullable_text(value: Any) -> str | None:
    result = text_value(value)
    return result or None


def normalize_variation(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def parse_positive_integer(value: Any) -> int:
    if isinstance(value, bool) or value is None or text_value(value) == "":
        raise ValueError("quantidade vazia")
    try:
        number = Decimal(text_value(value).replace(",", "."))
    except InvalidOperation as error:
        raise ValueError("quantidade não numérica") from error
    if not number.is_finite() or number != number.to_integral_value() or number <= 0:
        raise ValueError("quantidade deve ser um inteiro positivo")
    return int(number)


def parse_optional_price(value: Any) -> float | None:
    if value is None or text_value(value) == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(float(value)) else None
    raw = text_value(value).replace("R$", "").replace(" ", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        result = float(raw)
        return result if math.isfinite(result) else None
    except ValueError:
        return None

