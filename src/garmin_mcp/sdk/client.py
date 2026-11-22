"""Garmin Connect Personal API client (personal.connectapi.garmin.com).

Each caller supplies their own Personal API key; it is exchanged for a ~24h bearer token
(see :mod:`garmin_mcp.sdk.token`). Responses are returned and discarded.

:class:`GarminSource` is the swap point: an official Garmin Connect Developer Program
(Health/Activity API) implementation can be dropped in later, see
PLAN-garmin-official-oauth.md.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

import httpx

from . import _http
from .errors import GarminApiError, GarminAuthError
from .token import cache, key_fingerprint, personal_token

_MAX_DETAIL = 200
_UNPRINTABLE = re.compile(r"[^\x20-\x7e]+")


def error_detail(body: str, *secrets: str) -> str:
    """A short, single-line, secret-free excerpt of a Garmin error body (or "" if unusable)."""
    text = body.strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        for k in ("message", "errorMessage", "error_description", "error", "detail"):
            if isinstance(parsed.get(k), str) and parsed[k].strip():
                text = parsed[k]
                break
    if not text or text.lstrip().startswith("<"):  # empty, or an HTML error page
        return ""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    text = " ".join(_UNPRINTABLE.sub(" ", text).split())
    return text if len(text) <= _MAX_DETAIL else text[: _MAX_DETAIL - 3] + "..."


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
            r = _http.client.get(
                _http.PERSONAL_BASE + path,
                params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        except httpx.HTTPError as e:
            raise GarminApiError(f"Could not reach Garmin ({type(e).__name__})") from None
        if r.status_code == 401 and _retry:  # token revoked early: re-exchange once
            cache.drop(key_fingerprint(self._key))
            return self.get(path, params, _retry=False)
        if r.status_code == 401:
            raise GarminAuthError("Garmin rejected the access token for this key")
        if r.status_code in (204, 404) or not r.content:
            return None
        if r.status_code == 429:
            raise GarminApiError("Garmin rate limit (HTTP 429); try again later", 429)
        if not r.is_success:
            msg = f"Garmin API returned HTTP {r.status_code} for {path.split('/')[1]}"
            detail = error_detail(r.text, token, self._key)
            raise GarminApiError(f"{msg}: {detail}" if detail else msg, r.status_code)
        return r.json()

    # ---- typed helpers (Personal API paths, per garmin/connect-personal-api-python) ----
    def profile_settings(self) -> Any:
        return self.get("/userprofile-service/userprofile/settings")

    def activities(
        self,
        start: int = 0,
        limit: int = 20,
        start_date: str | None = None,
        end_date: str | None = None,
        activity_type: str | None = None,
    ) -> Any:
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

    def activity(self, activity_id: int) -> Any:
        return self.get(f"/activity-service/activity/{int(activity_id)}")

    def activity_splits(self, activity_id: int) -> Any:
        """Laps/splits. Not confirmed on the Personal API; callers treat None as "no splits"."""
        return self.get(f"/activity-service/activity/{int(activity_id)}/splits")

    def daily_summaries(self, s: str, e: str) -> Any:
        return self.get("/usersummary-service/v2/dailysummaries", {"startDate": s, "endDate": e})

    def sleep(self, d: str) -> Any:
        return self.get("/sleep-service/sleep/dailySleep", {"date": d})

    def sleep_summaries(self, s: str, e: str) -> Any:
        return self.get(
            "/sleep-service/sleep/dailySleepSummariesByDate", {"startDate": s, "endDate": e}
        )

    def heart_rate(self, d: str) -> Any:
        return self.get("/wellness-service/wellness/dailyHeartRate", {"date": d})

    def hrv(self, d: str) -> Any:
        return self.get(f"/hrv-service/hrv/{d}")

    def hrv_range(self, s: str, e: str) -> Any:
        return self.get(f"/hrv-service/hrv/daily/{s}/{e}")

    def stress_range(self, s: str, e: str) -> Any:
        return self.get(f"/usersummary-service/stats/stress/daily/{s}/{e}")

    def steps_range(self, s: str, e: str) -> Any:
        return self.get(f"/usersummary-service/stats/steps/daily/{s}/{e}")

    def hydration_range(self, s: str, e: str) -> Any:
        return self.get(f"/usersummary-service/stats/hydration/daily/{s}/{e}")

    def body_battery_range(self, s: str, e: str) -> Any:
        return self.get(
            "/wellness-service/wellness/bodyBattery/reports/daily", {"startDate": s, "endDate": e}
        )

    def weight_range(self, s: str, e: str) -> Any:
        return self.get(f"/weight-service/weight/range/{s}/{e}")

    def vo2max_range(self, s: str, e: str) -> Any:
        return self.get(f"/metrics-service/metrics/maxmet/daily/{s}/{e}")

    def spo2(self, d: str) -> Any:
        return self.get(f"/wellness-service/wellness/daily/spo2acclimation/{d}")

    def fitness_age(self, d: str) -> Any:
        return self.get(f"/fitnessage-service/fitnessage/v2/{d}")

    def hr_zones(self) -> Any:
        return self.get("/biometric-service/heartRateZones/v2")

    def wellness_activities(self, s: str, e: str) -> Any:
        return self.get(f"/wellnessactivity-service/activity/summary/range/{s}/{e}")
