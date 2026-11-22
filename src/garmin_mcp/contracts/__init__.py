"""Pydantic contracts shared by the SDK and the MCP tools."""

from .activity import ActivitySummary
from .common import READ_ONLY, DateStr, Metric, Note, OptDate
from .errors import AuthErrorBody
from .wellness import TrainingReadinessProxy

__all__ = [
    "READ_ONLY",
    "ActivitySummary",
    "AuthErrorBody",
    "DateStr",
    "Metric",
    "Note",
    "OptDate",
    "TrainingReadinessProxy",
]
