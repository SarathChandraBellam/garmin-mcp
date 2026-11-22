"""Pydantic contracts shared by the SDK and the MCP tools."""

from .activity import ActivitySummary
from .common import READ_ONLY, DateStr, Metric, Note, OptDate, Tz
from .errors import AuthErrorBody
from .stats import ActivityList, StatsResult
from .wellness import TrainingReadinessProxy

__all__ = [
    "READ_ONLY",
    "ActivityList",
    "ActivitySummary",
    "AuthErrorBody",
    "DateStr",
    "Metric",
    "Note",
    "OptDate",
    "StatsResult",
    "TrainingReadinessProxy",
    "Tz",
]
