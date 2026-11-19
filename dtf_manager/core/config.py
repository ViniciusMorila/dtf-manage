"""Runtime configuration read from environment variables.

Nothing here is secret: the API URL, the payment link and the support contact
are public values. Credentials never pass through this module.
"""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_API_URL = "https://dtf-manager-api-production.up.railway.app"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
APP_CONFIG_FILE = Path(__file__).resolve().parents[1] / "data" / "app_config.json"
EXAMPLE_WHATSAPP = "5511999999999"


class ConfigError(ValueError):
    """Invalid runtime configuration; the message is safe to show."""


def _validated_url(value, variable, *, allow_loopback_http):
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    secure = parts.scheme == "https" and bool(host)
    local = allow_loopback_http and parts.scheme == "http" and host in _LOOPBACK_HOSTS
    if not (secure or local) or parts.username or parts.password:
        raise ConfigError(
            f"{variable} inválida. Use uma URL https://"
            + (" (http:// só é aceito para localhost)." if allow_loopback_http else "."))
    return value.rstrip("/")


def api_base_url():
    value = os.environ.get("DTF_API_URL", "").strip()
    if not value:
        return DEFAULT_API_URL
    return _validated_url(value, "DTF_API_URL", allow_loopback_http=True)


def environment_name(base_url=None):
    """Stable credential scope: 'production' for the default API, otherwise a
    short fingerprint, so a development token is never sent to production."""
    url = (base_url or api_base_url()).rstrip("/")
    if url == DEFAULT_API_URL:
        return "production"
    return "dev-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]


def payment_url():
    """Optional secondary purchase page (DTF_PAYMENT_URL); None when not configured."""
    value = os.environ.get("DTF_PAYMENT_URL", "").strip()
    if not value:
        return None
    try:
        return _validated_url(value, "DTF_PAYMENT_URL", allow_loopback_http=False)
    except ConfigError:
        return None


def _app_config():
    """Values packaged with the executable (data/app_config.json); {} when unreadable."""
    try:
        data = json.loads(APP_CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def text_field(data, name):
    """Stripped text of a JSON field; anything that is not a string counts as empty."""
    value = data.get(name, "")
    return value.strip() if isinstance(value, str) else ""


def valid_whatsapp(value):
    return isinstance(value, str) and value.isascii() and value.isdigit() and 10 <= len(value) <= 15


def whatsapp_number():
    """Seller WhatsApp, international format, digits only (e.g. 5511999999999).

    Comes from the packaged data/app_config.json (field whatsapp_numero). The
    DTF_WHATSAPP_NUMBER environment variable only overrides it, for development.
    The shipped example number is treated as not configured, so the app shows a
    warning instead of opening a conversation with a fake number.
    """
    override = os.environ.get("DTF_WHATSAPP_NUMBER", "").strip()
    if override:
        return override if valid_whatsapp(override) else None
    packaged = text_field(_app_config(), "whatsapp_numero")
    return packaged if valid_whatsapp(packaged) and packaged != EXAMPLE_WHATSAPP else None


def plans_file_override():
    value = os.environ.get("DTF_PLANS_FILE", "").strip()
    return value or None


def support_contact():
    """Support contact: packaged contato_suporte; DTF_SUPPORT_CONTACT overrides it."""
    override = os.environ.get("DTF_SUPPORT_CONTACT", "").strip()
    return (override or text_field(_app_config(), "contato_suporte"))[:120]


def no_auth_allowed():
    return os.environ.get("DTF_ALLOW_NO_AUTH") == "1"
