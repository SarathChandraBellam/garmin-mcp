"""A synthetic Garmin Personal API for analytics tests. Every value is made up.

Range endpoints answer for whatever window they are asked, so chunked and parallel fetches
behave like the real thing. Values are deterministic functions of the date, and the fake
records every request (and the peak number in flight) for assertions.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import respx

from garmin_mcp.sdk import PERSONAL_BASE, TOKEN_PATH
from tests.conftest import fake_jwt

B = PERSONAL_BASE


def _days(s: str, e: str) -> list[dt.date]:
    a, b = dt.date.fromisoformat(s), dt.date.fromisoformat(e)
    return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]


def _ms(d: dt.date, hh: int, mm: int) -> int:
    """Garmin's local "shifted epoch": local wall-clock time encoded as if it were UTC."""
    t = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=dt.timezone.utc)
    return int(t.timestamp() * 1000)


@dataclass
class FakeGarmin:
    missing: set[str] = field(default_factory=set)  # dates with no data at all
    step_goal: int | None = 10_000
    intensity_goal: int | None = 150
    activities: list[dict[str, Any]] = field(default_factory=list)
    splits_status: int = 200  # HTTP status of the (unconfirmed) splits endpoint
    delay: float = 0.0
    calls: list[tuple[str, str, str]] = field(default_factory=list)  # (series, start, end)
    peak_in_flight: int = 0
    _in_flight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---- per-day synthetic values -------------------------------------------------------
    def steps(self, d: dt.date) -> dict[str, Any]:
        row: dict[str, Any] = {"totalSteps": 6000 + (d.toordinal() % 5) * 1500}
        if self.step_goal:
            row["stepGoal"] = self.step_goal
        return {"calendarDate": d.isoformat(), "values": row}

    def stress(self, d: dt.date) -> dict[str, Any]:
        return {"calendarDate": d.isoformat(), "values": {"overallStressLevel": 25 + d.day % 10}}

    def body_battery(self, d: dt.date) -> dict[str, Any]:
        return {
            "date": d.isoformat(),
            "charged": 60,
            "drained": 55,
            "bodyBatteryValuesArray": [[_ms(d, 6, 0), 80 - d.day % 10], [_ms(d, 22, 0), 20]],
        }

    def sleep(self, d: dt.date) -> dict[str, Any]:
        bed = _ms(d - dt.timedelta(days=1), 23, 30) if d.day % 2 else _ms(d, 0, 30)
        return {
            "calendarDate": d.isoformat(),
            "sleepTimeSeconds": 7 * 3600,
            "deepSleepSeconds": 3600,
            "lightSleepSeconds": 4 * 3600,
            "remSleepSeconds": 2 * 3600,
            "awakeSleepSeconds": 600,
            "sleepStartTimestampLocal": bed,
            "sleepEndTimestampLocal": _ms(d, 7, 0),
            "sleepScores": {"overall": {"value": 80}},
            "sleepNeed": {"actual": 480, "deviceId": 4242},
            "userProfilePK": 999999,
        }

    def hrv(self, d: dt.date) -> dict[str, Any]:
        return {
            "calendarDate": d.isoformat(),
            "lastNightAvg": 45 + d.day % 5,
            "weeklyAvg": 47,
            "status": "BALANCED",
            "baseline": {"balancedLow": 40, "balancedUpper": 55},
        }

    def daily(self, d: dt.date) -> dict[str, Any]:
        im: dict[str, Any] = {"moderate": 10 + d.day % 3 * 10, "vigorous": 5}
        if self.intensity_goal:
            im["goal"] = self.intensity_goal
        return {
            "calendarDate": d.isoformat(),
            "userProfilePk": 999999,
            "heartRate": {"restingHeartRate": 50 + d.day % 3},
            "intensityMinutes": im,
            "calories": {"totalKilocalories": 2200},
        }

    # ---- respx wiring -------------------------------------------------------------------
    def _rows(self, kind: str, s: str, e: str) -> list[dict[str, Any]]:
        make = getattr(self, kind)
        return [make(d) for d in _days(s, e) if d.isoformat() not in self.missing]

    def _handler(self, kind: str, wrap: str | None = None):
        def handle(request: httpx.Request) -> httpx.Response:
            q = request.url.params
            if "startDate" in q:
                s, e = q["startDate"], q["endDate"]
            else:
                s, e = re.findall(r"\d{4}-\d{2}-\d{2}", request.url.path)[-2:]
            with self._lock:
                self.calls.append((kind, s, e))
                self._in_flight += 1
                self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
            try:
                if self.delay:
                    time.sleep(self.delay)
                rows = self._rows(kind, s, e)
                return httpx.Response(200, json={wrap: rows} if wrap else rows)
            finally:
                with self._lock:
                    self._in_flight -= 1

        return handle

    def _day(self, kind: str, wrap: str | None = None):
        def handle(request: httpx.Request) -> httpx.Response:
            q = request.url.params
            d = q.get("date") or re.findall(r"\d{4}-\d{2}-\d{2}", request.url.path)[-1]
            if d in self.missing:
                return httpx.Response(204)
            row = getattr(self, kind)(dt.date.fromisoformat(d))
            return httpx.Response(200, json={wrap: row} if wrap else row)

        return handle

    def _activities(self, request: httpx.Request) -> httpx.Response:
        q = request.url.params
        start, limit = int(q.get("start", 0)), int(q.get("limit", 20))
        rows = [
            a
            for a in self.activities
            if (not q.get("startDate") or a["startTimeLocal"][:10] >= q["startDate"])
            and (not q.get("endDate") or a["startTimeLocal"][:10] <= q["endDate"])
            and (not q.get("activityType") or a["activityType"]["typeKey"] == q["activityType"])
        ]
        return httpx.Response(200, json=rows[start : start + limit])

    def _splits(self, request: httpx.Request) -> httpx.Response:
        if self.splits_status != 200:
            return httpx.Response(self.splits_status, text="unavailable")
        laps = [
            {
                "distance": 1000,
                "duration": 330,
                "averageHR": 150,
                "averageSpeed": 3.03,
                "startLatitude": 1.0,
                "geoPolylineDTO": {"polyline": [[1, 2]]},
            },
            {"distance": 1000, "duration": 320, "averageHR": 155, "averageSpeed": 3.1},
        ]
        return httpx.Response(200, json={"lapDTOs": laps})

    def install(self, router: respx.Router | Any = respx) -> FakeGarmin:
        router.post(B + TOKEN_PATH).mock(return_value=httpx.Response(200, text=fake_jwt()))
        d = r"\d{4}-\d{2}-\d{2}"
        router.get(url__regex=rf"{B}/usersummary-service/stats/steps/daily/{d}/{d}").mock(
            side_effect=self._handler("steps")
        )
        router.get(url__regex=rf"{B}/usersummary-service/stats/stress/daily/{d}/{d}").mock(
            side_effect=self._handler("stress")
        )
        router.get(f"{B}/wellness-service/wellness/bodyBattery/reports/daily").mock(
            side_effect=self._handler("body_battery")
        )
        router.get(f"{B}/sleep-service/sleep/dailySleepSummariesByDate").mock(
            side_effect=self._handler("sleep")
        )
        router.get(url__regex=rf"{B}/hrv-service/hrv/daily/{d}/{d}").mock(
            side_effect=self._handler("hrv", "hrvSummaries")
        )
        router.get(f"{B}/usersummary-service/v2/dailysummaries").mock(
            side_effect=self._handler("daily", "data")
        )
        router.get(url__regex=rf"{B}/hrv-service/hrv/{d}$").mock(
            side_effect=self._day("hrv", "hrvSummary")
        )
        router.get(f"{B}/sleep-service/sleep/dailySleep").mock(
            side_effect=self._day("sleep", "dailySleepDTO")
        )
        router.get(f"{B}/activitylist-service/activities/search/activities").mock(
            side_effect=self._activities
        )
        router.get(url__regex=rf"{B}/activity-service/activity/\d+/splits$").mock(
            side_effect=self._splits
        )
        router.get(url__regex=rf"{B}/activity-service/activity/\d+$").mock(
            side_effect=lambda r: httpx.Response(
                200,
                json=next(
                    (a for a in self.activities if str(a["activityId"]) in r.url.path),
                    {},
                ),
            )
        )
        return self


def activity(
    aid: int, day: str, kind: str = "running", km: float = 5.0, minutes: float = 30.0
) -> dict[str, Any]:
    return {
        "activityId": aid,
        "activityName": f"{kind.title()} {aid}",
        "activityType": {"typeKey": kind},
        "startTimeLocal": f"{day} 07:00:00",
        "distance": km * 1000,
        "duration": minutes * 60,
        "movingDuration": minutes * 60 - 30,
        "averageSpeed": km * 1000 / (minutes * 60),
        "averageHR": 140 + aid % 15,
        "elevationGain": 25,
        "calories": 300,
        "hrTimeInZone_1": 60,
        "hrTimeInZone_2": 600,
        "hrTimeInZone_3": 900,
        "hrTimeInZone_4": 180,
        "hrTimeInZone_5": 60,
        "ownerFullName": "REDACTED PERSON",
        "startLatitude": 12.3,
        "startLongitude": 45.6,
    }
