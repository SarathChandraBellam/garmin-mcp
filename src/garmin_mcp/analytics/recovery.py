"""A transparent readiness estimate from HRV, sleep and Body Battery.

Garmin's Personal API does not expose Training Readiness, so this is our own heuristic: each
available input is scored 0-100 and the scores are averaged with fixed weights (renormalised
over the inputs that exist). It is not Garmin's number and says so in every response.
"""

from __future__ import annotations

from typing import Any

from ..contracts.analytics import ReadinessLevel, RecoveryComponent
from .extract import body_battery_high, dig
from .sleep import DEFAULT_NEED_H

WEIGHTS = {"hrv": 0.35, "sleep": 0.35, "body_battery": 0.30}
HRV_STATUS_SCORE = {"BALANCED": 85.0, "UNBALANCED": 55.0, "LOW": 35.0, "POOR": 20.0}


def _clamp(x: float) -> float:
    return round(max(0.0, min(100.0, x)), 1)


def hrv_component(summary: Any) -> RecoveryComponent:
    s = (summary or {}).get("hrvSummary", summary) or {}
    status = s.get("status") if isinstance(s.get("status"), str) else None
    last = dig(s, "lastNightAvg")
    weekly = dig(s, "weeklyAvg")
    low = dig(s, "baseline.balancedLow")
    high = dig(s, "baseline.balancedUpper")
    score: float | None = None
    why = "No overnight HRV reading."
    if status and status.upper() in HRV_STATUS_SCORE:
        score = HRV_STATUS_SCORE[status.upper()]
        why = f"HRV status {status.lower()}"
        if last is not None:
            why += f" (last night {last:g} ms"
            why += f", baseline {low:g}-{high:g} ms)" if low and high else ")"
    elif last is not None and weekly:
        score = _clamp(70 + (last - weekly) / weekly * 200)  # +-15% of weekly avg ~ +-30 points
        why = f"Last night {last:g} ms vs 7-day average {weekly:g} ms"
    return RecoveryComponent(
        name="hrv",
        score=score,
        weight=WEIGHTS["hrv"],
        detail={"status": status, "last_night_ms": last, "weekly_avg_ms": weekly},
        explanation=why + ".",
    )


def sleep_component(sleep: Any) -> RecoveryComponent:
    r = (sleep or {}).get("dailySleepDTO", sleep) or {}
    secs = dig(r, "sleepTimeSeconds")
    score_v = dig(r, "sleepScores.overall.value", "overallSleepScore.value", "sleepScore")
    need_min = dig(sleep, "sleepNeed.actual", "sleepNeed.baseline")
    need_h = need_min / 60 if need_min else DEFAULT_NEED_H
    hours = secs / 3600 if secs is not None else None
    score: float | None
    if score_v is not None:
        score, why = _clamp(score_v), f"Sleep score {score_v:g}"
    elif hours is not None:
        score, why = _clamp(hours / need_h * 100), f"Slept {hours:.1f} h of {need_h:.1f} h needed"
    else:
        score, why = None, "No sleep recorded for last night"
    return RecoveryComponent(
        name="sleep",
        score=score,
        weight=WEIGHTS["sleep"],
        detail={"hours": round(hours, 2) if hours is not None else None, "score": score_v},
        explanation=why + ".",
    )


def body_battery_component(row: Any) -> RecoveryComponent:
    high = body_battery_high(row) if row else None
    return RecoveryComponent(
        name="body_battery",
        score=_clamp(high) if high is not None else None,
        weight=WEIGHTS["body_battery"],
        detail={"highest": high, "charged": dig(row, "charged"), "drained": dig(row, "drained")},
        explanation=(
            f"Body Battery peaked at {high:g}." if high is not None else "No Body Battery data."
        ),
    )


def combine(components: list[RecoveryComponent]) -> tuple[float | None, ReadinessLevel | None]:
    scored = [c for c in components if c.score is not None]
    if not scored:
        return None, None
    total_w = sum(c.weight for c in scored)
    score = round(sum((c.score or 0.0) * c.weight for c in scored) / total_w, 1)
    level: ReadinessLevel = "high" if score >= 70 else "moderate" if score >= 45 else "low"
    return score, level
