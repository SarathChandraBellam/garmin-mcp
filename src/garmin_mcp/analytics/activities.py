"""Activity roll-ups: totals per type or per week, longest and fastest activity."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Literal

from ..contracts.activity import ActivitySummary
from ..contracts.analytics import ActivityGroup

MIN_FASTEST_KM = 1.0  # ignore very short activities when picking the fastest one


def _week(a: ActivitySummary) -> str:
    try:
        d = dt.date.fromisoformat((a.start_local or "")[:10])
    except ValueError:
        return "unknown"
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def _add(g: ActivityGroup, a: ActivitySummary) -> None:
    g.count += 1
    g.distance_km += a.distance_km or 0.0
    g.duration_min += a.duration_min or 0.0
    g.moving_min += a.moving_min or 0.0
    g.elevation_gain_m += a.elevation_gain_m or 0.0
    g.calories += a.calories or 0.0
    for i, secs in enumerate(a.hr_zone_secs[:5]):
        g.hr_zone_min[i] += (secs or 0.0) / 60


def _rounded(g: ActivityGroup) -> ActivityGroup:
    return g.model_copy(
        update={
            "distance_km": round(g.distance_km, 2),
            "duration_min": round(g.duration_min, 1),
            "moving_min": round(g.moving_min, 1),
            "elevation_gain_m": round(g.elevation_gain_m, 1),
            "calories": round(g.calories),
            "hr_zone_min": [round(m, 1) for m in g.hr_zone_min],
        }
    )


def roll_up(
    acts: Sequence[ActivitySummary], group_by: Literal["type", "week"]
) -> tuple[ActivityGroup, list[ActivityGroup], ActivitySummary | None, ActivitySummary | None]:
    """(totals, groups sorted by time spent, longest by duration, fastest by average speed)."""
    totals = ActivityGroup(key="all")
    groups: dict[str, ActivityGroup] = {}
    for a in acts:
        key = (a.type or "unknown") if group_by == "type" else _week(a)
        _add(totals, a)
        _add(groups.setdefault(key, ActivityGroup(key=key)), a)
    ordered = sorted(groups.values(), key=lambda g: (-g.duration_min, g.key))
    if group_by == "week":
        ordered = sorted(groups.values(), key=lambda g: g.key)
    longest = max(acts, key=lambda a: a.duration_min or 0.0, default=None)
    fast = [a for a in acts if (a.distance_km or 0) >= MIN_FASTEST_KM and a.avg_speed_kmh]
    fastest = max(fast, key=lambda a: a.avg_speed_kmh or 0.0, default=None)
    return _rounded(totals), [_rounded(g) for g in ordered], longest, fastest
