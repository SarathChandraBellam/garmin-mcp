"""MCP authorization: stateless OAuth 2.1 + PKCE, with Garmin keys sealed inside tokens."""

from .keys import GARMIN_KEY_CLAIM, KEY_HEADER, SCOPE, extract_key
from .provider import GarminOAuthProvider

__all__ = ["GARMIN_KEY_CLAIM", "KEY_HEADER", "SCOPE", "GarminOAuthProvider", "extract_key"]
