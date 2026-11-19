"""Runtime configuration read from environment variables.

Nothing here is secret: the API URL, the payment link and the support contact
are public values. Credentials never pass through this module.
"""
import hashlib
import os
from urllib.parse import urlsplit

DEFAULT_API_URL = "https://dtf-manager-api-production.up.railway.app"
# Example value. Replace it with the real payment page through DTF_PAYMENT_URL.
DEFAULT_PAYMENT_URL = "https://example.com/dtf-manager/planos"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


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
    value = os.environ.get("DTF_PAYMENT_URL", "").strip() or DEFAULT_PAYMENT_URL
    try:
        return _validated_url(value, "DTF_PAYMENT_URL", allow_loopback_http=False)
    except ConfigError:
        return DEFAULT_PAYMENT_URL


def support_contact():
    return os.environ.get("DTF_SUPPORT_CONTACT", "").strip()[:120]


def no_auth_allowed():
    return os.environ.get("DTF_ALLOW_NO_AUTH") == "1"
