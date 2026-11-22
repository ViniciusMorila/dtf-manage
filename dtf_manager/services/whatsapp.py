"""WhatsApp message and link for the manual subscription flow.

The message carries only the plan and the contact data the app already knows
(name, account e-mail, phone). It never includes a password, token or machine id.
"""
import re
from urllib.parse import quote

from dtf_manager.core.constants import APP_NAME

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value, limit=120):
    return _CONTROL.sub(" ", str(value or "")).strip()[:limit]


def build_message(plan, *, name="", email="", phone=""):
    name, email, phone = _clean(name, 200), _clean(email, 254), _clean(phone, 30)
    parts = [f"Olá! Quero assinar o {APP_NAME}. Plano: {plan.name} ({plan.price})."]
    if name:
        parts.append(f"Nome: {name}.")
    parts.append(f"E-mail da conta: {email}." if email
                 else "E-mail da conta: vou informar aqui na conversa.")
    if phone:
        parts.append(f"Telefone: {phone}.")
    return " ".join(parts)


def build_url(number, message):
    """https://wa.me/<digits>?text=<percent-encoded message>."""
    return f"https://wa.me/{number}?text={quote(message, safe='')}"
