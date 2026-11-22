"""Regression tests for issue #19: range caps, error detail, response contract."""

from __future__ import annotations

import datetime as dt
import json
import re

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from garmin_mcp.sdk import PERSONAL_BASE, TOKEN_PATH, GarminApiError, PersonalApi
from garmin_mcp.sdk.client import error_detail
from garmin_mcp.server import App
from garmin_mcp.tools._context import chunks, today
from garmin_mcp.tools._sanitize import compact, has_data, no_pii
from garmin_mcp.tools._series import SPECS, row_date
from tests.conftest import fake_jwt
from tests.fixtures import (
    ACTIVITY_DETAIL,
    BODY_BATTERY_DAY,
    HRV_DAY,
    SLEEP,
    SLEEP_NULL_SKELETON,
    SLEEP_SKELETON_NIGHT,
    SLEEP_SUMMARIES,
    WEIGHT_RANGE,
    WELLNESS_ACTIVITY,
)
from tests.test_server import _call

# Largest inclusive window Garmin accepted per metric (live probe in issue #19).
GARMIN_CAPS = {
    "steps": 28,
    "stress": 28,
    "body_battery": 31,
    "hydration": 31,
    "sleep": 32,
    "daily_summaries": 32,
    "hrv": 366,
    "weight": 366,
    "vo2max": 366,
    "wellness_activities": 366,
}
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@pytest.fixture
def client():
    with TestClient(App(), base_url="http://localhost") as c:
        yield c


def _token():
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(200, text=fake_jwt()))


def _window(request: httpx.Request) -> tuple[str, str]:
    q = request.url.params
    if "startDate" in q:
        return q["startDate"], q["endDate"]
    s, e = DATE.findall(request.url.path)[-2:]
    return s, e


def _days(s: str, e: str) -> int:
    return (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days + 1


def test_chunks_are_inclusive_and_contiguous():
    assert chunks("2026-01-01", "2026-01-01", 28) == [("2026-01-01", "2026-01-01")]
    parts = chunks("2026-01-01", "2026-03-01", 28)  # 60 days
    assert parts == [
        ("2026-01-01", "2026-01-28"),
        ("2026-01-29", "2026-02-25"),
        ("2026-02-26", "2026-03-01"),
    ]


def test_chunk_sizes_never_exceed_garmin_caps():
    for metric, spec in SPECS.items():
        assert spec.chunk_days <= GARMIN_CAPS[metric], metric


@pytest.mark.parametrize("metric", list(SPECS))
@pytest.mark.parametrize("n", [1, 7, 28, 29, 30, 31, 32, 33, 366])
@respx.mock
def test_range_boundaries(client: TestClient, metric: str, n: int):
    """Every metric accepts up to its documented max and never sends Garmin an over-cap window."""
    _token()
    windows: list[tuple[str, str]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        s, e = _window(request)
        windows.append((s, e))
        if _days(s, e) > GARMIN_CAPS[metric]:
            return httpx.Response(400, json={"message": "range too long"})
        return httpx.Response(200, json=[])

    respx.get(url__startswith=PERSONAL_BASE).mock(side_effect=upstream)
    end = "2026-06-30"
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=n - 1)).isoformat()
    err, text = _call(
        client, "query_stats", {"metric": metric, "start_date": start, "end_date": end}
    )

    if n > SPECS[metric].max_days:
        assert err
        assert metric in text and f"{n} days" in text and f"max {SPECS[metric].max_days}" in text
        assert windows == []  # rejected before any upstream call
        return
    assert not err, text
    body = json.loads(text)
    assert body["days"] == n
    assert len(body["data"]) == n  # one padded row per requested date
    assert all(_days(s, e) <= GARMIN_CAPS[metric] for s, e in windows)
    assert sum(_days(s, e) for s, e in windows) == n  # contiguous, no overlap


@respx.mock
def test_upstream_400_detail_is_surfaced(client: TestClient):
    _token()
    respx.get(url__startswith=PERSONAL_BASE).mock(
        return_value=httpx.Response(400, json={"message": "range exceeds 28 days"})
    )
    err, text = _call(
        client,
        "query_stats",
        {"metric": "hrv", "start_date": "2026-01-01", "end_date": "2026-01-02"},
    )
    assert err
    assert "HTTP 400" in text and "hrv-service" in text and "range exceeds 28 days" in text


@respx.mock
def test_upstream_error_detail_never_echoes_secrets():
    _token()
    key = "secret-key-123"
    respx.get(url__startswith=PERSONAL_BASE).mock(
        return_value=httpx.Response(400, text=f"bad request for {key}\n\x00 more")
    )
    with pytest.raises(GarminApiError) as exc:
        PersonalApi(key).hrv("2026-01-01")
    assert key not in str(exc.value)
    assert "[redacted]" in str(exc.value)
    assert "\n" not in str(exc.value)


def test_error_detail_shapes():
    assert error_detail("") == ""
    assert error_detail("<html><body>oops</body></html>") == ""
    assert error_detail('{"errorMessage": "bad date"}') == "bad date"
    assert len(error_detail("x" * 1000)) == 200


@pytest.mark.parametrize(
    "args, needle",
    [
        ({"metric": "steps", "start_date": "2026-13-40"}, "calendar date"),
        ({"metric": "steps", "start_date": "2026-02-01", "end_date": "2026-01-01"}, "start_date"),
        ({"metric": "nope", "start_date": "2026-01-01"}, "metric"),
    ],
)
@respx.mock
def test_input_errors_name_the_field(client: TestClient, args: dict, needle: str):
    _token()
    err, text = _call(client, "query_stats", args)
    assert err
    assert needle in text


@respx.mock
def test_daily_summary_rejects_impossible_date(client: TestClient):
    _token()
    err, text = _call(client, "get_daily_summary", {"date": "2026-13-40"})
    assert err
    assert "calendar date" in text


@respx.mock
def test_gap_padding_and_partial_today(client: TestClient):
    _token()
    t = today()
    d = [(dt.date.fromisoformat(t) - dt.timedelta(days=i)).isoformat() for i in (3, 2, 1, 0)]
    respx.get(url__startswith=f"{PERSONAL_BASE}/usersummary-service/stats/steps/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"calendarDate": d[1], "values": {"totalSteps": 8000}},
                {"calendarDate": d[3], "values": {"totalSteps": 1200}},
            ],
        )
    )
    err, text = _call(client, "query_stats", {"metric": "steps", "start_date": d[0]})
    assert not err
    body = json.loads(text)
    assert body["status"] == "ok" and body["days_with_data"] == 2
    assert [r["calendarDate"] for r in body["data"]] == d
    assert [r["missing"] for r in body["data"]] == [True, False, True, False]
    assert body["data"][3]["partial"] is True
    assert all("partial" not in r for r in body["data"][:3])


@pytest.mark.parametrize("metric", ["steps", "stress", "body_battery", "hrv", "daily_summaries"])
@respx.mock
def test_every_metric_uses_the_same_gap_policy(client: TestClient, metric: str):
    _token()
    row = {"calendarDate": "2026-01-02", "value": 1}
    payload = {"hrv": {"hrvSummaries": [row]}, "daily_summaries": {"data": [row]}}
    respx.get(url__startswith=PERSONAL_BASE).mock(
        return_value=httpx.Response(200, json=payload.get(metric, [row]))
    )
    err, text = _call(
        client,
        "query_stats",
        {"metric": metric, "start_date": "2026-01-01", "end_date": "2026-01-03"},
    )
    assert not err
    data = json.loads(text)["data"]
    assert [(r["calendarDate"], r["missing"]) for r in data] == [
        ("2026-01-01", True),
        ("2026-01-02", False),
        ("2026-01-03", True),
    ]


@respx.mock
def test_empty_series_is_structured_not_blank(client: TestClient):
    _token()
    respx.get(url__startswith=PERSONAL_BASE).mock(return_value=httpx.Response(200, json=[]))
    err, text = _call(
        client,
        "query_stats",
        {"metric": "hydration", "start_date": "2026-01-01", "end_date": "2026-01-07"},
    )
    assert not err and text  # never an empty MCP content array
    body = json.loads(text)
    assert body["status"] == "empty"
    assert body["days_with_data"] == 0
    assert any("not that the metric is unsupported" in n for n in body["notes"])


@respx.mock
def test_empty_activity_list_is_structured(client: TestClient):
    _token()
    respx.get(f"{PERSONAL_BASE}/activitylist-service/activities/search/activities").mock(
        return_value=httpx.Response(200, json=[])
    )
    err, text = _call(
        client, "get_activities", {"start_date": "2026-01-15", "end_date": "2026-01-15"}
    )
    assert not err and text
    body = json.loads(text)
    assert body["count"] == 0 and body["activities"] == []
    assert "intensity minutes" in body["note"]


@respx.mock
def test_weight_units_and_outside_range_hints(client: TestClient):
    _token()
    respx.get(url__startswith=f"{PERSONAL_BASE}/weight-service/").mock(
        return_value=httpx.Response(200, json=WEIGHT_RANGE)
    )
    err, text = _call(
        client,
        "query_stats",
        {"metric": "weight", "start_date": "2026-01-14", "end_date": "2026-01-15"},
    )
    assert not err
    body = json.loads(text)
    assert "grams" in body["units"].values()
    assert body["data"][1]["minWeight"] == 81_200.0
    assert "omitted" in body["data"][1]["allWeightMetrics"]  # compact by default
    assert body["outside_range"] == [{"calendarDate": "2026-01-01", "weight": 81_900.0}]

    err, text = _call(client, "get_body_composition", {"start_date": "2026-01-14"})
    assert not err
    assert "grams" in json.loads(text)["units"].values()


@respx.mock
def test_sleep_wake_date_outside_window_and_raw(client: TestClient):
    _token()
    respx.get(f"{PERSONAL_BASE}/sleep-service/sleep/dailySleepSummariesByDate").mock(
        return_value=httpx.Response(200, json=SLEEP_SUMMARIES)
    )
    args = {"metric": "sleep", "start_date": "2026-01-14", "end_date": "2026-01-15"}
    body = json.loads(_call(client, "query_stats", args)[1])
    assert [r["calendarDate"] for r in body["data"]] == ["2026-01-14", "2026-01-15"]
    assert body["outside_range"][0]["calendarDate"] == "2026-01-16"
    assert "sleepNeed" not in body["data"][0]  # heavy descriptor dropped in compact mode
    assert any("woke up" in n for n in body["notes"])

    raw = json.loads(_call(client, "query_stats", {**args, "raw": True})[1])
    assert raw["data"][0]["sleepNeed"] == {}  # kept, but deviceId still stripped


@respx.mock
def test_null_skeleton_sleep_is_a_note(client: TestClient):
    _token()
    respx.get(f"{PERSONAL_BASE}/sleep-service/sleep/dailySleep").mock(
        return_value=httpx.Response(200, json=SLEEP_NULL_SKELETON)
    )
    err, text = _call(client, "get_sleep", {"date": "2020-01-01"})
    assert not err
    assert json.loads(text) == {"note": "No sleep data for 2020-01-01"}


@respx.mock
def test_hrv_note_does_not_blame_the_device(client: TestClient):
    _token()
    respx.get(f"{PERSONAL_BASE}/hrv-service/hrv/2026-01-15").mock(return_value=httpx.Response(204))
    text = _call(client, "get_hrv", {"date": "2026-01-15"})[1]
    assert "device" not in text


@respx.mock
def test_daily_summary_partial_flag(client: TestClient):
    _token()
    t = today()
    respx.get(f"{PERSONAL_BASE}/usersummary-service/v2/dailysummaries").mock(
        side_effect=lambda r: httpx.Response(
            200, json={"data": [{"calendarDate": r.url.params["startDate"], "steps": 10}]}
        )
    )
    assert json.loads(_call(client, "get_daily_summary", {})[1])["partial"] is True
    past = (dt.date.fromisoformat(t) - dt.timedelta(days=1)).isoformat()
    assert json.loads(_call(client, "get_daily_summary", {"date": past})[1])["partial"] is False


@respx.mock
def test_training_readiness_omits_hrv_readings(client: TestClient):
    _token()
    respx.get(f"{PERSONAL_BASE}/hrv-service/hrv/2026-01-15").mock(
        return_value=httpx.Response(200, json=HRV_DAY)
    )
    respx.get(f"{PERSONAL_BASE}/sleep-service/sleep/dailySleep").mock(
        return_value=httpx.Response(200, json=SLEEP)
    )
    respx.get(f"{PERSONAL_BASE}/wellness-service/wellness/bodyBattery/reports/daily").mock(
        return_value=httpx.Response(200, json=[{"date": "2026-01-15", "charged": 40}])
    )
    body = json.loads(_call(client, "get_training_readiness", {"date": "2026-01-15"})[1])
    assert "66 samples omitted" in body["hrv"]["hrvReadings"]
    full = json.loads(
        _call(client, "get_training_readiness", {"date": "2026-01-15", "include_samples": True})[1]
    )
    assert len(full["hrv"]["hrvReadings"]) == 66


@respx.mock
def test_get_activity_strips_residual_identifiers(client: TestClient):
    _token()
    respx.get(f"{PERSONAL_BASE}/activity-service/activity/1001").mock(
        return_value=httpx.Response(200, json=ACTIVITY_DETAIL)
    )
    body = json.loads(_call(client, "get_activity", {"activity_id": 1001})[1])
    assert body["activityId"] == 1001
    for k in ("userProfileId", "locationName", "activityUUID"):
        assert k not in body
    assert "deviceId" not in body["summaryDTO"] and "startLatitude" not in body["summaryDTO"]


def test_helpers():
    assert row_date({"generic": {"calendarDate": "2026-01-02"}}) == "2026-01-02"
    assert row_date({"startTimeLocal": "2026-01-02 07:00:00"}) == "2026-01-02"
    assert row_date({"value": 1}) is None
    assert not has_data({"calendarDate": "2026-01-01", "x": None, "flag": False, "l": []})
    assert has_data({"calendarDate": "2026-01-01", "x": 0})
    assert compact({"a": [1, 2], "b": [{"x": 1}], "c": 1}) == {
        "a": [1, 2],
        "b": "[1 items omitted; pass raw=true]",
        "c": 1,
    }


@respx.mock
def test_skeleton_sleep_night_is_missing(client: TestClient):
    """A night with only sleepNeed descriptors is a gap, not data, and keeps its own date."""
    _token()
    respx.get(f"{PERSONAL_BASE}/sleep-service/sleep/dailySleepSummariesByDate").mock(
        return_value=httpx.Response(
            200,
            json=[{"calendarDate": "2026-01-14", "sleepTimeSeconds": 25_000}, SLEEP_SKELETON_NIGHT],
        )
    )
    args = {"metric": "sleep", "start_date": "2026-01-14", "end_date": "2026-01-15"}
    for raw in (False, True):
        body = json.loads(_call(client, "query_stats", {**args, "raw": raw})[1])
        assert body["days_with_data"] == 1
        assert [(r["calendarDate"], r["missing"]) for r in body["data"]] == [
            ("2026-01-14", False),
            ("2026-01-15", True),
        ]
        assert body["outside_range"] == []


@respx.mock
def test_skeleton_only_window_is_empty(client: TestClient):
    _token()
    respx.get(f"{PERSONAL_BASE}/sleep-service/sleep/dailySleepSummariesByDate").mock(
        return_value=httpx.Response(200, json=[SLEEP_SKELETON_NIGHT])
    )
    args = {"metric": "sleep", "start_date": "2026-01-15", "end_date": "2026-01-15"}
    body = json.loads(_call(client, "query_stats", args)[1])
    assert body["status"] == "empty"
    assert body["data"] == [{"calendarDate": "2026-01-15", "missing": True}]


@respx.mock
def test_body_battery_rows_use_calendar_date(client: TestClient):
    _token()
    respx.get(f"{PERSONAL_BASE}/wellness-service/wellness/bodyBattery/reports/daily").mock(
        return_value=httpx.Response(200, json=[BODY_BATTERY_DAY])
    )
    args = {"metric": "body_battery", "start_date": "2026-01-14", "end_date": "2026-01-15"}
    data = json.loads(_call(client, "query_stats", args)[1])["data"]
    assert data[0] == {"calendarDate": "2026-01-14", "missing": True}
    assert data[1] == {"calendarDate": "2026-01-15", "charged": 40, "drained": 55, "missing": False}


@respx.mock
def test_wellness_activities_strip_ids(client: TestClient):
    _token()
    respx.get(url__startswith=f"{PERSONAL_BASE}/wellnessactivity-service/").mock(
        return_value=httpx.Response(200, json=[WELLNESS_ACTIVITY])
    )
    args = {"metric": "wellness_activities", "start_date": "2026-01-15", "end_date": "2026-01-15"}
    for raw in (False, True):
        row = json.loads(_call(client, "query_stats", {**args, "raw": raw})[1])["data"][0]
        assert row["activityType"] == "walking"
        assert "activityUuid" not in row and "deviceMetaData" not in row


def test_pii_denylist_is_case_insensitive():
    assert no_pii({"ActivityUuid": 1, "USERID": 2, "deviceid": 3, "keep": 4}) == {"keep": 4}
    assert not has_data({"sleepNeed": {"baseline": 480}}, frozenset({"sleepNeed"}))
    assert row_date({"sleepNeed": {"calendarDate": "2026-01-14"}}, frozenset({"sleepNeed"})) is None
