"""Fetch daily series from Garmin: split into Garmin-sized chunks, run them in parallel, merge.

Shared by ``query_stats`` and the analytics tools. Nothing is cached: every call goes to Garmin.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial
from typing import Any

from ..sdk import PersonalApi
from ._context import chunks, parallel
from ._sanitize import has_data
from ._series import SPECS, row_date, split_response

Rows = list[Any]


def fetcher(src: PersonalApi, metric: str) -> Callable[[str, str], Any]:
    return {
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


def call_count(metrics: Iterable[str], start: str, end: str) -> int:
    """How many Garmin requests :func:`fetch_series` would make."""
    return sum(len(chunks(start, end, SPECS[m].chunk_days)) for m in set(metrics))


def fetch_series(
    src: PersonalApi, metrics: Iterable[str], start: str, end: str
) -> dict[str, tuple[Rows, Rows]]:
    """{metric: (rows dated inside [start, end] or undated, out-of-window records)}."""
    plan = [
        (m, cs, ce)
        for m in sorted(set(metrics))
        for cs, ce in chunks(start, end, SPECS[m].chunk_days)
    ]
    results = parallel([partial(fetcher(src, m), cs, ce) for m, cs, ce in plan])
    out: dict[str, tuple[Rows, Rows]] = {m: ([], []) for m, _, _ in plan}
    for (m, cs, ce), res in zip(plan, results, strict=True):
        rows, outside = out[m]
        chunk_rows, hints = split_response(SPECS[m], res)
        for r in chunk_rows:
            if not isinstance(r, dict) or not has_data(r, SPECS[m].drop):
                continue  # skeleton record (e.g. a night with no sleep): treat as missing
            d = row_date(r, SPECS[m].drop)
            if d is None or cs <= d <= ce:
                rows.append(r)
            elif not start <= d <= end:  # a neighbouring chunk owns in-window dates
                outside.append(r)
        outside.extend(hints)
    return out
