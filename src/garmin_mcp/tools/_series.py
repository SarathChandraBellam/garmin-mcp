"""Per-metric facts for ``query_stats``: Garmin range caps, row shapes, units, compaction.

Garmin caps were measured live against the Personal API (largest inclusive window it
accepted): steps/stress 28 days, body_battery/hydration 31, sleep 32, the rest 366.
``chunk_days`` stays at or below those, so longer windows are fetched in several calls.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

# Conventions shared by every Garmin payload (see README "Units and timestamps").
TIMESTAMP_UNITS = {
    "*TimestampGMT / *TimeGMT": "true UTC (Unix epoch ms when numeric)",
    "*TimestampLocal / *TimeLocal": (
        "local wall-clock time encoded as if it were UTC (shifted epoch ms when numeric); "
        "do not convert it with a time zone"
    ),
}


@dataclass(frozen=True)
class MetricSpec:
    chunk_days: int  # largest window sent to Garmin in one call (inclusive days)
    max_days: int = 366  # largest window query_stats accepts (inclusive days)
    rows_key: str | None = None  # where the daily list lives when Garmin wraps it in an object
    hint_keys: tuple[str, ...] = ()  # out-of-window neighbours Garmin adds (kept as hints)
    drop: frozenset[str] = frozenset()  # heavy keys removed from the compact view
    units: dict[str, str] = field(default_factory=dict)
    note: str | None = None
    # Garmin answers identically for "nothing logged" and "not supported for this account".
    ambiguous_empty: bool = False
    # Sparse metrics where include_nearest may look outside an empty window (one extra call).
    nearest: bool = False


SPECS: dict[str, MetricSpec] = {
    "steps": MetricSpec(
        chunk_days=28,
        units={"totalSteps": "steps", "stepGoal": "steps", "totalDistance": "meters"},
    ),
    "stress": MetricSpec(
        chunk_days=28,
        units={
            "*StressDuration": "seconds",
            "overallStressLevel": "0-100 score",
        },
        note=(
            "This series has no 'uncategorized' bucket (time Garmin could not score, often a "
            "large share of the day), so averages can be skewed. Pass "
            "include_uncategorized=true to merge it in from daily summaries."
        ),
    ),
    "body_battery": MetricSpec(
        chunk_days=31,
        drop=frozenset(
            {"bodyBatteryDynamicFeedbackEvent", "endOfDayBodyBatteryDynamicFeedbackEvent"}
        ),
        units={"charged / drained / *BodyBattery": "0-100 Body Battery points"},
    ),
    "sleep": MetricSpec(
        chunk_days=31,
        drop=frozenset({"sleepNeed", "nextSleepNeed"}),
        units={"*Seconds": "seconds", **TIMESTAMP_UNITS},
        note="calendarDate is the local date you woke up, not the date you fell asleep.",
    ),
    "hrv": MetricSpec(
        chunk_days=366,
        rows_key="hrvSummaries",
        nearest=True,
        units={"weeklyAvg / lastNightAvg / lastNight5MinHigh / baseline": "milliseconds"},
    ),
    "weight": MetricSpec(
        chunk_days=366,
        rows_key="dailyWeightSummaries",
        hint_keys=("previousDateWeight", "nextDateWeight"),
        nearest=True,
        units={
            "weight / minWeight / maxWeight / boneMass / muscleMass": "grams",
            "bmi": "kg/m^2",
            "bodyFat / bodyWater": "percent",
            **TIMESTAMP_UNITS,
        },
    ),
    "vo2max": MetricSpec(
        chunk_days=366,
        units={"vo2MaxValue / vo2MaxPreciseValue": "ml/kg/min"},
        ambiguous_empty=True,
        nearest=True,
        note="VO2 max is only updated after qualifying activities, so most days are missing.",
    ),
    "hydration": MetricSpec(
        chunk_days=31,
        units={"*InML / value": "milliliters"},
        ambiguous_empty=True,
        note="Hydration only exists for days where intake was logged in Garmin Connect.",
    ),
    "daily_summaries": MetricSpec(
        chunk_days=31,
        rows_key="data",
        units={
            "*InMillis": "milliseconds",
            "*Distance / distance values": "meters",
            "intensityMinutes": "minutes",
            "*Proportion": "fraction 0-1",
            "wellnessChronology timestamps": "ISO-8601 local / GMT strings without offset",
        },
        note=(
            "Steps are under movement.steps.value. Intensity minutes are tracked all day and "
            "do not imply a recorded activity (see get_activities)."
        ),
    ),
    "wellness_activities": MetricSpec(chunk_days=366),
}

_DATE_KEYS = ("calendarDate", "summaryDate", "date")
_DATETIME_KEYS = ("startTimeLocal", "startTimestampLocal", "startLocal")


def _as_date(v: Any) -> str | None:
    if isinstance(v, str) and len(v) >= 10:
        try:
            return dt.date.fromisoformat(v[:10]).isoformat()
        except ValueError:
            return None
    return None


def row_date(row: Any, skip: frozenset[str] = frozenset()) -> str | None:
    """The local calendar date a Garmin daily record belongs to, if it can be found.

    Nested objects named in ``skip`` (descriptors such as ``sleepNeed``) are not searched:
    their dates describe something else, not the record.
    """
    if not isinstance(row, dict):
        return None
    for k in _DATE_KEYS + _DATETIME_KEYS:
        d = _as_date(row.get(k))
        if d:
            return d
    for key, nested in row.items():  # e.g. vo2max rows: {"generic": {"calendarDate": ...}}
        if isinstance(nested, dict) and key not in skip:
            d = next((_as_date(nested.get(k)) for k in _DATE_KEYS if nested.get(k)), None)
            if d:
                return d
    return None


# daily_summaries compact view: section -> how many object levels to keep. Each keeps only
# its scalar fields; movement also keeps the scalars of its sub-objects (movement.steps.value,
# .goal, distance). Everything else in the record (chronology, event lists, feedback
# descriptors, SpO2/respiration detail) is dropped.
SUMMARY_SECTIONS = {
    "bodyBattery": 0,
    "stress": 0,
    "heartRate": 0,
    "movement": 1,
    "calories": 0,
    "intensityMinutes": 0,
}


def _scalars(obj: dict[str, Any], depth: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if isinstance(v, dict) and depth > 0:
            inner = _scalars(v, depth - 1)
            if inner:
                out[k] = inner
        elif not isinstance(v, (dict, list)):
            out[k] = v
    return out


def compact_daily_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Top-level scalars plus scalar summaries of the main sections of one daily summary."""
    out = {k: v for k, v in row.items() if not isinstance(v, (dict, list))}
    for k, depth in SUMMARY_SECTIONS.items():
        v = row.get(k)
        if isinstance(v, dict):
            out[k] = _scalars(v, depth)
        elif v is not None and not isinstance(v, list):
            out[k] = v
    return out


def split_response(spec: MetricSpec, res: Any) -> tuple[list[Any], list[Any]]:
    """(daily rows, out-of-window hint records) from one Garmin response."""
    if res is None:
        return [], []
    if isinstance(res, list):
        return res, []
    if isinstance(res, dict):
        rows = res.get(spec.rows_key) if spec.rows_key else None
        hints = [res[k] for k in spec.hint_keys if res.get(k)]
        return (rows if isinstance(rows, list) else []), hints
    return [], []
