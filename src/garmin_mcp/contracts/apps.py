"""Outputs of the tools only the MCP Apps call (activity explorer, trend compare, picker)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .activity import ActivitySummary
from .analytics import DayValue, MetricStats, Window


class ActivityPage(BaseModel):
    window: Window
    offset: int
    limit: int
    items: list[ActivitySummary]
    has_more: bool
    summary: str


class Split(BaseModel):
    index: int
    distance_km: float | None = None
    duration_min: float | None = None
    avg_hr: float | None = None
    avg_speed_kmh: float | None = None
    elevation_gain_m: float | None = None


class ActivityDetail(BaseModel):
    activity: ActivitySummary
    hr_zone_min: list[float] = Field(default_factory=list)
    splits: list[Split] = Field(default_factory=list)
    summary: str
    notes: list[str] = Field(default_factory=list)


class TrendCompare(BaseModel):
    metric: str
    unit: str
    window_a: Window
    window_b: Window
    a: MetricStats
    b: MetricStats
    a_daily: list[DayValue]
    b_daily: list[DayValue]
    change: float | None = None
    change_pct: float | None = None
    summary: str


class PeriodOption(BaseModel):
    value: str
    label: str


class PeriodChoice(BaseModel):
    question: str
    options: list[PeriodOption]
    summary: str
