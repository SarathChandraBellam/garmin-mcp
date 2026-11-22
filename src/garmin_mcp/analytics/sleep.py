"""Sleep analysis: average stages, bedtime / wake-time consistency, sleep debt."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable
from typing import Any

from ..contracts.analytics import SleepNight
from .extract import dig, num

DEFAULT_NEED_H = 8.0
_NOON = 12 * 60
_DAY = 24 * 60


def _clock_minutes(v: Any) -> int | None:
    """Minutes after local midnight. Garmin's *TimestampLocal is local time encoded as UTC ms."""
    if num(v) is not None:
        t = dt.datetime.fromtimestamp(float(v) / 1000, tz=dt.timezone.utc)
    elif isinstance(v, str) and len(v) >= 16:
        try:
            t = dt.datetime.fromisoformat(v.replace("Z", ""))
        except ValueError:
            return None
    else:
        return None
    return t.hour * 60 + t.minute


def _hhmm(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    m = round(minutes) % _DAY
    return f"{m // 60:02d}:{m % 60:02d}"


def _h(seconds: float | None) -> float | None:
    return round(seconds / 3600, 2) if seconds is not None else None


def night(date: str, row: Any) -> SleepNight:
    r = row.get("dailySleepDTO", row) if isinstance(row, dict) else {}
    need_min = dig(row, "sleepNeed.actual", "sleepNeed.baseline", "dailySleepDTO.sleepNeed.actual")
    return SleepNight(
        date=date,
        total_h=_h(dig(r, "sleepTimeSeconds")),
        deep_h=_h(dig(r, "deepSleepSeconds")),
        light_h=_h(dig(r, "lightSleepSeconds")),
        rem_h=_h(dig(r, "remSleepSeconds")),
        awake_h=_h(dig(r, "awakeSleepSeconds")),
        score=dig(r, "sleepScores.overall.value", "overallSleepScore.value", "sleepScore"),
        need_h=round(need_min / 60, 2) if need_min is not None else None,
        bedtime=_hhmm(_clock_minutes(r.get("sleepStartTimestampLocal"))),
        wake_time=_hhmm(_clock_minutes(r.get("sleepEndTimestampLocal"))),
    )


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _sd(xs: list[float]) -> float | None:
    m = _mean(xs)
    if m is None or len(xs) < 2:
        return None
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _minutes(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def analyse(nights: Iterable[SleepNight]) -> dict[str, Any]:
    """Aggregate fields for :class:`~garmin_mcp.contracts.analytics.SleepAnalysis`."""
    ns = [n for n in nights if n.total_h]

    def avg(attr: str) -> float | None:
        m = _mean([getattr(n, attr) for n in ns if getattr(n, attr) is not None])
        return round(m, 2) if m is not None else None

    # Bedtimes straddle midnight, so measure them from noon (23:30 and 00:30 are 60 min apart).
    beds = [(b - _NOON) % _DAY for n in ns if (b := _minutes(n.bedtime)) is not None]
    wakes = [float(w) for n in ns if (w := _minutes(n.wake_time)) is not None]
    stages = {k: avg(f"{k}_h") for k in ("deep", "light", "rem", "awake")}
    staged = sum(v for v in stages.values() if v)
    need_known = any(n.need_h for n in ns)
    debt = sum(max(0.0, (n.need_h or DEFAULT_NEED_H) - (n.total_h or 0.0)) for n in ns)
    bed_mean = _mean([float(b) for b in beds])
    bed_sd, wake_sd = _sd([float(b) for b in beds]), _sd(wakes)
    return {
        "nights": len(ns),
        "avg_total_h": avg("total_h"),
        "avg_deep_h": stages["deep"],
        "avg_light_h": stages["light"],
        "avg_rem_h": stages["rem"],
        "avg_awake_h": stages["awake"],
        "stage_pct": (
            {k: round(v / staged * 100, 1) for k, v in stages.items() if v} if staged else {}
        ),
        "avg_score": avg("score"),
        "avg_bedtime": _hhmm(bed_mean + _NOON) if bed_mean is not None else None,
        "avg_wake_time": _hhmm(_mean(wakes)),
        "bedtime_spread_min": round(bed_sd, 1) if bed_sd is not None else None,
        "wake_spread_min": round(wake_sd, 1) if wake_sd is not None else None,
        "avg_need_h": avg("need_h") if need_known else DEFAULT_NEED_H if ns else None,
        "sleep_debt_h": round(debt, 2) if ns else None,
        "need_known": need_known,
    }
