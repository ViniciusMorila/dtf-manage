"""Subscription plans and prices, read from data/planos.json (never hardcoded in the UI)."""
from dataclasses import dataclass
import json
from pathlib import Path

from dtf_manager.core import config

DEFAULT_PLANS_FILE = Path(__file__).resolve().parents[1] / "data" / "planos.json"
VALID_CODES = ("MENSAL", "SEMESTRAL", "ANUAL", "VITALICIO")


class PlansError(RuntimeError):
    """The plans file is missing or malformed; the message is safe to show."""


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    duration: str
    price: str
    highlight: str = ""     # badge text, e.g. "Mais vantajoso"
    example: bool = False   # prices are placeholders


def _text(value, limit):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def parse_plans(data):
    if not isinstance(data, dict) or not isinstance(data.get("planos"), list):
        raise PlansError("Arquivo de planos inválido.")
    example = data.get("exemplo") is True
    plans, seen = [], set()
    for item in data["planos"]:
        if (not isinstance(item, dict) or item.get("codigo") not in VALID_CODES
                or item["codigo"] in seen or not _text(item.get("nome"), 40)
                or not _text(item.get("duracao"), 40) or not _text(item.get("preco"), 40)
                or not (item.get("destaque") is None or _text(item.get("destaque"), 30))):
            raise PlansError("Arquivo de planos inválido.")
        seen.add(item["codigo"])
        plans.append(Plan(item["codigo"], item["nome"].strip(), item["duracao"].strip(),
                          item["preco"].strip(), (item.get("destaque") or "").strip(), example))
    if not plans:
        raise PlansError("Nenhum plano configurado.")
    return tuple(plans)


def load_plans(path=None):
    """Plans from DTF_PLANS_FILE, else the bundled data/planos.json."""
    source = Path(path) if path else Path(config.plans_file_override() or DEFAULT_PLANS_FILE)
    try:
        return parse_plans(json.loads(source.read_text(encoding="utf-8-sig")))
    except PlansError:
        raise
    except (OSError, ValueError):
        raise PlansError("Não foi possível ler o arquivo de planos.") from None
