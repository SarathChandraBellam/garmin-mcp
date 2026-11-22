"""Daily wellness tools: summary, sleep, heart rate, HRV, SpO2, body composition, fitness."""

from __future__ import annotations

from typing import Any

from ..contracts import Note, OptDate, TrainingReadinessProxy
from ._context import call, check_range, shift, source, today
from ._sanitize import has_data, no_pii, strip_samples
from ._series import SPECS


def _or_note(value: Any, message: str) -> Any:
    """``value`` if it holds any measurement, else a Note (Garmin may send null skeletons)."""
    return value if has_data(value) else Note(note=message).model_dump()


def get_daily_summary(date: OptDate = None) -> Any:
    """Daily summary for one day: steps (movement.steps.value), calories, heart rate, stress, Body Battery, intensity minutes, SpO2, respiration.

    `partial` is true when `date` is today or later (in the server's DEFAULT_TIMEZONE): the day
    is still in progress and totals will grow. Intensity minutes are counted all day and do not
    mean a recorded activity exists; use get_activities for recorded activities.
    """
    d = date or today()
    res = call(source().daily_summaries, d, d) or {}
    data = res.get("data") if isinstance(res, dict) else res
    if not data or not has_data(data[0]):
        return Note(note=f"No daily summary for {d}").model_dump()
    return {**no_pii(data[0]), "partial": d >= today()}


def get_sleep(date: OptDate = None) -> Any:
    """Sleep for the night ending on `date` (the wake-up date): total/deep/light/REM/awake seconds, timings, sleep need.

    *TimestampGMT values are Unix epoch ms; *TimestampLocal values are local wall-clock time
    encoded as epoch ms (read them as UTC to get the local clock time).
    """
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
    return _or_note(no_pii(call(source().hrv, d)), f"No overnight HRV reading recorded for {d}")


def get_body_composition(start_date: OptDate = None, end_date: OptDate = None) -> Any:
    """Weight / body-composition measurements in a range (default the last 31 days, inclusive).

    Weight and mass values are in grams (81200 = 81.2 kg) regardless of the profile's
    measurement system; see the `units` key.
    """
    e = end_date or today()
    s = start_date or shift(e, -30)
    check_range(s, e, what="get_body_composition")
    res = no_pii(call(source().weight_range, s, e))
    if not has_data(res):
        return Note(note=f"No weight or body-composition entries for {s}..{e}").model_dump()
    return {**res, "units": SPECS["weight"].units} if isinstance(res, dict) else res


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


def get_training_readiness(date: OptDate = None, include_samples: bool = False) -> Any:
    """Training readiness. Not exposed by the Garmin Personal API; returns HRV, sleep and Body Battery for the day as proxies. Long sample arrays (e.g. hrv.hrvReadings) omitted unless include_samples."""
    d = date or today()
    src = source()
    bb = call(src.body_battery_range, d, d)
    bb = bb[0] if isinstance(bb, list) and bb else bb
    return TrainingReadinessProxy(
        date=d,
        hrv=strip_samples(no_pii(call(src.hrv, d)), include_samples),
        sleep=strip_samples(no_pii(call(src.sleep, d)), include_samples),
        body_battery=strip_samples(no_pii(bb), include_samples),
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
