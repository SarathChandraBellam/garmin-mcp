"""Errors raised by the Garmin SDK."""

from __future__ import annotations


class GarminAuthError(Exception):
    """The supplied Garmin key is missing, invalid, expired or revoked."""


class GarminApiError(Exception):
    """Garmin could not be reached or returned an unexpected response."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status
