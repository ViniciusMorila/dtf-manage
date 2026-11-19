"""License returned by the API (contract: API_LICENCAS.md, "Objeto de licença")."""
from dataclasses import dataclass
from datetime import datetime, timezone

PLANS = {"TESTE": "Teste", "MENSAL": "Mensal", "SEMESTRAL": "Semestral",
         "ANUAL": "Anual", "VITALICIO": "Vitalício"}
STATUSES = {"ATIVA", "EXPIRADA", "BLOQUEADA"}


def parse_timestamp(value):
    """ISO 8601 (UTC) to an aware datetime; None for missing or invalid values."""
    if not isinstance(value, str) or not value or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def format_timestamp(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class LicenseInfo:
    plano: str
    status: str
    data_ativacao: str | None
    data_expiracao: str | None
    dias_restantes: int | None
    vitalicia: bool

    @classmethod
    def from_dict(cls, data):
        """Strict parse: any malformed field returns None (never authorizes)."""
        if not isinstance(data, dict):
            return None
        plano, status = data.get("plano"), data.get("status")
        vitalicia, days = data.get("vitalicia"), data.get("dias_restantes")
        if plano not in PLANS or status not in STATUSES or not isinstance(vitalicia, bool):
            return None
        if days is not None and (type(days) is not int or days < 0):
            return None
        expiry, activation = data.get("data_expiracao"), data.get("data_ativacao")
        if expiry is not None and parse_timestamp(expiry) is None:
            return None
        if activation is not None and parse_timestamp(activation) is None:
            return None
        return cls(plano, status, activation, expiry, days, vitalicia)

    def to_dict(self):
        return {"plano": self.plano, "status": self.status, "data_ativacao": self.data_ativacao,
                "data_expiracao": self.data_expiracao, "dias_restantes": self.dias_restantes,
                "vitalicia": self.vitalicia}

    @property
    def active(self):
        return self.status == "ATIVA"

    @property
    def plan_name(self):
        return PLANS.get(self.plano, self.plano)


@dataclass(frozen=True)
class LicenseStatus:
    """A license plus the server clock at the moment it was issued."""
    info: LicenseInfo
    server_now: str

    @classmethod
    def from_response(cls, data):
        if not isinstance(data, dict):
            return None
        info = LicenseInfo.from_dict(data.get("licenca"))
        server_now = data.get("servidor_agora")
        if info is None or parse_timestamp(server_now) is None:
            return None
        return cls(info, server_now)
