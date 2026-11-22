"""Time-series tool."""

from __future__ import annotations

from typing import Any

from fastmcp.exceptions import ToolError

from ..contracts import DateStr, Metric, OptDate, StatsResult, Tz
from ..contracts.stats import SeriesStatus
from ..sdk import PersonalApi
from ._context import call, check_range, chunks, date_span, inclusive_days, shift, source, today
from ._sanitize import compact, has_data, no_pii
from ._series import SPECS, MetricSpec, compact_daily_summary, row_date, split_response

NEAREST_DAYS = 180  # how far around an empty window include_nearest looks
UNCATEGORIZED_FIELDS = ("uncategorizedProportion", "uncategorizedDurationInMillis")


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
            if not isinstance(r, dict) or not has_data(r, spec.drop):
                continue  # skeleton record (e.g. a night with no sleep): treat as missing
            d = row_date(r, spec.drop)
            if d is None or cs <= d <= ce:
                rows.append(r)
            elif not start <= d <= end:  # a neighbouring chunk owns in-window dates
                outside.append(r)
        outside.extend(hints)
    return rows, outside


def _uncategorized(src: PersonalApi, start: str, end: str) -> dict[str, dict[str, Any]]:
    """calendarDate -> uncategorized stress fields, from daily summaries (31-day chunks)."""
    spec = SPECS["daily_summaries"]
    rows, _ = _fetch(spec, src.daily_summaries, start, end)
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        d, stress = row_date(r), r.get("stress")
        if d and isinstance(stress, dict):
            fields = {k: stress[k] for k in UNCATEGORIZED_FIELDS if stress.get(k) is not None}
            if fields:
                out[d] = fields
    return out


def _nearest(spec: MetricSpec, fn: Any, start: str, end: str, now: str) -> list[dict[str, Any]]:
    """ONE wider call around an empty window: the latest record before it, earliest after."""
    lo = shift(start, -NEAREST_DAYS)
    hi = min(shift(end, NEAREST_DAYS), max(now, end))
    if inclusive_days(lo, hi) > spec.chunk_days:  # stay a single Garmin call
        hi = shift(lo, spec.chunk_days - 1)
    rows, hints = split_response(spec, call(fn, lo, hi))
    dated = [
        (d, r)
        for r in rows + hints
        if isinstance(r, dict) and has_data(r, spec.drop) and (d := row_date(r, spec.drop))
    ]
    before = max((x for x in dated if x[0] < start), default=None, key=lambda x: x[0])
    after = min((x for x in dated if x[0] > end), default=None, key=lambda x: x[0])
    return [
        {"calendarDate": d, "nearest": side, **r}
        for side, found in (("before", before), ("after", after))
        if found
        for d, r in [found]
    ]


def query_stats(
    metric: Metric,
    start_date: DateStr,
    end_date: OptDate = None,
    raw: bool = False,
    include_uncategorized: bool = False,
    include_nearest: bool = False,
    tz: Tz = None,
) -> Any:
    """Daily time series for one metric over a date range (start and end inclusive) for trends and comparisons.

    Max 366 days (daily_summaries: 31). Longer windows than Garmin accepts in one call
    (steps/stress 28 days, body_battery/hydration/sleep 31) are fetched in chunks.

    Returns {metric, start_date, end_date, days, status, days_with_data, units, notes, data,
    outside_range}. `data` has one entry per requested date (more if Garmin has several records
    for a day); a date without a record is {"calendarDate", "missing": true}; today's entry
    (in `tz`) has "partial": true. status is "ok" (records found), "empty" (none in the window)
    or "unknown" (none, and for hydration/vo2max Garmin answers the same whether nothing was
    logged or the metric is unsupported). Rows are compact by default; raw=true returns
    Garmin's full records.

    include_uncategorized (stress only): also fetch daily summaries and merge
    uncategorizedProportion / uncategorizedDurationInMillis into each row's values.
    include_nearest (vo2max, weight, hrv): if the window is empty, make one extra call up to
    180 days around it and put the latest earlier and earliest later record in outside_range.
    """
    spec = SPECS[metric]
    if include_uncategorized and metric != "stress":
        raise ToolError("include_uncategorized: only applies to metric 'stress'")
    if include_nearest and not spec.nearest:
        names = ", ".join(m for m, s in SPECS.items() if s.nearest)
        raise ToolError(f"include_nearest: only supported for {names}")
    now = today(tz)
    e = end_date or now
    check_range(start_date, e, spec.max_days, f"query_stats metric '{metric}'")
    src = source()
    rows, outside = _fetch(spec, _fetcher(src, metric), start_date, e)

    def shape(r: Any) -> Any:
        r = no_pii(r)
        if raw:
            return r
        if metric == "daily_summaries" and isinstance(r, dict):
            return compact_daily_summary(r)
        return compact(r, spec.drop)

    by_date: dict[str, list[dict[str, Any]]] = {}
    undated: list[dict[str, Any]] = []
    for r in rows:
        d = row_date(r, spec.drop)
        if d is None:
            undated.append(shape(r))
            continue
        # Every dated row carries calendarDate, like the padded rows (body_battery uses
        # "date", weight "summaryDate", vo2max nests it under "generic").
        if r.get("date") == d:
            r = {k: v for k, v in r.items() if k != "date"}
        by_date.setdefault(d, []).append({"calendarDate": d, **shape(r)})

    merge_uncategorized = include_uncategorized and bool(by_date)
    notes = [spec.note] if spec.note and not merge_uncategorized else []
    if merge_uncategorized:
        extra = _uncategorized(src, start_date, e)
        for d, day_rows in by_date.items():
            for r in day_rows:
                target = r["values"] if isinstance(r.get("values"), dict) else r
                target.update(extra.get(d, {}))
        notes.append(
            "uncategorizedProportion (0-1) and uncategorizedDurationInMillis were merged in "
            "from daily summaries; days without a daily summary have neither."
        )

    data: list[dict[str, Any]] = []
    for d in date_span(start_date, e):
        flags = {"missing": d not in by_date, **({"partial": True} if d == now else {})}
        for r in by_date.get(d) or [{"calendarDate": d}]:
            data.append({**r, **flags})
    data.extend(undated)

    found = bool(by_date or undated)
    if not found and include_nearest:
        seen = {row_date(o, spec.drop) for o in outside}
        outside += [
            n
            for n in _nearest(spec, _fetcher(src, metric), start_date, e, now)
            if n["calendarDate"] not in seen
        ]

    status: SeriesStatus = "ok"
    if not found:
        status = "unknown" if spec.ambiguous_empty and not outside else "empty"
    if status == "empty":
        notes.append(
            f"Garmin returned no {metric} records for {start_date}..{e}."
            + (
                " Records exist outside the window (see outside_range), so the metric works "
                "for this account."
                if outside
                else " Nothing was recorded or logged in that window."
            )
        )
    elif status == "unknown":
        notes.append(
            f"Garmin returned no {metric} records for {start_date}..{e}. It gives the same "
            f"empty answer when nothing was logged and when {metric} is not available for this "
            "account or device, so which one applies is unknown."
            + (" Try include_nearest=true to look for older records." if spec.nearest else "")
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
