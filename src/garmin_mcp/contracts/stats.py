"""Output envelopes that never serialize to an empty MCP ``content`` array."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .analytics import Window

# ok: records found. empty: none in the window (the metric is known to work for this
# account, or the endpoint distinguishes "nothing logged"). unknown: none, and Garmin gives
# the same empty answer whether nothing was logged or the metric is unsupported.
SeriesStatus = Literal["ok", "empty", "unknown"]


class StatsResult(BaseModel):
    """``query_stats`` output: one entry per requested calendar date, plus metadata.

    Every requested date appears in ``data`` at least once. A date with no Garmin record is
    ``{"calendarDate": d, "missing": true}``; the row for "today" carries ``partial: true``.
    """

    metric: str
    start_date: str
    end_date: str
    days: int
    status: SeriesStatus
    days_with_data: int
    units: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    data: list[dict[str, Any]] = Field(default_factory=list)
    outside_range: list[Any] = Field(
        default_factory=list,
        description="Records Garmin returned for dates outside the window (e.g. nearest weigh-ins).",
    )
    window: Window | None = None


class ActivityList(BaseModel):
    """``get_activities`` output. ``activities`` is always present, even when empty."""

    count: int
    activities: list[dict[str, Any]]
    note: str | None = None
    window: Window | None = None
