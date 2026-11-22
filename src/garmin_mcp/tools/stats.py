"""Time-series tool."""

from __future__ import annotations

from typing import Any

from ..contracts import DateStr, Metric, OptDate
from ._context import call, check_range, source, today
from ._sanitize import no_pii, strip_samples


def query_stats(metric: Metric, start_date: DateStr, end_date: OptDate = None) -> Any:
    """Daily time series for one whitelisted metric over a date range (max 366 days; daily_summaries max 31) for trends and comparisons."""
    e = end_date or today()
    check_range(start_date, e, 31 if metric == "daily_summaries" else 366)
    src = source()
    fn = {
        "steps": src.steps_range,
        "stress": src.stress_range,
        "body_battery": src.body_battery_range,
        "sleep": src.sleep_summaries,
        "hrv": src.hrv_range,
        "weight": src.weight_range,
        "vo2max": src.vo2max_range,
        "hydration": src.hydration_range,
        "daily_summaries": src.daily_summaries,
        "wellness_activities": src.wellness_activities,
    }[metric]
    res = no_pii(call(fn, start_date, e))
    if metric == "body_battery" and isinstance(res, list):
        res = [strip_samples(x) for x in res]
    return res
