"""API-key auth: each caller sends their own Garmin Personal API key on every request."""

from .keys import CREATE_KEY_URL, KEY_HEADER, extract_key
from .middleware import GarminKeyGate, HttpsOnlyMiddleware

__all__ = ["CREATE_KEY_URL", "KEY_HEADER", "GarminKeyGate", "HttpsOnlyMiddleware", "extract_key"]
