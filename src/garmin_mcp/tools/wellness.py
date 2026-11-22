"""Daily wellness tools: summary, sleep, heart rate, HRV, SpO2, body composition, fitness."""

from __future__ import annotations

from typing import Any

from ..contracts import Note, OptDate, TrainingReadinessProxy
from ._context import call, check_range, shift, source, today
from ._sanitize import no_pii, strip_samples


def _or_note(value: Any, message: str) -> Any:
    return value if value else Note(note=message).model_dump()


def get_daily_summary(date: OptDate = None) -> Any:
    """Daily summary for one day: steps/movement, calories, heart rate, stress, Body Battery, intensity minutes, SpO2, respiration."""
    d = date or today()
    res = call(source().daily_summaries, d, d) or {}
    data = res.get("data") if isinstance(res, dict) else res
    return no_pii(data[0]) if data else Note(note=f"No daily summary for {d}").model_dump()


def get_sleep(date: OptDate = None) -> Any:
    """Sleep for the night ending on `date`: total/deep/light/REM/awake seconds, timings, sleep need."""
    d = date or today()
    return _or_note(no_pii(call(source().sleep, d)), f"No sleep data for {d}")


def get_heart_rate(date: OptDate = None, include_samples: bool = False) -> Any:
    """Heart rate for a day: resting, min, max, 7-day resting average. Per-minute samples omitted unless include_samples."""
    d = date or today()
    data = strip_samples(no_pii(call(source().heart_rate, d)), include_samples)
    return _or_note(data, f"No heart-rate data for {d}")


def get_hrv(date: OptDate = None) -> Any:
    """Overnight heart-rate variability summary for a day."""
    d = date or today()
    return _or_note(
        no_pii(call(source().hrv, d)), f"No HRV data for {d} (device may not record HRV)"
    )


def get_body_composition(start_date: OptDate = None, end_date: OptDate = None) -> Any:
    """Weight / body-composition measurements in a range (default last 30 days)."""
    e = end_date or today()
    s = start_date or shift(e, -30)
    check_range(s, e)
    return no_pii(call(source().weight_range, s, e))


def get_spo2(date: OptDate = None) -> Any:
    """Pulse-ox (SpO2) and acclimation for a day."""
    d = date or today()
    return _or_note(strip_samples(no_pii(call(source().spo2, d))), f"No SpO2 data for {d}")


def get_fitness_age(date: OptDate = None) -> Any:
    """Fitness age and its components."""
    return no_pii(call(source().fitness_age, date or today()))


def get_heart_rate_zones() -> Any:
    """Configured heart-rate zones."""
    return no_pii(call(source().hr_zones))


def get_training_readiness(date: OptDate = None) -> Any:
    """Training readiness. Not exposed by the Garmin Personal API; returns HRV, sleep and Body Battery for the day as proxies."""
    d = date or today()
    src = source()
    bb = call(src.body_battery_range, d, d)
    return TrainingReadinessProxy(
        date=d,
        hrv=no_pii(call(src.hrv, d)),
        sleep=no_pii(call(src.sleep, d)),
        body_battery=strip_samples(no_pii(bb[0])) if isinstance(bb, list) and bb else bb,
    ).model_dump()


TOOLS = (
    get_daily_summary,
    get_sleep,
    get_heart_rate,
    get_hrv,
    get_body_composition,
    get_spo2,
    get_fitness_age,
    get_heart_rate_zones,
    get_training_readiness,
)
