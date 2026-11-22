"""Activity tools."""

from __future__ import annotations

from functools import partial
from typing import Annotated, Any

import anyio
import mcp_types as mt
from fastmcp import Context
from pydantic import Field

from ..contracts import ActivityList, ActivitySummary, Note, OptDate, Tz
from ..contracts.common import OptPeriod
from ._context import call, source
from ._elicit import Elicitor, choice_schema
from ._sanitize import no_pii
from ._window import resolve_window

ActivityType = Annotated[
    str | None,
    Field(max_length=40, description="e.g. running, cycling, walking, strength_training"),
]
MAX_CHOICES = 10


def get_activities(
    start_date: OptDate = None,
    end_date: OptDate = None,
    activity_type: ActivityType = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    offset: Annotated[int, Field(ge=0)] = 0,
    raw: bool = False,
    period: OptPeriod = None,
    tz: Tz = None,
) -> Any:
    """List recorded activities newest first with key metrics; optional date window (inclusive, or `period` such as last_7d), type filter and paging.

    Returns {count, activities, note, window}. Only activities that were started and saved on a
    device or app appear here. Intensity minutes in daily summaries are tracked all day and can
    be non-zero on days with no recorded activity, so an empty list is not a date-filter error.
    For totals per type or week, use get_activity_summary.
    """
    window = None
    if period or start_date or end_date:
        window = resolve_window(period, start_date, end_date, tz)
        start_date, end_date = window.start, window.end
    acts = call(source().activities, offset, limit, start_date, end_date, activity_type) or []
    items = no_pii(acts) if raw else [ActivitySummary.from_garmin(a).model_dump() for a in acts]
    note = None
    if not items:
        note = (
            "No recorded activities match. Daily intensity minutes are counted separately and "
            "do not create activities; query_stats wellness_activities is a third, separate list."
        )
    return ActivityList(count=len(items), activities=items, note=note, window=window).model_dump(
        exclude_none=True
    )


def _label(a: ActivitySummary) -> str:
    parts = [a.name or a.type or "Activity", (a.start_local or "")[:16]]
    if a.distance_km:
        parts.append(f"{a.distance_km:g} km")
    if a.duration_min:
        parts.append(f"{a.duration_min:g} min")
    return " - ".join(p for p in parts if p)


async def get_activity(
    activity_id: Annotated[int | None, Field(gt=0)] = None,
    date: OptDate = None,
    activity_type: ActivityType = None,
    tz: Tz = None,
    ctx: Context | None = None,
) -> Any:
    """Full details for one activity (location, coordinates and owner/device ids removed).

    Pass activity_id, or describe it with date and/or activity_type (e.g. "my run yesterday").
    With neither, the most recent activity is used. When several activities match, the user is
    asked which one (if the client supports it); otherwise the newest match is returned and
    the others are listed in `other_matches`.
    """
    src = source()
    note = None
    others: list[dict[str, Any]] = []
    if activity_id is None:
        if date:
            resolve_window(None, date, date, tz)  # validates tz, if any
        limit = MAX_CHOICES if date or activity_type else 1
        found = await anyio.to_thread.run_sync(
            partial(call, src.activities, 0, limit, date, date, activity_type)
        )
        matches = [ActivitySummary.from_garmin(a) for a in (found or []) if isinstance(a, dict)]
        if not matches:
            what = " ".join(
                x for x in (activity_type, "activity", f"on {date}" if date else "") if x
            )
            return Note(note=f"No recorded {what} found.").model_dump()
        chosen = matches[0]
        if len(matches) > 1:
            el = Elicitor(
                ctx,
                "get_activity",
                {"date": date, "activity_type": activity_type, "tz": tz},
            )
            ans = await el.ask(
                "activity",
                f"{len(matches)} activities match. Which one?",
                choice_schema(
                    "activity_id", [(str(m.activity_id), _label(m)) for m in matches], "Activity"
                ),
            )
            if isinstance(ans, mt.InputRequiredResult):
                return ans
            picked = str((ans.value or {}).get("activity_id", "")) if ans.accepted else ""
            chosen = next((m for m in matches if str(m.activity_id) == picked), matches[0])
            if not ans.accepted:
                note = f"{len(matches)} activities matched; showing the newest."
                others = [
                    {"activity_id": m.activity_id, "label": _label(m)}
                    for m in matches
                    if m is not chosen
                ]
        activity_id = chosen.activity_id
    if activity_id is None:
        return Note(note="That activity has no id.").model_dump()
    res = no_pii(await anyio.to_thread.run_sync(partial(call, src.activity, activity_id)))
    if not res:
        return Note(note=f"No activity {activity_id}").model_dump()
    if isinstance(res, dict) and (note or others):
        res = {**res, "note": note, "other_matches": others}
    return res
