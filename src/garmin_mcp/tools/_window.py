"""Resolve a tool's date arguments into one concrete, inclusive window in the caller's timezone.

Precedence: explicit ``start_date`` / ``end_date`` win over ``period``, and ``period`` wins over
the tool's own default. The timezone comes from the ``tz`` argument, then the
``X-Timezone`` request header, then the server's ``DEFAULT_TIMEZONE``.
"""

from __future__ import annotations

import datetime as dt

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from ..config import get_settings
from ..contracts.analytics import TimezoneSource, Window
from . import _context
from ._context import TZ_HEADER, _zone

DEFAULT_PERIOD = "last_7d"
_LAST_N = {"last_1d": 1, "last_7d": 7, "last_15d": 15, "last_30d": 30, "last_90d": 90}


def resolve_tz(tz: str | None = None) -> tuple[str, TimezoneSource]:
    """(IANA name, where it came from): the ``tz`` argument, then the X-Timezone header, then
    DEFAULT_TIMEZONE. Same order and errors as :func:`._context.caller_zone`."""
    if tz and tz.strip():
        return _zone(tz.strip(), "tz").key, "argument"
    header = {k.lower(): v for k, v in get_http_headers(include_all=True).items()}
    if header.get(TZ_HEADER, "").strip():
        return _zone(header[TZ_HEADER].strip(), "X-Timezone header").key, "header"
    return _zone(get_settings().default_timezone, "DEFAULT_TIMEZONE").key, "default"


def timezone_is_configured() -> bool:
    """False when "today" would fall back to the built-in UTC default (nobody chose a zone)."""
    return "default_timezone" in get_settings().model_fields_set


def local_today(name: str) -> dt.date:
    return _context._utcnow().astimezone(_zone(name, "tz")).date()


def period_bounds(period: str, today: dt.date) -> tuple[dt.date, dt.date]:
    """Inclusive (start, end) dates for a relative period ending relative to ``today``."""
    if period in _LAST_N:
        return today - dt.timedelta(days=_LAST_N[period] - 1), today
    if period == "today":
        return today, today
    if period == "yesterday":
        y = today - dt.timedelta(days=1)
        return y, y
    monday = today - dt.timedelta(days=today.weekday())
    if period == "this_week":
        return monday, today
    if period == "last_week":
        return monday - dt.timedelta(days=7), monday - dt.timedelta(days=1)
    first = today.replace(day=1)
    if period == "this_month":
        return first, today
    if period == "last_month":
        last_prev = first - dt.timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    if period == "ytd":
        return today.replace(month=1, day=1), today
    raise ToolError(f"Unknown period {period!r}")


def resolve_window(
    period: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    tz: str | None = None,
    default: str = DEFAULT_PERIOD,
    zone: tuple[str, TimezoneSource] | None = None,
) -> Window:
    """The window a call covers. ``zone`` short-circuits timezone resolution when known."""
    name, source = zone or resolve_tz(tz)
    today = local_today(name)
    if start_date or end_date:
        end = dt.date.fromisoformat(end_date) if end_date else today
        if start_date:
            start = dt.date.fromisoformat(start_date)
        else:  # only an end date: take the default period's length, ending there
            s, e = period_bounds(period or default, today)
            start = end - (e - s)
        label = "custom"
    else:
        label = period or default
        start, end = period_bounds(label, today)
    if start > end:
        raise ToolError(f"start_date ({start}) must be <= end_date ({end})")
    return Window(
        start=start.isoformat(),
        end=end.isoformat(),
        days=(end - start).days + 1,
        period=label,
        timezone=name,
        timezone_source=source,
    )


def previous_window(w: Window) -> Window:
    """The window of the same length that ends the day before ``w`` starts."""
    start = dt.date.fromisoformat(w.start)
    end = start - dt.timedelta(days=1)
    s = end - dt.timedelta(days=w.days - 1)
    return w.model_copy(
        update={
            "start": s.isoformat(),
            "end": end.isoformat(),
            "period": f"previous_{w.period}",
        }
    )


def window_dates(w: Window) -> list[str]:
    s = dt.date.fromisoformat(w.start)
    return [(s + dt.timedelta(days=i)).isoformat() for i in range(w.days)]
