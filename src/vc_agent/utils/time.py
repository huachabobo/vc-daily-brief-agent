from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str) -> datetime:
    cleaned = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_local_date(value: datetime, tz_name: str) -> str:
    return value.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")


def hours_ago(hours: int) -> datetime:
    return utcnow() - timedelta(hours=hours)
