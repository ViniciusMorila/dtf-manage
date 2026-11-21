"""Date text for the stock screens (stored as ISO text, shown as dd/mm in the user's zone)."""
from datetime import datetime


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except (ValueError, AttributeError):
        return None


def short_date(value: str) -> str:
    moment = _parse(value)
    return moment.strftime("%d/%m") if moment else "—"


def date_time(value: str) -> str:
    moment = _parse(value)
    return moment.strftime("%d/%m/%Y %H:%M") if moment else "—"


def at_time(value: str) -> str:
    moment = _parse(value)
    return moment.strftime("%d/%m às %H:%M") if moment else "—"
