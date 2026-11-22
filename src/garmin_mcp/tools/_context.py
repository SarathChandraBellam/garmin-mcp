"""Per-call plumbing shared by every tool: whose key, which source, error mapping, dates."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

from ..auth.keys import GARMIN_KEY_CLAIM
from ..config import get_settings
from ..sdk import GarminApiError, GarminAuthError, PersonalApi

T = TypeVar("T")


def current_garmin_key() -> str:
    """The caller's Garmin key: from the verified OAuth/bearer token (HTTP) or env (stdio)."""
    token = get_access_token()
    if token is not None:
        key = token.claims.get(GARMIN_KEY_CLAIM)
        if isinstance(key, str) and key:
            return key
    env = get_settings().garmin_api_key
    if env is not None and env.get_secret_value().strip():
        return env.get_secret_value().strip()
    raise ToolError(
        "No Garmin Personal API key: connect over OAuth, send header X-Garmin-Api-Key (HTTP) "
        "or set GARMIN_API_KEY (stdio)."
    )


def source() -> PersonalApi:
    return PersonalApi(current_garmin_key())


def call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return fn(*args, **kwargs)
    except (GarminAuthError, GarminApiError) as e:
        raise ToolError(str(e)) from None


def today() -> str:
    return dt.datetime.now(ZoneInfo(get_settings().default_timezone)).date().isoformat()


def shift(d: str, days: int) -> str:
    return (dt.date.fromisoformat(d) + dt.timedelta(days=days)).isoformat()


def check_range(start: str, end: str, max_days: int = 366) -> None:
    s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if s > e:
        raise ToolError("start_date must be <= end_date")
    if (e - s).days > max_days:
        raise ToolError(f"Range too long (max {max_days} days)")
