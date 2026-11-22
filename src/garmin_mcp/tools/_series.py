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
            "large share of the day), so averages can be skewed; daily_summaries[].stress has "
            "uncategorizedProportion / uncategorizedDurationInMillis."
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
        units={"weeklyAvg / lastNightAvg / lastNight5MinHigh / baseline": "milliseconds"},
    ),
    "weight": MetricSpec(
        chunk_days=366,
        rows_key="dailyWeightSummaries",
        hint_keys=("previousDateWeight", "nextDateWeight"),
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
        note="VO2 max is only updated after qualifying activities, so most days are missing.",
    ),
    "hydration": MetricSpec(
        chunk_days=31,
        units={"*InML / value": "milliliters"},
        note="Hydration only exists for days where intake was logged in Garmin Connect.",
    ),
    "daily_summaries": MetricSpec(
        chunk_days=31,
        max_days=31,
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


def row_date(row: Any) -> str | None:
    """The local calendar date a Garmin daily record belongs to, if it can be found."""
    if not isinstance(row, dict):
        return None
    for k in _DATE_KEYS + _DATETIME_KEYS:
        d = _as_date(row.get(k))
        if d:
            return d
    for nested in row.values():  # e.g. vo2max rows: {"generic": {"calendarDate": ...}}
        if isinstance(nested, dict):
            d = next((_as_date(nested.get(k)) for k in _DATE_KEYS if nested.get(k)), None)
            if d:
                return d
    return None


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
