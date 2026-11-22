"""Typed outputs of the analytics tools.

Clients get these as the tool's output schema and structured content; each one also
carries a short plain-text ``summary`` so a model can answer without reading every field.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .activity import ActivitySummary

Trend = Literal["up", "down", "flat"]
ReadinessLevel = Literal["low", "moderate", "high"]
TimezoneSource = Literal["argument", "header", "elicited", "default"]


class Window(BaseModel):
    """The calendar dates a response covers (start and end inclusive, caller's local dates)."""

    start: str
    end: str
    days: int
    period: str = Field(description="The requested period, or 'custom' for explicit dates.")
    timezone: str
    timezone_source: TimezoneSource = "default"


class DayValue(BaseModel):
    date: str
    value: float | None = None
    partial: bool = Field(default=False, description="True for today: the day is in progress.")


class MetricStats(BaseModel):
    """Statistics for one daily metric over one window. Missing days are excluded."""

    metric: str
    unit: str
    days_with_data: int = 0
    missing_days: int = 0
    average: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    total: float | None = None
    stdev: float | None = Field(default=None, description="Population standard deviation.")
    slope_per_day: float | None = Field(
        default=None, description="Least-squares change per day across the window."
    )
    trend: Trend | None = None
    best_day: DayValue | None = None
    worst_day: DayValue | None = None
    previous_average: float | None = None
    change: float | None = Field(default=None, description="average - previous_average")
    change_pct: float | None = None
    daily: list[DayValue] | None = None


class WellnessOverview(BaseModel):
    window: Window
    previous_window: Window
    metrics: list[MetricStats]
    summary: str
    notes: list[str] = Field(default_factory=list)
    raw: dict[str, list[Any]] | None = None


class TrendsResult(BaseModel):
    window: Window
    compare_window: Window | None = None
    granularity: Literal["day", "week"] = "day"
    metrics: list[MetricStats]
    summary: str
    notes: list[str] = Field(default_factory=list)
    raw: dict[str, list[Any]] | None = None


class PeriodComparison(BaseModel):
    metric: str
    unit: str
    window_a: Window
    window_b: Window
    a: MetricStats
    b: MetricStats
    change: float | None = Field(default=None, description="a.average - b.average")
    change_pct: float | None = None
    summary: str
    notes: list[str] = Field(default_factory=list)


class ActivityGroup(BaseModel):
    key: str
    count: int = 0
    distance_km: float = 0.0
    duration_min: float = 0.0
    moving_min: float = 0.0
    elevation_gain_m: float = 0.0
    calories: float = 0.0
    hr_zone_min: list[float] = Field(
        default_factory=lambda: [0.0] * 5, description="Minutes in HR zones 1-5."
    )


class ActivityReport(BaseModel):
    window: Window
    group_by: Literal["type", "week"]
    totals: ActivityGroup
    groups: list[ActivityGroup]
    longest: ActivitySummary | None = None
    fastest: ActivitySummary | None = None
    activities: list[ActivitySummary] | None = None
    summary: str
    notes: list[str] = Field(default_factory=list)


class SleepNight(BaseModel):
    date: str = Field(description="Wake-up date.")
    total_h: float | None = None
    deep_h: float | None = None
    light_h: float | None = None
    rem_h: float | None = None
    awake_h: float | None = None
    score: float | None = None
    need_h: float | None = None
    bedtime: str | None = Field(default=None, description="Local HH:MM")
    wake_time: str | None = Field(default=None, description="Local HH:MM")


class SleepAnalysis(BaseModel):
    window: Window
    nights: int
    avg_total_h: float | None = None
    avg_deep_h: float | None = None
    avg_light_h: float | None = None
    avg_rem_h: float | None = None
    avg_awake_h: float | None = None
    stage_pct: dict[str, float] = Field(default_factory=dict)
    avg_score: float | None = None
    avg_bedtime: str | None = None
    avg_wake_time: str | None = None
    bedtime_spread_min: float | None = Field(
        default=None, description="Standard deviation of bedtime, minutes (lower = steadier)."
    )
    wake_spread_min: float | None = None
    avg_need_h: float | None = None
    sleep_debt_h: float | None = Field(
        default=None, description="Sum over nights of max(0, need - slept), hours."
    )
    daily: list[SleepNight] | None = None
    summary: str
    notes: list[str] = Field(default_factory=list)


class RecoveryComponent(BaseModel):
    name: Literal["hrv", "sleep", "body_battery"]
    score: float | None = Field(default=None, description="0-100, higher is better")
    weight: float
    detail: dict[str, Any] = Field(default_factory=dict)
    explanation: str


class RecoveryStatus(BaseModel):
    date: str
    timezone: str
    score: float | None = Field(default=None, description="0-100 weighted readiness estimate")
    level: ReadinessLevel | None = None
    components: list[RecoveryComponent]
    summary: str
    notes: list[str] = Field(default_factory=list)


class GoalStreaks(BaseModel):
    metric: Literal["steps", "intensity_minutes"]
    unit: Literal["day", "week"]
    window: Window
    goal: float
    goal_source: Literal["argument", "garmin", "elicited", "default"]
    periods_hit: int
    periods_with_data: int
    hit_rate: float | None = None
    current_streak: int
    longest_streak: int
    daily: list[DayValue] | None = None
    summary: str
    notes: list[str] = Field(default_factory=list)
