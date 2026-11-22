"""Shared input types and small output models for the MCP tools."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from mcp.types import ToolAnnotations
from pydantic import AfterValidator, BaseModel, Field

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


def _real_date(value: str | None) -> str | None:
    """Reject strings that match YYYY-MM-DD but are not calendar dates (e.g. 2026-13-40)."""
    if value is not None:
        try:
            dt.date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{value!r} is not a valid calendar date (YYYY-MM-DD)") from None
    return value


DateStr = Annotated[
    str, Field(pattern=DATE_PATTERN, description="YYYY-MM-DD"), AfterValidator(_real_date)
]
OptDate = Annotated[
    str | None,
    Field(default=None, pattern=DATE_PATTERN, description="YYYY-MM-DD; default today"),
    AfterValidator(_real_date),
]
Tz = Annotated[
    str | None,
    Field(
        default=None,
        max_length=64,
        description=(
            "IANA time zone used for 'today' (default dates, partial flag), e.g. Asia/Kolkata; "
            "default: X-Timezone header, then the server's DEFAULT_TIMEZONE"
        ),
    ),
]

Metric = Literal[
    "steps",
    "stress",
    "body_battery",
    "sleep",
    "hrv",
    "weight",
    "vo2max",
    "hydration",
    "daily_summaries",
    "wellness_activities",
]

Period = Literal[
    "today",
    "yesterday",
    "last_1d",
    "last_7d",
    "last_15d",
    "last_30d",
    "last_90d",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "ytd",
]
PERIOD_DESCRIPTION = (
    "Relative window in the caller's timezone: today, yesterday, last_1d (= today), last_7d, "
    "last_15d, last_30d, last_90d (each ending today, inclusive), this_week / last_week "
    "(Monday-Sunday), this_month, last_month, ytd. Explicit start_date/end_date win over period."
)
OptPeriod = Annotated[Period | None, Field(default=None, description=PERIOD_DESCRIPTION)]

Detail = Literal["summary", "daily", "raw"]
DETAIL_DESCRIPTION = (
    "summary (default, smallest): statistics only; daily: plus one value per day; "
    "raw: plus the PII-free Garmin records the statistics were computed from."
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True)


class Note(BaseModel):
    """Returned instead of data when Garmin has nothing for the request."""

    note: str
