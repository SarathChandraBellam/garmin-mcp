"""Activity tools."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..contracts import ActivitySummary, OptDate
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
    """List activities newest first with key metrics; optional date window, type filter and paging."""
    acts = call(source().activities, offset, limit, start_date, end_date, activity_type) or []
    if raw:
        return no_pii(acts)
    return [ActivitySummary.from_garmin(a).model_dump() for a in acts]


def get_activity(activity_id: Annotated[int, Field(gt=0)]) -> Any:
    """Full details for one activity."""
    return no_pii(call(source().activity, activity_id))
