"""Which Garmin series each daily metric comes from, and how to read one value from a row.

Garmin's shapes vary between endpoints (and sometimes between accounts), so every reader
tries a short list of known paths and returns ``None`` when none holds a number.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

TrendMetric = Literal[
    "steps",
    "resting_hr",
    "hrv",
    "stress",
    "body_battery",
    "sleep_hours",
    "sleep_score",
    "intensity_minutes",
    "calories",
    "weight_kg",
    "vo2max",
]


def num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def dig(row: Any, *paths: str) -> float | None:
    """First numeric value found at any dotted ``path`` in ``row``."""
    for path in paths:
        cur = row
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        v = num(cur)
        if v is not None:
            return v
    return None


def _sleep_row(row: Any) -> Any:
    return row.get("dailySleepDTO", row) if isinstance(row, dict) else row


def body_battery_high(row: Any) -> float | None:
    """Highest Body Battery level of the day, from the samples or a summary field."""
    levels: list[float] = []
    for sample in (row or {}).get("bodyBatteryValuesArray") or []:
        if isinstance(sample, list) and len(sample) >= 2:
            v = num(sample[1] if len(sample) == 2 else sample[2])
            if v is not None:
                levels.append(v)
    if levels:
        return max(levels)
    return dig(row, "highest", "bodyBatteryHighestValue", "bodyBattery.highest")


def intensity_minutes(row: Any) -> float | None:
    """Moderate + 2 x vigorous minutes (how Garmin counts toward the weekly goal)."""
    mod = dig(row, "intensityMinutes.moderate", "moderateIntensityMinutes")
    vig = dig(row, "intensityMinutes.vigorous", "vigorousIntensityMinutes")
    if mod is None and vig is None:
        return None
    return (mod or 0.0) + 2 * (vig or 0.0)


def _hours(row: Any) -> float | None:
    s = dig(_sleep_row(row), "sleepTimeSeconds")
    return s / 3600 if s is not None else None


def _sleep_score(row: Any) -> float | None:
    r = _sleep_row(row)
    return dig(r, "sleepScores.overall.value", "overallSleepScore.value", "sleepScore")


def _weight_kg(row: Any) -> float | None:
    g = dig(row, "weight", "maxWeight", "minWeight")
    return g / 1000 if g is not None else None


@dataclass(frozen=True)
class MetricDef:
    name: str
    series: str  # a query_stats metric (see tools/_series.SPECS)
    unit: str
    read: Callable[[Any], float | None]
    higher_is_better: bool | None
    cumulative: bool = False  # a running daily total: today's partial value is left out of stats
    label: str = ""


METRICS: dict[str, MetricDef] = {
    m.name: m
    for m in (
        MetricDef(
            "steps",
            "steps",
            "steps",
            lambda r: dig(r, "values.totalSteps", "totalSteps", "movement.steps.value"),
            True,
            cumulative=True,
            label="Steps",
        ),
        MetricDef(
            "resting_hr",
            "daily_summaries",
            "bpm",
            lambda r: dig(r, "heartRate.restingHeartRate", "restingHeartRate", "restingHR"),
            False,
            label="Resting HR",
        ),
        MetricDef(
            "hrv",
            "hrv",
            "ms",
            lambda r: dig(r, "lastNightAvg", "hrvSummary.lastNightAvg"),
            True,
            label="Overnight HRV",
        ),
        MetricDef(
            "stress",
            "stress",
            "0-100",
            lambda r: dig(r, "values.overallStressLevel", "overallStressLevel"),
            False,
            label="Stress",
        ),
        MetricDef(
            "body_battery", "body_battery", "0-100", body_battery_high, True, label="Body Battery"
        ),
        MetricDef("sleep_hours", "sleep", "hours", _hours, True, label="Sleep"),
        MetricDef("sleep_score", "sleep", "0-100", _sleep_score, True, label="Sleep score"),
        MetricDef(
            "intensity_minutes",
            "daily_summaries",
            "minutes",
            intensity_minutes,
            True,
            cumulative=True,
            label="Intensity minutes",
        ),
        MetricDef(
            "calories",
            "daily_summaries",
            "kcal",
            lambda r: dig(r, "calories.totalKilocalories", "totalKilocalories"),
            None,
            cumulative=True,
            label="Calories",
        ),
        MetricDef("weight_kg", "weight", "kg", _weight_kg, None, label="Weight"),
        MetricDef(
            "vo2max",
            "vo2max",
            "ml/kg/min",
            lambda r: dig(
                r,
                "generic.vo2MaxPreciseValue",
                "generic.vo2MaxValue",
                "vo2MaxPreciseValue",
                "vo2MaxValue",
            ),
            True,
            label="VO2 max",
        ),
    )
}

OVERVIEW_METRICS = ("sleep_hours", "resting_hr", "hrv", "stress", "body_battery", "steps")


def daily_values(metric: str, dated_rows: Iterable[tuple[str | None, Any]]) -> dict[str, float]:
    """{date: value} for one metric. When a date has several rows the last reading wins."""
    read = METRICS[metric].read
    out: dict[str, float] = {}
    for d, row in dated_rows:
        if d is None:
            continue
        v = read(row)
        if v is not None:
            out[d] = v
    return out
