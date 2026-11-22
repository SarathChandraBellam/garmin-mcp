"""Thin, synchronous SDK for the Garmin Connect Personal API."""

from ._http import PERSONAL_BASE, TOKEN_PATH
from .client import GarminSource, PersonalApi
from .errors import GarminApiError, GarminAuthError
from .token import key_fingerprint, personal_token, validate_key_shape

__all__ = [
    "PERSONAL_BASE",
    "TOKEN_PATH",
    "GarminApiError",
    "GarminAuthError",
    "GarminSource",
    "PersonalApi",
    "key_fingerprint",
    "personal_token",
    "validate_key_shape",
]
