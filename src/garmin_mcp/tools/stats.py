"""Time-series tool."""

from __future__ import annotations

from typing import Any

from ..contracts import DateStr, Metric, OptDate, StatsResult
from ..contracts.stats import SeriesStatus
from ..sdk import PersonalApi
from ._context import call, check_range, chunks, date_span, source, today
from ._sanitize import compact, has_data, no_pii
from ._series import SPECS, MetricSpec, row_date, split_response


def _fetcher(src: PersonalApi, metric: str) -> Any:
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


def _fetch(spec: MetricSpec, fn: Any, start: str, end: str) -> tuple[list[Any], list[Any]]:
    """Fetch [start, end] in Garmin-sized chunks. Returns (in-window rows, outside records)."""
    rows: list[Any] = []
    outside: list[Any] = []
    for cs, ce in chunks(start, end, spec.chunk_days):
        chunk_rows, hints = split_response(spec, call(fn, cs, ce))
        for r in chunk_rows:
            d = row_date(r)
            if d is None or cs <= d <= ce:
                rows.append(r)
            elif not start <= d <= end:  # a neighbouring chunk owns in-window dates
                outside.append(r)
        outside.extend(hints)
    return rows, outside


def query_stats(
    metric: Metric, start_date: DateStr, end_date: OptDate = None, raw: bool = False
) -> Any:
    """Daily time series for one metric over a date range (start and end inclusive) for trends and comparisons.

    Max 366 days (daily_summaries: 31). Longer windows than Garmin accepts in one call
    (steps/stress 28 days, body_battery/hydration/sleep 31) are fetched in chunks.

    Returns {metric, start_date, end_date, days, status: "ok"|"empty", days_with_data, units,
    notes, data, outside_range}. `data` has one entry per requested date (more if Garmin has
    several records for a day); a date without a record is {"calendarDate", "missing": true};
    today's entry has "partial": true. `outside_range` holds records Garmin added for other
    dates (e.g. the nearest weigh-ins around the window). Rows are compact by default (nested
    event lists and descriptor objects omitted); pass raw=true for Garmin's full records.
    """
    e = end_date or today()
    spec = SPECS[metric]
    check_range(start_date, e, spec.max_days, f"query_stats metric '{metric}'")
    rows, outside = _fetch(spec, _fetcher(source(), metric), start_date, e)

    def shape(r: Any) -> Any:
        r = no_pii(r)
        return r if raw else compact(r, spec.drop)

    by_date: dict[str, list[dict[str, Any]]] = {}
    undated: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict) or not has_data(r):
            continue
        d = row_date(r)
        (by_date.setdefault(d, []) if d else undated).append(shape(r))

    now = today()
    data: list[dict[str, Any]] = []
    for d in date_span(start_date, e):
        flags = {"missing": d not in by_date, **({"partial": True} if d == now else {})}
        for r in by_date.get(d) or [{"calendarDate": d}]:
            data.append({**r, **flags})
    data.extend(undated)

    notes = [spec.note] if spec.note else []
    status: SeriesStatus = "ok" if by_date or undated else "empty"
    if status == "empty":
        notes.append(
            f"Garmin returned no {metric} records for {start_date}..{e}. This usually means "
            "nothing was recorded or logged in that window, not that the metric is unsupported."
            + (" See outside_range for the nearest records." if outside else "")
        )
    return StatsResult(
        metric=metric,
        start_date=start_date,
        end_date=e,
        days=len(date_span(start_date, e)),
        status=status,
        days_with_data=len(by_date),
        units=spec.units,
        notes=notes,
        data=data,
        outside_range=[shape(o) for o in outside],
    ).model_dump()
