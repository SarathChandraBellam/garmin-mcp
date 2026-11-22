"""Shared input types and small output models for the MCP tools."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

DateStr = Annotated[str, Field(pattern=DATE_PATTERN, description="YYYY-MM-DD")]
OptDate = Annotated[
    str | None,
    Field(default=None, pattern=DATE_PATTERN, description="YYYY-MM-DD; default today"),
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

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True)


class Note(BaseModel):
    """Returned instead of data when Garmin has nothing for the request."""

    note: str
