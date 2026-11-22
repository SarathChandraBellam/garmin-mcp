"""Pydantic contracts shared by the SDK, the MCP tools and the auth layer."""

from .activity import ActivitySummary
from .auth import (
    AccessTokenClaims,
    AuthCodeClaims,
    ClientClaims,
    PendingAuthorization,
    RefreshTokenClaims,
)
from .common import READ_ONLY, DateStr, Metric, Note, OptDate
from .wellness import TrainingReadinessProxy

__all__ = [
    "READ_ONLY",
    "AccessTokenClaims",
    "ActivitySummary",
    "AuthCodeClaims",
    "ClientClaims",
    "DateStr",
    "Metric",
    "Note",
    "OptDate",
    "PendingAuthorization",
    "RefreshTokenClaims",
    "TrainingReadinessProxy",
]
