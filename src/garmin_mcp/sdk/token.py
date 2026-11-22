"""Exchange a Garmin Personal API key for a short-lived bearer token.

The token is cached in memory only (per warm instance, keyed by SHA-256 of the key) and
dies with the process. Nothing is written to disk.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time

import httpx

from . import _http
from .errors import GarminApiError, GarminAuthError

MAX_KEY_LEN = 4096
REUSE_MARGIN_SECONDS = 3600  # reuse while >1h left (Garmin's own client rule)


def _jwt_exp(token: str) -> float:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return float(json.loads(base64.urlsafe_b64decode(part)).get("exp", 0))
    except Exception:
        return 0.0


class TokenCache:
    """In-memory only. Maps sha256(api_key) -> (bearer token, expiry)."""

    def __init__(self, max_entries: int = 256):
        self._d: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._max = max_entries

    def get(self, k: str) -> str | None:
        with self._lock:
            v = self._d.get(k)
            if v and v[1] - time.time() > REUSE_MARGIN_SECONDS:
                return v[0]
            self._d.pop(k, None)
            return None

    def put(self, k: str, token: str, exp: float) -> None:
        with self._lock:
            if len(self._d) >= self._max:
                self._d.pop(next(iter(self._d)))
            self._d[k] = (token, exp)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

    def drop(self, k: str) -> None:
        with self._lock:
            self._d.pop(k, None)


cache = TokenCache()


def key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def validate_key_shape(api_key: str | None) -> str:
    api_key = (api_key or "").strip()
    if not api_key or len(api_key) > MAX_KEY_LEN or any(c in api_key for c in "\r\n"):
        raise GarminAuthError("Missing or malformed Garmin Personal API key")
    return api_key


def personal_token(api_key: str, force: bool = False) -> str:
    """Exchange a Personal API key for a bearer token (cached in memory)."""
    api_key = validate_key_shape(api_key)
    fp = key_fingerprint(api_key)
    if not force and (tok := cache.get(fp)):
        return tok
    try:
        r = _http.client.post(
            _http.PERSONAL_BASE + _http.TOKEN_PATH,
            headers={"Authorization": f"ApiKey {api_key}", "Accept": "*/*"},
        )
    except httpx.HTTPError as e:
        raise GarminApiError(
            f"Could not reach Garmin token endpoint ({type(e).__name__})"
        ) from None
    if r.status_code in (400, 401, 403, 404):
        raise GarminAuthError("Garmin rejected the Personal API key (invalid, expired or revoked)")
    if r.status_code == 429:
        raise GarminApiError("Garmin rate limit on token endpoint (HTTP 429)", 429)
    if not r.is_success:
        raise GarminApiError(f"Garmin token endpoint returned HTTP {r.status_code}", r.status_code)
    token = r.text.strip().strip('"')  # body is the raw JWT, not JSON
    if token.count(".") != 2:
        raise GarminApiError("Unexpected token response from Garmin")
    cache.put(fp, token, _jwt_exp(token) or time.time() + 6 * 3600)
    return token
