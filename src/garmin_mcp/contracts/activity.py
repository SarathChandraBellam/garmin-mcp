"""Activity contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


def _round(value: Any, digits: int = 1) -> float | None:
    return round(value, digits) if isinstance(value, (int, float)) else None


def _scaled(value: Any, factor: float, digits: int) -> float | None:
    return _round(value * factor, digits) if isinstance(value, (int, float)) else None


class ActivitySummary(BaseModel):
    """Compact, PII-free view of a Garmin activity."""

    activity_id: int | None = None
    name: str | None = None
    type: str | None = None
    start_local: str | None = None
    start_gmt: str | None = None
    location: str | None = None
    distance_km: float | None = None
    duration_min: float | None = None
    moving_min: float | None = None
    calories: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    avg_speed_kmh: float | None = None
    elevation_gain_m: float | None = None
    steps: int | None = None
    training_effect: str | None = None
    body_battery_change: float | None = None
    hr_zone_secs: list[float | None] = Field(default_factory=list)

    @classmethod
    def from_garmin(cls, a: dict[str, Any]) -> ActivitySummary:
        return cls(
            activity_id=a.get("activityId"),
            name=a.get("activityName"),
            type=(a.get("activityType") or {}).get("typeKey"),
            start_local=a.get("startTimeLocal"),
            start_gmt=a.get("startTimeGMT"),
            location=a.get("locationName"),
            distance_km=_scaled(a.get("distance"), 1 / 1000, 3),
            duration_min=_scaled(a.get("duration"), 1 / 60, 1),
            moving_min=_scaled(a.get("movingDuration"), 1 / 60, 1),
            calories=a.get("calories"),
            avg_hr=a.get("averageHR"),
            max_hr=a.get("maxHR"),
            avg_speed_kmh=_scaled(a.get("averageSpeed"), 3.6, 2),
            elevation_gain_m=a.get("elevationGain"),
            steps=a.get("steps"),
            training_effect=a.get("trainingEffectLabel"),
            body_battery_change=a.get("differenceBodyBattery"),
            hr_zone_secs=[a.get(f"hrTimeInZone_{i}") for i in range(1, 6)],
        )
