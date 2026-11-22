"""Descriptive statistics for one daily series over one window."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence

from ..contracts.analytics import DayValue, MetricStats, Trend
from .extract import METRICS

FLAT_THRESHOLD = 0.03  # a change across the window below 3% of the mean counts as flat


def _r(x: float | None, digits: int = 2) -> float | None:
    return None if x is None or math.isnan(x) else round(x, digits)


def slope(points: Sequence[tuple[float, float]]) -> float | None:
    """Least-squares slope of (x, y) points; None with fewer than two distinct x."""
    n = len(points)
    if n < 2:
        return None
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    den = sum((x - mx) ** 2 for x, _ in points)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in points) / den


def trend_of(slope_per_day: float | None, mean: float | None, days: int) -> Trend | None:
    if slope_per_day is None or mean is None:
        return None
    change = slope_per_day * max(days - 1, 1)
    if mean == 0 or abs(change) < FLAT_THRESHOLD * abs(mean):
        return "flat"
    return "up" if change > 0 else "down"


def pct(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return _r((new - old) / abs(old) * 100, 1)


def summarize(
    metric: str,
    values: dict[str, float],
    dates: Sequence[str],
    today: str | None = None,
    include_daily: bool = False,
) -> MetricStats:
    """Stats over ``dates`` (the window). Today's value is shown but, for running totals such
    as steps, left out of the statistics because the day is not over yet."""
    spec = METRICS[metric]
    used = [
        (i, d, values[d])
        for i, d in enumerate(dates)
        if d in values and not (spec.cumulative and d == today)
    ]
    ys = [v for _, _, v in used]
    stats = MetricStats(metric=metric, unit=spec.unit)
    stats.days_with_data = len(used)
    stats.missing_days = len(dates) - sum(1 for d in dates if d in values)
    if ys:
        mean = sum(ys) / len(ys)
        s = slope([(float(i), v) for i, _, v in used])
        stats.average = _r(mean)
        stats.minimum = _r(min(ys))
        stats.maximum = _r(max(ys))
        stats.total = _r(sum(ys))
        stats.stdev = _r(math.sqrt(sum((y - mean) ** 2 for y in ys) / len(ys)))
        stats.slope_per_day = _r(s, 3)
        stats.trend = trend_of(s, mean, len(dates))
        if spec.higher_is_better is not None:
            hi = max(used, key=lambda t: t[2])
            lo = min(used, key=lambda t: t[2])
            best, worst = (hi, lo) if spec.higher_is_better else (lo, hi)
            stats.best_day = DayValue(date=best[1], value=_r(best[2]))
            stats.worst_day = DayValue(date=worst[1], value=_r(worst[2]))
    if include_daily:
        stats.daily = [DayValue(date=d, value=_r(values.get(d)), partial=d == today) for d in dates]
    return stats


def with_previous(cur: MetricStats, prev: MetricStats) -> MetricStats:
    cur.previous_average = prev.average
    if cur.average is not None and prev.average is not None:
        cur.change = _r(cur.average - prev.average)
        cur.change_pct = pct(cur.average, prev.average)
    return cur


def rollup_weekly(daily: Sequence[DayValue]) -> list[DayValue]:
    """Mean per Monday-based week; ``date`` is the week's Monday."""
    weeks: dict[str, list[float]] = {}
    partial: dict[str, bool] = {}
    for dv in daily:
        d = dt.date.fromisoformat(dv.date)
        monday = (d - dt.timedelta(days=d.weekday())).isoformat()
        weeks.setdefault(monday, [])
        partial[monday] = partial.get(monday, False) or dv.partial
        if dv.value is not None and not dv.partial:
            weeks[monday].append(dv.value)
    return [
        DayValue(date=w, value=_r(sum(v) / len(v)) if v else None, partial=partial[w])
        for w, v in weeks.items()
    ]


def describe(stats: MetricStats) -> str:
    """One short sentence, e.g. 'Steps averaged 8,120 steps (+6.2% vs previous), trending up'."""
    spec = METRICS[stats.metric]
    if stats.average is None:
        return f"{spec.label}: no data"
    avg = f"{stats.average:,.0f}" if abs(stats.average) >= 100 else f"{stats.average:g}"
    text = f"{spec.label} averaged {avg} {spec.unit}"
    if stats.change_pct is not None:
        text += f" ({stats.change_pct:+.1f}% vs previous)"
    if stats.trend and stats.trend != "flat":
        text += f", trending {stats.trend}"
    return text
