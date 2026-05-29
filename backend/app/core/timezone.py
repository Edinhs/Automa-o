from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


def app_timezone():
    timezone_name = settings.APP_TIMEZONE or "America/Sao_Paulo"
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-3), timezone_name)


def now_sao_paulo() -> datetime:
    return datetime.now(app_timezone())


def now_sao_paulo_naive() -> datetime:
    return now_sao_paulo().replace(tzinfo=None)


def to_sao_paulo_naive(value: datetime | None, *, assume_utc: bool = False) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        if assume_utc:
            return value.replace(tzinfo=timezone.utc).astimezone(app_timezone()).replace(tzinfo=None)
        return value
    return value.astimezone(app_timezone()).replace(tzinfo=None)


def parse_sao_paulo_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return to_sao_paulo_naive(value)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return to_sao_paulo_naive(parsed)


def sao_paulo_iso(value: datetime | None, *, assume_utc: bool = False) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        tz = timezone.utc if assume_utc else app_timezone()
        localized = value.replace(tzinfo=tz)
    else:
        localized = value
    return localized.astimezone(app_timezone()).isoformat(timespec="seconds")


def sao_paulo_utc_iso(value: datetime | None) -> str | None:
    return sao_paulo_iso(value, assume_utc=True)


def sao_paulo_local_iso(value: datetime | None) -> str | None:
    return sao_paulo_iso(value, assume_utc=False)


def parse_sao_paulo_to_utc_naive(value: str | None) -> datetime | None:
    local_value = parse_sao_paulo_datetime(value)
    if local_value is None:
        return None
    return local_value.replace(tzinfo=app_timezone()).astimezone(timezone.utc).replace(tzinfo=None)
