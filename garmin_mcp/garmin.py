"""Garmin data sources.

Primary: the official Garmin Connect *Personal API* (personal.connectapi.garmin.com).
Each caller supplies their own Personal API key; it is exchanged for a ~24h bearer token
which is cached in memory only (per warm instance, keyed by SHA-256 of the key).
Nothing is written to disk or a database; responses are returned and discarded.

`GarminSource` is the swap point: an official Garmin Connect Developer Program
(Health/Activity API, OAuth2 PKCE) implementation can be dropped in later, see
PLAN-garmin-official-oauth.md.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from typing import Any, Protocol

import httpx

PERSONAL_BASE = os.environ.get(
    "GARMIN_PERSONAL_API_BASE_URL", "https://personal.connectapi.garmin.com"
).rstrip("/")
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "garmin-mcp/0.1 (+personal-api)"
MAX_KEY_LEN = 4096


class GarminAuthError(Exception):
    """The supplied Garmin key is missing, invalid, expired or revoked."""


class GarminApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _jwt_exp(token: str) -> float:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return float(json.loads(base64.urlsafe_b64decode(part)).get("exp", 0))
    except Exception:
        return 0.0


class _TokenCache:
    """In-memory only. Maps sha256(api_key) -> (bearer token, expiry)."""

    def __init__(self, max_entries: int = 256):
        self._d: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._max = max_entries

    def get(self, k: str) -> str | None:
        with self._lock:
            v = self._d.get(k)
            if v and v[1] - time.time() > 3600:  # reuse while >1h left (Garmin's own client rule)
                return v[0]
            self._d.pop(k, None)
            return None

    def put(self, k: str, token: str, exp: float) -> None:
        with self._lock:
            if len(self._d) >= self._max:
                self._d.pop(next(iter(self._d)))
            self._d[k] = (token, exp)

    def drop(self, k: str) -> None:
        with self._lock:
            self._d.pop(k, None)


_cache = _TokenCache()
_client = httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=False)


def key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def personal_token(api_key: str, force: bool = False) -> str:
    """Exchange a Personal API key for a bearer token (cached in memory)."""
    api_key = (api_key or "").strip()
    if not api_key or len(api_key) > MAX_KEY_LEN or any(c in api_key for c in "\r\n"):
        raise GarminAuthError("Missing or malformed Garmin Personal API key")
    fp = key_fingerprint(api_key)
    if not force and (tok := _cache.get(fp)):
        return tok
    try:
        r = _client.post(
            PERSONAL_BASE + TOKEN_PATH,
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
    _cache.put(fp, token, _jwt_exp(token) or time.time() + 6 * 3600)
    return token


class GarminSource(Protocol):
    name: str

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any: ...


class PersonalApi:
    """Garmin Connect Personal API client bound to one caller's key."""

    name = "garmin-personal-api"

    def __init__(self, api_key: str):
        self._key = api_key

    def get(self, path: str, params: dict[str, Any] | None = None, _retry: bool = True) -> Any:
        token = personal_token(self._key)
        params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            r = _client.get(
                PERSONAL_BASE + path,
                params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        except httpx.HTTPError as e:
            raise GarminApiError(f"Could not reach Garmin ({type(e).__name__})") from None
        if r.status_code == 401 and _retry:  # token revoked early: re-exchange once
            _cache.drop(key_fingerprint(self._key))
            return self.get(path, params, _retry=False)
        if r.status_code == 401:
            raise GarminAuthError("Garmin rejected the access token for this key")
        if r.status_code == 204 or not r.content:
            return None
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            raise GarminApiError("Garmin rate limit (HTTP 429); try again later", 429)
        if not r.is_success:
            raise GarminApiError(
                f"Garmin API returned HTTP {r.status_code} for {path.split('/')[1]}", r.status_code
            )
        return r.json()

    # ---- typed helpers (Personal API paths, per garmin/connect-personal-api-python) ----
    def profile_settings(self):
        return self.get("/userprofile-service/userprofile/settings")

    def activities(self, start=0, limit=20, start_date=None, end_date=None, activity_type=None):
        return self.get(
            "/activitylist-service/activities/search/activities",
            {
                "start": start,
                "limit": limit,
                "startDate": start_date,
                "endDate": end_date,
                "activityType": activity_type,
            },
        )

    def activity(self, activity_id: int):
        return self.get(f"/activity-service/activity/{int(activity_id)}")

    def daily_summaries(self, s, e):
        return self.get("/usersummary-service/v2/dailysummaries", {"startDate": s, "endDate": e})

    def sleep(self, d):
        return self.get("/sleep-service/sleep/dailySleep", {"date": d})

    def sleep_summaries(self, s, e):
        return self.get(
            "/sleep-service/sleep/dailySleepSummariesByDate", {"startDate": s, "endDate": e}
        )

    def heart_rate(self, d):
        return self.get("/wellness-service/wellness/dailyHeartRate", {"date": d})

    def hrv(self, d):
        return self.get(f"/hrv-service/hrv/{d}")

    def hrv_range(self, s, e):
        return self.get(f"/hrv-service/hrv/daily/{s}/{e}")

    def stress_range(self, s, e):
        return self.get(f"/usersummary-service/stats/stress/daily/{s}/{e}")

    def steps_range(self, s, e):
        return self.get(f"/usersummary-service/stats/steps/daily/{s}/{e}")

    def hydration_range(self, s, e):
        return self.get(f"/usersummary-service/stats/hydration/daily/{s}/{e}")

    def body_battery_range(self, s, e):
        return self.get(
            "/wellness-service/wellness/bodyBattery/reports/daily", {"startDate": s, "endDate": e}
        )

    def weight_range(self, s, e):
        return self.get(f"/weight-service/weight/range/{s}/{e}")

    def vo2max_range(self, s, e):
        return self.get(f"/metrics-service/metrics/maxmet/daily/{s}/{e}")

    def spo2(self, d):
        return self.get(f"/wellness-service/wellness/daily/spo2acclimation/{d}")

    def fitness_age(self, d):
        return self.get(f"/fitnessage-service/fitnessage/v2/{d}")

    def hr_zones(self):
        return self.get("/biometric-service/heartRateZones/v2")

    def wellness_activities(self, s, e):
        return self.get(f"/wellnessactivity-service/activity/summary/range/{s}/{e}")
