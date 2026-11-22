"""Where a caller's Garmin key can come from on an HTTP request."""

from __future__ import annotations

from collections.abc import Mapping

KEY_HEADER = "x-garmin-api-key"
CREATE_KEY_URL = "https://connect.garmin.com/app/settings/personalApiToken"


def extract_key(headers: Mapping[str, str]) -> str | None:
    """Return the key from ``X-Garmin-Api-Key`` or ``Authorization: Bearer``, if present."""
    h = {k.lower(): v for k, v in headers.items()}
    if h.get(KEY_HEADER, "").strip():
        return h[KEY_HEADER].strip()
    auth = h.get("authorization", "")
    if auth[:7].lower() == "bearer " and auth[7:].strip():
        return auth[7:].strip()
    return None
