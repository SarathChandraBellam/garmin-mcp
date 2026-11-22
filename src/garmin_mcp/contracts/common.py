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

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True)


class Note(BaseModel):
    """Returned instead of data when Garmin has nothing for the request."""

    note: str
