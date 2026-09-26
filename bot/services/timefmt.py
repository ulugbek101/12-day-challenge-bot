"""UTC storage helpers and UTC -> local display formatting.

All timestamps are stored in the database as naive UTC datetimes. They are
only converted to the operator's TZ (from .env) when displayed to a human.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    """Current time as a naive UTC datetime, suitable for storing in MySQL DATETIME."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_display(dt: datetime | None, tz_name: str, *, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Render a naive-UTC datetime in the given IANA timezone. Empty string if dt is None."""
    if dt is None:
        return ""
    aware_utc = dt.replace(tzinfo=timezone.utc)
    local = aware_utc.astimezone(ZoneInfo(tz_name))
    return local.strftime(fmt)
