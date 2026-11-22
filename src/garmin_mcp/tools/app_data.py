"""Tools only the MCP Apps call (``visibility: ["app"]``). Read-only, like every other tool.

Visibility is a hint to the host, not access control: these go through the same key gate and
the same PII stripping as the model-facing tools.
"""

from __future__ import annotations

from functools import partial
from typing import Annotated, Any

from fastmcp.tools.base import ToolResult
from pydantic import BaseModel, Field

from ..analytics.extract import METRICS, TrendMetric, num
from ..analytics.stats import pct, summarize
from ..contracts import ActivitySummary, Tz
from ..contracts.apps import (
    ActivityDetail,
    ActivityPage,
    PeriodChoice,
    PeriodOption,
    Split,
    TrendCompare,
)
from ..contracts.common import Period
from ._context import call, source
from ._sanitize import no_pii
from ._window import previous_window, resolve_window, window_dates
from .analytics import (
    Result,
    _fetch,
    _today,
    _values,
    blocking,
    get_sleep_analysis,
    get_wellness_overview,
    result,
)

PAGE = 20


async def dashboard_data(period: Period = "last_7d", tz: Tz = None) -> Result:
    """Wellness dashboard data: the overview with one value per day for the sparklines."""
    return await get_wellness_overview(period=period, tz=tz, detail="daily")


async def activity_page(
    period: Period = "last_30d",
    offset: Annotated[int, Field(ge=0, le=10_000)] = 0,
    activity_type: Annotated[str | None, Field(max_length=40)] = None,
    tz: Tz = None,
) -> Result:
    """One page of activities for the activity explorer."""
    w = resolve_window(period, tz=tz)
    src = source()
    rows = await blocking(
        partial(call, src.activities, offset, PAGE + 1, w.start, w.end, activity_type)
    )
    items = [ActivitySummary.from_garmin(a) for a in (rows or []) if isinstance(a, dict)]
    page = ActivityPage(
        window=w,
        offset=offset,
        limit=PAGE,
        items=items[:PAGE],
        has_more=len(items) > PAGE,
        summary=f"{len(items[:PAGE])} activities from {w.start}..{w.end}, from #{offset + 1}.",
    )
    return result(page)


def _split(i: int, lap: dict[str, Any]) -> Split:
    def r(x: float | None, f: float, d: int) -> float | None:
        return round(x * f, d) if x is not None else None

    return Split(
        index=i + 1,
        distance_km=r(num(lap.get("distance")), 1 / 1000, 3),
        duration_min=r(num(lap.get("duration")), 1 / 60, 2),
        avg_hr=num(lap.get("averageHR")),
        avg_speed_kmh=r(num(lap.get("averageSpeed")), 3.6, 2),
        elevation_gain_m=num(lap.get("elevationGain")),
    )


async def activity_detail(activity_id: Annotated[int, Field(gt=0)]) -> Result:
    """One activity for the explorer's detail drawer: key metrics, HR zones and splits (no maps)."""
    src = source()
    raw = no_pii(await blocking(partial(call, src.activity, activity_id))) or {}
    flat = {**raw, **(raw.get("summaryDTO") or {})} if isinstance(raw, dict) else {}
    act = ActivitySummary.from_garmin(flat)
    notes: list[str] = []
    try:
        laps_raw = no_pii(await blocking(partial(call, src.activity_splits, activity_id)))
    except Exception:  # splits are optional; never fail the drawer for them
        laps_raw, notes = None, ["Splits are not available for this activity."]
    laps = laps_raw.get("lapDTOs") if isinstance(laps_raw, dict) else laps_raw
    splits = [_split(i, lap) for i, lap in enumerate(laps or []) if isinstance(lap, dict)]
    detail = ActivityDetail(
        activity=act,
        hr_zone_min=[round((s or 0) / 60, 1) for s in act.hr_zone_secs],
        splits=splits,
        summary=f"{act.name or 'Activity'}: {act.distance_km or 0:g} km in {act.duration_min or 0:g} min.",
        notes=notes,
    )
    return result(detail)


async def sleep_series(period: Period = "last_30d", tz: Tz = None) -> Result:
    """Sleep view data: every night in the window with its stages, bedtime and wake time."""
    return await get_sleep_analysis(period=period, tz=tz, detail="daily")


async def trend_data(
    metric: TrendMetric = "steps",
    period_a: Period = "last_30d",
    period_b: Annotated[
        Period | None, Field(description="Default: the window just before A")
    ] = None,
    tz: Tz = None,
) -> Result:
    """Trend compare data: two windows of one metric with daily values to overlay."""
    wa = resolve_window(period_a, tz=tz)
    zone = (wa.timezone, wa.timezone_source)
    wb = previous_window(wa) if period_b is None else resolve_window(period_b, zone=zone)
    lo, hi = min(wa.start, wb.start), max(wa.end, wb.end)
    series = await _fetch(source(), [metric], lo, hi)
    vals, now = _values(series, metric), _today(wa)
    a = summarize(metric, vals, window_dates(wa), now, include_daily=True)
    b = summarize(metric, vals, window_dates(wb), now, include_daily=True)
    change = (
        round(a.average - b.average, 2) if a.average is not None and b.average is not None else None
    )
    out = TrendCompare(
        metric=metric,
        unit=METRICS[metric].unit,
        window_a=wa,
        window_b=wb,
        a=a.model_copy(update={"daily": None}),
        b=b.model_copy(update={"daily": None}),
        a_daily=a.daily or [],
        b_daily=b.daily or [],
        change=change,
        change_pct=pct(a.average, b.average),
        summary=f"{METRICS[metric].label}: {wa.start}..{wa.end} vs {wb.start}..{wb.end}.",
    )
    return result(out)


PICKER_OPTIONS = [
    ("last_1d", "Today"),
    ("last_7d", "Last 7 days"),
    ("last_15d", "Last 15 days"),
    ("last_30d", "Last 30 days"),
    ("last_90d", "Last 90 days"),
    ("this_week", "This week"),
    ("last_week", "Last week"),
    ("this_month", "This month"),
    ("last_month", "Last month"),
    ("ytd", "Year to date"),
]


def pick_period(
    question: Annotated[str | None, Field(max_length=200)] = None,
) -> ToolResult:
    """Let the user pick a time window by clicking (a visual alternative to asking in chat). The choice comes back as a user message; wait for it."""
    q = (question or "Which time window should I look at?").strip()
    choice = PeriodChoice(
        question=q,
        options=[PeriodOption(value=v, label=label) for v, label in PICKER_OPTIONS],
        summary=q + " Options: " + ", ".join(f"{label} ({v})" for v, label in PICKER_OPTIONS),
    )
    return result(choice)


OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "activity_page": ActivityPage,
    "activity_detail": ActivityDetail,
    "trend_data": TrendCompare,
    "pick_period": PeriodChoice,
}
