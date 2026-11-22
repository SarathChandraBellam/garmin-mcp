"""Shared HTTP client and endpoint constants for the Garmin Personal API."""

from __future__ import annotations

import os

import httpx

from .. import __version__

PERSONAL_BASE = os.environ.get(
    "GARMIN_PERSONAL_API_BASE_URL", "https://personal.connectapi.garmin.com"
).rstrip("/")
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = f"garmin-mcp/{__version__} (+personal-api)"

client = httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=False)
