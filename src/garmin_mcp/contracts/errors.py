"""HTTP error bodies returned by the API-key gate."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

AuthErrorCode = Literal[
    "missing_garmin_api_key", "invalid_garmin_api_key", "garmin_unavailable", "https_required"
]


class AuthErrorBody(BaseModel):
    error: AuthErrorCode
    error_description: str | None = None
