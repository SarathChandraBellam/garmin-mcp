"""Goal streaks: days (or weeks) a goal was met, and the current / longest run."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from ..contracts.analytics import DayValue

DEFAULT_GOALS = {"steps": 10_000.0, "intensity_minutes": 150.0}  # steps/day, minutes/week


def weekly_totals(values: dict[str, float], dates: Sequence[str]) -> tuple[list[str], dict]:
    """Sum daily values per Monday-based week -> (week keys in order, {week: total})."""
    totals: dict[str, float] = {}
    order: list[str] = []
    for d in dates:
        day = dt.date.fromisoformat(d)
        w = (day - dt.timedelta(days=day.weekday())).isoformat()
        if w not in totals:
            totals[w] = 0.0
            order.append(w)
        totals[w] += values.get(d, 0.0)
    seen = {
        (
            dt.date.fromisoformat(d) - dt.timedelta(days=dt.date.fromisoformat(d).weekday())
        ).isoformat()
        for d in values
    }
    return order, {w: t for w, t in totals.items() if w in seen}


def streaks(
    values: dict[str, float], keys: Sequence[str], goal: float, open_key: str | None = None
) -> tuple[int, int, int, int, list[DayValue]]:
    """(periods hit, periods with data, current streak, longest streak, per-period values).

    ``open_key`` is the period still in progress (today, or this week). If its goal is not met
    yet it does not break the current streak, since there is still time to meet it.
    """
    hit = with_data = longest = run = 0
    rows: list[DayValue] = []
    for k in keys:
        v = values.get(k)
        rows.append(
            DayValue(date=k, value=round(v, 1) if v is not None else None, partial=k == open_key)
        )
        if v is None:
            if k != open_key:
                run = 0
            continue
        with_data += 1
        if v >= goal:
            hit += 1
            run += 1
            longest = max(longest, run)
        elif k != open_key:
            run = 0
    # current streak: walk back from the end, skipping an unfinished open period
    current = 0
    for k in reversed(keys):
        v = values.get(k)
        if k == open_key and (v is None or v < goal):
            continue
        if v is not None and v >= goal:
            current += 1
        else:
            break
    return hit, with_data, current, longest, rows
