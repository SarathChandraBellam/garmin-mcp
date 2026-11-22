"""Activity tools."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..contracts import ActivityList, ActivitySummary, Note, OptDate
from ._context import call, source
from ._sanitize import no_pii


def get_activities(
    start_date: OptDate = None,
    end_date: OptDate = None,
    activity_type: Annotated[
        str | None,
        Field(max_length=40, description="e.g. running, cycling, walking, strength_training"),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    offset: Annotated[int, Field(ge=0)] = 0,
    raw: bool = False,
) -> Any:
    """List recorded activities newest first with key metrics; optional date window (inclusive), type filter and paging.

    Returns {count, activities, note}. Only activities that were started and saved on a device
    or app appear here. Intensity minutes in daily summaries are tracked all day and can be
    non-zero on days with no recorded activity, so an empty list is not a date-filter error.
    """
    acts = call(source().activities, offset, limit, start_date, end_date, activity_type) or []
    items = no_pii(acts) if raw else [ActivitySummary.from_garmin(a).model_dump() for a in acts]
    note = None
    if not items:
        note = (
            "No recorded activities match. Daily intensity minutes are counted separately and "
            "do not create activities; query_stats wellness_activities is a third, separate list."
        )
    return ActivityList(count=len(items), activities=items, note=note).model_dump(exclude_none=True)


def get_activity(activity_id: Annotated[int, Field(gt=0)]) -> Any:
    """Full details for one activity (location, coordinates and owner/device ids removed)."""
    res = no_pii(call(source().activity, activity_id))
    return res if res else Note(note=f"No activity {activity_id}").model_dump()
