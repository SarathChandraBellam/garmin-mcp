"""Per-call plumbing shared by every tool: whose key, which source, error mapping, dates."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from ..auth.keys import extract_key
from ..config import get_settings
from ..sdk import GarminApiError, GarminAuthError, PersonalApi

T = TypeVar("T")


def current_garmin_key() -> str:
    """The caller's Garmin key: from the request headers (HTTP) or GARMIN_API_KEY (stdio)."""
    key = extract_key(get_http_headers(include_all=True))
    if key:
        return key
    env = get_settings().garmin_api_key
    if env is not None and env.get_secret_value().strip():
        return env.get_secret_value().strip()
    raise ToolError(
        "No Garmin Personal API key: send header X-Garmin-Api-Key (HTTP) "
        "or set GARMIN_API_KEY (stdio)."
    )


def source() -> PersonalApi:
    return PersonalApi(current_garmin_key())


def call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return fn(*args, **kwargs)
    except (GarminAuthError, GarminApiError) as e:
        raise ToolError(str(e)) from None


TZ_HEADER = "x-timezone"


def _utcnow() -> dt.datetime:
    """The current instant (patched in tests to freeze the clock)."""
    return dt.datetime.now(dt.timezone.utc)


def _zone(name: str, source_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        shown = name if len(name) <= 64 else name[:61] + "..."
        raise ToolError(
            f"{source_name}: unknown IANA time zone {shown!r} (use a name like Asia/Kolkata "
            "or America/New_York)"
        ) from None


def caller_zone(tz: str | None = None) -> ZoneInfo:
    """Time zone for "today": the ``tz`` argument, else the X-Timezone header, else
    DEFAULT_TIMEZONE."""
    if tz and tz.strip():
        return _zone(tz.strip(), "tz")
    header = {k.lower(): v for k, v in get_http_headers(include_all=True).items()}
    if header.get(TZ_HEADER, "").strip():
        return _zone(header[TZ_HEADER].strip(), "X-Timezone header")
    return _zone(get_settings().default_timezone, "DEFAULT_TIMEZONE")


def today(tz: str | None = None) -> str:
    return _utcnow().astimezone(caller_zone(tz)).date().isoformat()


def shift(d: str, days: int) -> str:
    return (dt.date.fromisoformat(d) + dt.timedelta(days=days)).isoformat()


def inclusive_days(start: str, end: str) -> int:
    return (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1


def check_range(start: str, end: str, max_days: int = 366, what: str = "this tool") -> None:
    """Validate a start/end window; ``max_days`` counts calendar dates inclusively."""
    s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if s > e:
        raise ToolError(f"start_date ({start}) must be <= end_date ({end})")
    n = (e - s).days + 1
    if n > max_days:
        raise ToolError(
            f"Range too long for {what}: {start}..{end} is {n} days "
            f"(max {max_days} days, start and end inclusive)"
        )


def date_span(start: str, end: str) -> list[str]:
    s = dt.date.fromisoformat(start)
    return [(s + dt.timedelta(days=i)).isoformat() for i in range(inclusive_days(start, end))]


def chunks(start: str, end: str, size: int) -> list[tuple[str, str]]:
    """Split an inclusive window into consecutive inclusive windows of at most ``size`` days."""
    days = date_span(start, end)
    return [(days[i], days[min(i + size, len(days)) - 1]) for i in range(0, len(days), size)]
