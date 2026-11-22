"""Analytics tools: they fetch a window of data and answer with statistics, not raw payloads.

Each returns a typed model (an output schema plus structured content) and a short text
summary. ``detail`` keeps responses small by default. Questions are asked through
:mod:`._elicit` only when they help, and every tool also works with no questions asked.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable
from functools import partial
from typing import Annotated, Any, Literal, TypeVar

import anyio
import mcp_types as mt
from fastmcp import Context
from fastmcp.tools.base import ToolResult
from pydantic import BaseModel, Field

from ..analytics import activities as act_an
from ..analytics import recovery as rec
from ..analytics import sleep as sleep_an
from ..analytics.extract import METRICS, OVERVIEW_METRICS, TrendMetric, daily_values, dig
from ..analytics.stats import describe, pct, rollup_weekly, summarize, with_previous
from ..analytics.streaks import DEFAULT_GOALS, streaks, weekly_totals
from ..contracts import ActivitySummary, OptDate, Tz
from ..contracts.analytics import (
    ActivityReport,
    GoalStreaks,
    PeriodComparison,
    RecoveryStatus,
    SleepAnalysis,
    TrendsResult,
    WellnessOverview,
    Window,
)
from ..contracts.common import DETAIL_DESCRIPTION, PERIOD_DESCRIPTION, Detail, Period
from ..sdk import PersonalApi
from ._context import call, parallel, source, today
from ._elicit import Answer, Elicitor, choice_schema
from ._fetch import call_count, fetch_series
from ._sanitize import compact, no_pii
from ._series import row_date
from ._window import (
    previous_window,
    resolve_tz,
    resolve_window,
    timezone_is_configured,
    window_dates,
)

T = TypeVar("T")
LARGE_CALLS = 12  # confirm before a request needs this many Garmin calls
MAX_ACTIVITY_PAGES = 10  # 10 x 100 activities per summary
Result = ToolResult | mt.InputRequiredResult

PeriodArg = Annotated[Period | None, Field(description=PERIOD_DESCRIPTION)]
DetailArg = Annotated[Detail, Field(description=DETAIL_DESCRIPTION)]
Series = dict[str, tuple[list[Any], list[Any]]]


def result(model: BaseModel) -> ToolResult:
    """Structured content plus two text blocks: the summary, then the full JSON."""
    summary = getattr(model, "summary", "")
    return ToolResult(
        content=[
            mt.TextContent(type="text", text=summary),
            mt.TextContent(type="text", text=model.model_dump_json(exclude_none=True)),
        ],
        structured_content=model.model_dump(mode="json", exclude_none=True),
    )


async def blocking(fn: Callable[[], T]) -> T:
    """Run Garmin I/O off the event loop (contextvars, and so request headers, are copied)."""
    return await anyio.to_thread.run_sync(fn)


# ---- shared question flows ----------------------------------------------------------------


async def window_or_ask(
    el: Elicitor,
    notes: list[str],
    period: str | None,
    start_date: str | None,
    end_date: str | None,
    tz: str | None,
    default: str,
) -> Window | mt.InputRequiredResult:
    """Resolve the window; ask for the timezone when "today"/"yesterday" depends on it and
    nobody has said which zone the user is in."""
    zone = resolve_tz(tz)
    label = period or (None if start_date or end_date else default)
    if zone[1] == "default" and not timezone_is_configured() and label in ("today", "yesterday"):
        ans = await el.ask(
            "timezone",
            f"Which timezone are you in? It decides what '{label}' means "
            "(an IANA name such as Europe/Berlin or America/New_York).",
            {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "title": "Timezone", "maxLength": 64}
                },
                "required": ["timezone"],
            },
        )
        if isinstance(ans, mt.InputRequiredResult):
            return ans
        picked = (ans.value or {}).get("timezone") if ans.accepted else None
        if isinstance(picked, str) and picked.strip():
            try:
                name, _ = resolve_tz(picked.strip())
                zone = (name, "elicited")
            except Exception:
                notes.append(f"Ignored unknown timezone {picked!r}; using {zone[0]}.")
        else:
            notes.append(
                f"Assumed timezone {zone[0]} for '{label}'. Pass tz= or the X-Timezone "
                "header to use your local day."
            )
    return resolve_window(period, start_date, end_date, default=default, zone=zone)


async def confirm_large(
    el: Elicitor, notes: list[str], calls: int, w: Window, weekly_option: bool
) -> str | mt.InputRequiredResult:
    """'proceed', 'weekly' or 'shorten' for a request needing >= LARGE_CALLS Garmin calls."""
    if calls < LARGE_CALLS:
        return "proceed"
    options = [("proceed", f"Fetch all {w.days} days ({calls} Garmin calls)")]
    if weekly_option:
        options.append(("weekly", "Fetch all days but answer with weekly averages"))
    options.append(("shorten", "Use the last 30 days instead"))
    ans = await el.ask(
        "large_range",
        f"{w.start}..{w.end} needs {calls} calls to Garmin and may take a while. Continue?",
        choice_schema("choice", options, "How much data?"),
    )
    if isinstance(ans, mt.InputRequiredResult):
        return ans
    if not ans.accepted:
        if ans.status == "declined":
            notes.append("Large range declined; used the last 30 days instead.")
            return "shorten"
        notes.append(f"This window needed {calls} Garmin calls.")
        return "proceed"
    return str((ans.value or {}).get("choice") or "proceed")


def _shortened(w: Window) -> Window:
    end = dt.date.fromisoformat(w.end)
    return w.model_copy(
        update={
            "start": (end - dt.timedelta(days=29)).isoformat(),
            "days": 30,
            "period": "last_30d",
        }
    )


def _dated(rows: list[Any]) -> list[tuple[str | None, Any]]:
    return [(row_date(r), r) for r in rows]


def _values(series: Series, metric: str) -> dict[str, float]:
    return daily_values(metric, _dated(series.get(METRICS[metric].series, ([], []))[0]))


def _raw(series: Series, w: Window) -> dict[str, list[Any]]:
    return {
        name: [
            compact(no_pii(r)) for r in rows if (d := row_date(r)) is None or w.start <= d <= w.end
        ]
        for name, (rows, _) in series.items()
    }


def _series_for(metrics: Iterable[str]) -> set[str]:
    return {METRICS[m].series for m in metrics}


async def _fetch(src: PersonalApi, metrics: Iterable[str], start: str, end: str) -> Series:
    return await blocking(partial(fetch_series, src, _series_for(metrics), start, end))


def _today(w: Window) -> str:
    return today(w.timezone)


# ---- tools ---------------------------------------------------------------------------------


async def get_wellness_overview(
    period: PeriodArg = None,
    start_date: OptDate = None,
    end_date: OptDate = None,
    tz: Tz = None,
    detail: DetailArg = "summary",
    ctx: Context | None = None,
) -> Result:
    """Wellness at a glance for a window (default last_7d): average/min/max and trend for sleep, resting HR, HRV, stress, Body Battery and steps, each compared with the previous window of the same length."""
    el = Elicitor(ctx, "get_wellness_overview", locals_args(locals()))
    notes: list[str] = []
    w = await window_or_ask(el, notes, period, start_date, end_date, tz, "last_7d")
    if isinstance(w, mt.InputRequiredResult):
        return w
    metrics = list(OVERVIEW_METRICS)
    prev = previous_window(w)
    choice = await confirm_large(
        el, notes, call_count(_series_for(metrics), prev.start, w.end), w, False
    )
    if isinstance(choice, mt.InputRequiredResult):
        return choice
    if choice == "shorten":
        w = _shortened(w)
        prev = previous_window(w)
    series = await _fetch(source(), metrics, prev.start, w.end)
    now = _today(w)
    stats = []
    for m in metrics:
        vals = _values(series, m)
        cur = summarize(m, vals, window_dates(w), now, include_daily=detail != "summary")
        stats.append(with_previous(cur, summarize(m, vals, window_dates(prev), now)))
    summary = f"{w.start}..{w.end}: " + "; ".join(describe(s) for s in stats) + "."
    out = WellnessOverview(
        window=w,
        previous_window=prev,
        metrics=stats,
        summary=summary,
        notes=notes,
        raw=_raw(series, w) if detail == "raw" else None,
    )
    return result(out)


async def get_trends(
    metrics: Annotated[
        list[TrendMetric], Field(min_length=1, max_length=6, description="1-6 daily metrics")
    ],
    period: PeriodArg = None,
    start_date: OptDate = None,
    end_date: OptDate = None,
    tz: Tz = None,
    compare_to: Literal["previous_period", "none"] = "previous_period",
    granularity: Literal["day", "week"] = "day",
    detail: DetailArg = "summary",
    ctx: Context | None = None,
) -> Result:
    """Trend statistics for chosen metrics over a window (default last_30d): average, total, spread, slope, best/worst day, missing days, and the change vs the previous period. granularity=week rolls the daily values up into weekly averages."""
    el = Elicitor(ctx, "get_trends", locals_args(locals()))
    notes: list[str] = []
    w = await window_or_ask(el, notes, period, start_date, end_date, tz, "last_30d")
    if isinstance(w, mt.InputRequiredResult):
        return w
    ms = list(dict.fromkeys(metrics))
    prev = previous_window(w) if compare_to == "previous_period" else None
    start = prev.start if prev else w.start
    choice = await confirm_large(el, notes, call_count(_series_for(ms), start, w.end), w, True)
    if isinstance(choice, mt.InputRequiredResult):
        return choice
    if choice == "shorten":
        w = _shortened(w)
        prev = previous_window(w) if prev else None
    if choice == "weekly":
        granularity = "week"
    series = await _fetch(source(), ms, prev.start if prev else w.start, w.end)
    now = _today(w)
    out_stats = []
    for m in ms:
        vals = _values(series, m)
        cur = summarize(m, vals, window_dates(w), now, include_daily=detail != "summary")
        if prev:
            cur = with_previous(cur, summarize(m, vals, window_dates(prev), now))
        if granularity == "week" and cur.daily:
            cur.daily = rollup_weekly(cur.daily)
        out_stats.append(cur)
    out = TrendsResult(
        window=w,
        compare_window=prev,
        granularity=granularity,
        metrics=out_stats,
        summary=f"{w.start}..{w.end}: " + "; ".join(describe(s) for s in out_stats) + ".",
        notes=notes,
        raw=_raw(series, w) if detail == "raw" else None,
    )
    return result(out)


_B_OPTIONS = [
    ("previous", "The same number of days just before"),
    ("last_week", "Last week"),
    ("last_month", "Last month"),
    ("last_30d", "The last 30 days"),
    ("last_90d", "The last 90 days"),
]


async def compare_periods(
    metric: TrendMetric,
    period_a: PeriodArg = None,
    period_b: Annotated[
        Period | Literal["previous"] | None,
        Field(description="Second window; 'previous' = same length just before A"),
    ] = None,
    a_start_date: OptDate = None,
    a_end_date: OptDate = None,
    b_start_date: OptDate = None,
    b_end_date: OptDate = None,
    tz: Tz = None,
    ctx: Context | None = None,
) -> Result:
    """Compare one metric across two windows side by side (A default this_week; B asked for, else the previous window of the same length): stats for each and the change A - B."""
    el = Elicitor(ctx, "compare_periods", locals_args(locals()))
    notes: list[str] = []
    wa = await window_or_ask(el, notes, period_a, a_start_date, a_end_date, tz, "this_week")
    if isinstance(wa, mt.InputRequiredResult):
        return wa
    zone = (wa.timezone, wa.timezone_source)
    b_label: str | None = period_b
    if b_label is None and not (b_start_date or b_end_date):
        ans = await el.ask(
            "period_b",
            f"Compare {METRICS[metric].label.lower()} for {wa.start}..{wa.end} with which period?",
            choice_schema("period_b", _B_OPTIONS, "Compare with"),
        )
        if isinstance(ans, mt.InputRequiredResult):
            return ans
        b_label = str((ans.value or {}).get("period_b") or "") if ans.accepted else None
        if not b_label:
            b_label = "previous"
            notes.append("No second period given; compared with the previous window.")
    if b_label == "previous" and not (b_start_date or b_end_date):
        wb = previous_window(wa)
    else:
        wb = resolve_window(b_label, b_start_date, b_end_date, default="last_7d", zone=zone)
    src = source()
    ranges = [(wa.start, wa.end), (wb.start, wb.end)]
    lo, hi = min(r[0] for r in ranges), max(r[1] for r in ranges)
    if (dt.date.fromisoformat(hi) - dt.date.fromisoformat(lo)).days + 1 <= wa.days + wb.days + 31:
        series = await _fetch(src, [metric], lo, hi)
        sa = sb = series
    else:  # far apart: fetch the two windows separately instead of everything in between
        sa = await _fetch(src, [metric], wa.start, wa.end)
        sb = await _fetch(src, [metric], wb.start, wb.end)
    now = _today(wa)
    a = summarize(metric, _values(sa, metric), window_dates(wa), now)
    b = summarize(metric, _values(sb, metric), window_dates(wb), now)
    change = (
        round(a.average - b.average, 2) if a.average is not None and b.average is not None else None
    )
    label, unit = METRICS[metric].label, METRICS[metric].unit
    if change is None:
        summary = (
            f"{label}: not enough data to compare {wa.start}..{wa.end} with {wb.start}..{wb.end}."
        )
    else:
        summary = (
            f"{label} averaged {a.average:g} {unit} in {wa.start}..{wa.end} vs {b.average:g} "
            f"{unit} in {wb.start}..{wb.end} ({change:+g} {unit}"
            + (
                f", {pct(a.average, b.average):+.1f}%)."
                if pct(a.average, b.average) is not None
                else ")."
            )
        )
    out = PeriodComparison(
        metric=metric,
        unit=unit,
        window_a=wa,
        window_b=wb,
        a=a,
        b=b,
        change=change,
        change_pct=pct(a.average, b.average),
        summary=summary,
        notes=notes,
    )
    return result(out)


def fetch_activities(
    src: PersonalApi, start: str, end: str, activity_type: str | None
) -> tuple[list[dict[str, Any]], bool]:
    """All activities in [start, end] (up to MAX_ACTIVITY_PAGES pages). (rows, truncated)."""
    acts: list[dict[str, Any]] = []
    for page in range(MAX_ACTIVITY_PAGES):
        batch = call(src.activities, page * 100, 100, start, end, activity_type) or []
        acts.extend(a for a in batch if isinstance(a, dict))
        if len(batch) < 100:
            return acts, False
    return acts, True


async def get_activity_summary(
    period: PeriodArg = None,
    start_date: OptDate = None,
    end_date: OptDate = None,
    tz: Tz = None,
    group_by: Literal["type", "week"] = "type",
    activity_type: Annotated[
        str | None, Field(max_length=40, description="Only this type, e.g. running")
    ] = None,
    detail: DetailArg = "summary",
    ctx: Context | None = None,
) -> Result:
    """Training volume for a window (default last_30d), grouped by activity type or week: count, distance, time, elevation, calories and minutes in each HR zone, plus the longest and fastest activity."""
    el = Elicitor(ctx, "get_activity_summary", locals_args(locals()))
    notes: list[str] = []
    w = await window_or_ask(el, notes, period, start_date, end_date, tz, "last_30d")
    if isinstance(w, mt.InputRequiredResult):
        return w
    src = source()
    raw, truncated = await blocking(partial(fetch_activities, src, w.start, w.end, activity_type))
    acts = [ActivitySummary.from_garmin(a) for a in raw]
    totals, groups, longest, fastest = act_an.roll_up(acts, group_by)
    if truncated:
        notes.append(f"Only the newest {len(acts)} activities were included.")
    if not acts:
        notes.append(
            "No recorded activities in this window. Daily intensity minutes do not create "
            "activities (see get_trends intensity_minutes)."
        )
    top = ", ".join(f"{g.key} {g.count}x" for g in groups[:3]) if group_by == "type" else ""
    summary = (
        f"{w.start}..{w.end}: {totals.count} activities, {totals.distance_km:g} km, "
        f"{totals.duration_min / 60:.1f} h, {totals.elevation_gain_m:g} m climb"
        + (f" ({top})" if top else "")
        + "."
    )
    out = ActivityReport(
        window=w,
        group_by=group_by,
        totals=totals,
        groups=groups,
        longest=longest,
        fastest=fastest,
        activities=acts if detail != "summary" else None,
        summary=summary,
        notes=notes,
    )
    return result(out)


def _sleep_nights(rows: list[Any], w: Window) -> list[Any]:
    by_date: dict[str, Any] = {}
    for r in rows:
        d = row_date(r)
        if d and w.start <= d <= w.end:
            by_date[d] = r
    return [sleep_an.night(d, by_date[d]) for d in sorted(by_date)]


async def get_sleep_analysis(
    period: PeriodArg = None,
    start_date: OptDate = None,
    end_date: OptDate = None,
    tz: Tz = None,
    detail: DetailArg = "summary",
    ctx: Context | None = None,
) -> Result:
    """Sleep over a window (default last_7d, by wake-up date): average stages and score, bedtime and wake-time consistency, and sleep debt against sleep need."""
    el = Elicitor(ctx, "get_sleep_analysis", locals_args(locals()))
    notes: list[str] = []
    w = await window_or_ask(el, notes, period, start_date, end_date, tz, "last_7d")
    if isinstance(w, mt.InputRequiredResult):
        return w
    series = await blocking(partial(fetch_series, source(), {"sleep"}, w.start, w.end))
    nights = _sleep_nights(series["sleep"][0], w)
    agg = sleep_an.analyse(nights)
    if not agg.pop("need_known") and nights:
        notes.append(f"Garmin sent no sleep need; assumed {sleep_an.DEFAULT_NEED_H:g} h a night.")
    if agg["nights"]:
        summary = (
            f"{agg['nights']} nights in {w.start}..{w.end}: average {agg['avg_total_h']:g} h"
            + (f", score {agg['avg_score']:g}" if agg["avg_score"] is not None else "")
            + (f", bedtime ~{agg['avg_bedtime']}" if agg["avg_bedtime"] else "")
            + (
                f" (+-{agg['bedtime_spread_min']:g} min)"
                if agg["bedtime_spread_min"] is not None
                else ""
            )
            + f", sleep debt {agg['sleep_debt_h']:g} h."
        )
    else:
        summary = f"No sleep recorded in {w.start}..{w.end}."
    out = SleepAnalysis(
        window=w, daily=nights if detail != "summary" else None, summary=summary, notes=notes, **agg
    )
    return result(out)


async def get_recovery_status(
    date: OptDate = None, tz: Tz = None, ctx: Context | None = None
) -> Result:
    """Readiness estimate for a day (default today): HRV, last night's sleep and Body Battery combined into one 0-100 score with an explanation. Our own transparent heuristic; Garmin's Personal API has no Training Readiness."""
    el = Elicitor(ctx, "get_recovery_status", locals_args(locals()))
    notes: list[str] = []
    w = await window_or_ask(el, notes, None, date, date, tz, "today")
    if isinstance(w, mt.InputRequiredResult):
        return w
    d = w.end
    src = source()
    hrv, sleep, bb = await blocking(
        partial(
            parallel,
            [partial(src.hrv, d), partial(src.sleep, d), partial(src.body_battery_range, d, d)],
        )
    )
    bb_row = bb[0] if isinstance(bb, list) and bb else bb
    comps = [
        rec.hrv_component(no_pii(hrv)),
        rec.sleep_component(no_pii(sleep)),
        rec.body_battery_component(no_pii(bb_row)),
    ]
    score, level = rec.combine(comps)
    notes.append(
        "Estimate from HRV, sleep and Body Battery (weights 35/35/30); not Garmin's Training "
        "Readiness, which the Personal API does not expose."
    )
    if score is None:
        summary = f"Not enough data for {d} to estimate recovery."
    else:
        summary = f"Recovery on {d}: {score:g}/100 ({level}). " + " ".join(
            c.explanation for c in comps if c.score is not None
        )
    out = RecoveryStatus(
        date=d,
        timezone=w.timezone,
        score=score,
        level=level,
        components=comps,
        summary=summary,
        notes=notes,
    )
    return result(out)


def _garmin_goal(metric: str, rows: list[Any]) -> float | None:
    paths = (
        ("values.stepGoal", "stepGoal", "dailyStepGoal")
        if metric == "steps"
        else ("intensityMinutes.goal", "intensityMinutesGoal", "intensityMinutes.weeklyGoal")
    )
    goals = [g for r in rows if (g := dig(r, *paths))]
    return goals[-1] if goals else None


async def get_goal_streaks(
    metric: Literal["steps", "intensity_minutes"] = "steps",
    period: PeriodArg = None,
    start_date: OptDate = None,
    end_date: OptDate = None,
    tz: Tz = None,
    goal: Annotated[
        float | None,
        Field(gt=0, le=1_000_000, description="Target (steps per day, or minutes per week)"),
    ] = None,
    detail: DetailArg = "summary",
    ctx: Context | None = None,
) -> Result:
    """Goal hits and streaks over a window (default last_30d): days the step goal was met, or weeks the intensity-minutes goal was met, plus the current and longest streak. Uses Garmin's own goal unless `goal` is given."""
    el = Elicitor(ctx, "get_goal_streaks", locals_args(locals()))
    notes: list[str] = []
    w = await window_or_ask(el, notes, period, start_date, end_date, tz, "last_30d")
    if isinstance(w, mt.InputRequiredResult):
        return w
    series = await _fetch(source(), [metric], w.start, w.end)
    rows = series[METRICS[metric].series][0]
    source_: Literal["argument", "garmin", "elicited", "default"]
    target = goal
    source_ = "argument"
    if target is None and (g := _garmin_goal(metric, rows)) is not None:
        target, source_ = g, "garmin"
    if target is None:
        unit = "steps a day" if metric == "steps" else "intensity minutes a week"
        ans: Answer | mt.InputRequiredResult = await el.ask(
            "goal",
            f"Garmin has no {metric.replace('_', ' ')} goal on record. What is your goal ({unit})?",
            {
                "type": "object",
                "properties": {"goal": {"type": "number", "title": f"Goal ({unit})", "minimum": 1}},
                "required": ["goal"],
            },
        )
        if isinstance(ans, mt.InputRequiredResult):
            return ans
        picked = (ans.value or {}).get("goal") if ans.accepted else None
        if isinstance(picked, (int, float)) and picked > 0:
            target, source_ = float(picked), "elicited"
        else:
            target, source_ = DEFAULT_GOALS[metric], "default"
            notes.append(f"No goal given; assumed {target:g} {unit}.")
    values = daily_values(metric, _dated(rows))
    dates = window_dates(w)
    now = _today(w)
    if metric == "steps":
        keys, per, unit_k = dates, values, "day"
        open_key = now if now in dates else None
    else:
        keys, per = weekly_totals(values, dates)
        unit_k = "week"
        this_monday = (
            dt.date.fromisoformat(now) - dt.timedelta(days=dt.date.fromisoformat(now).weekday())
        ).isoformat()
        open_key = this_monday if this_monday in keys else None
        if keys and keys[0] < w.start:
            notes.append("The first week is only partly inside the window.")
    hit, with_data, current, longest, daily = streaks(per, keys, target, open_key)
    word = "days" if unit_k == "day" else "weeks"
    summary = (
        f"Goal {target:g}: met on {hit} of {with_data} {word} with data in {w.start}..{w.end}; "
        f"current streak {current}, longest {longest} {word}."
    )
    out = GoalStreaks(
        metric=metric,
        unit=unit_k,  # type: ignore[arg-type]
        window=w,
        goal=target,
        goal_source=source_,
        periods_hit=hit,
        periods_with_data=with_data,
        hit_rate=round(hit / with_data, 3) if with_data else None,
        current_streak=current,
        longest_streak=longest,
        daily=daily if detail != "summary" else None,
        summary=summary,
        notes=notes,
    )
    return result(out)


def locals_args(values: dict[str, Any]) -> dict[str, Any]:
    """A tool's own arguments (from ``locals()`` at the top of the body), minus the context."""
    return {k: v for k, v in values.items() if k != "ctx" and not k.startswith("_")}


# Output schema per tool (the functions return ToolResult / InputRequiredResult at runtime).
OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "get_wellness_overview": WellnessOverview,
    "get_trends": TrendsResult,
    "compare_periods": PeriodComparison,
    "get_activity_summary": ActivityReport,
    "get_sleep_analysis": SleepAnalysis,
    "get_recovery_status": RecoveryStatus,
    "get_goal_streaks": GoalStreaks,
}

TOOLS = (
    get_wellness_overview,
    get_trends,
    compare_periods,
    get_activity_summary,
    get_sleep_analysis,
    get_recovery_status,
    get_goal_streaks,
)
