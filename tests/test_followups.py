"""Follow-ups to issue #19: uncategorized stress, unknown status, nearest records,
compact daily summaries, get_hrv samples, clean validation errors, caller time zone."""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from garmin_mcp.sdk import PERSONAL_BASE, TOKEN_PATH
from garmin_mcp.server import App
from garmin_mcp.tools import _context
from tests.conftest import fake_jwt
from tests.fixtures import DAILY_SUMMARY_FULL, HRV_DAY
from tests.test_server import _call

STRESS = f"{PERSONAL_BASE}/usersummary-service/stats/stress/daily/"
SUMMARIES = f"{PERSONAL_BASE}/usersummary-service/v2/dailysummaries"
VO2 = f"{PERSONAL_BASE}/metrics-service/metrics/maxmet/daily/"


@pytest.fixture
def client():
    with TestClient(App(), base_url="http://localhost") as c:
        yield c


def _token():
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(200, text=fake_jwt()))


def _days(s: str, e: str) -> int:
    return (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days + 1


def _body(client: TestClient, tool: str, args: dict, **kw) -> dict:
    err, text = _call(client, tool, args, **kw)
    assert not err, text
    return json.loads(text)


# ---- 5. uncategorized stress -------------------------------------------------------------


def _stress_row(d: str) -> dict:
    return {"calendarDate": d, "values": {"overallStressLevel": 30, "lowStressDuration": 100}}


@respx.mock
def test_stress_uncategorized_merged_with_chunked_daily_summaries(client: TestClient):
    _token()
    windows: list[tuple[str, str]] = []

    def summaries(request: httpx.Request) -> httpx.Response:
        s, e = request.url.params["startDate"], request.url.params["endDate"]
        windows.append((s, e))
        day = dt.date.fromisoformat(s)
        rows = []
        while day.isoformat() <= e:
            rows.append(
                {
                    "calendarDate": day.isoformat(),
                    "stress": {
                        "uncategorizedProportion": 0.4,
                        "uncategorizedDurationInMillis": 34_560_000,
                    },
                }
            )
            day += dt.timedelta(days=1)
        return httpx.Response(200, json={"data": rows})

    respx.get(url__startswith=STRESS).mock(
        side_effect=lambda r: httpx.Response(
            200, json=[_stress_row(r.url.path.split("/")[-2])]  # one row per chunk start
        )
    )
    respx.get(SUMMARIES).mock(side_effect=summaries)
    body = _body(
        client,
        "query_stats",
        {
            "metric": "stress",
            "start_date": "2026-01-01",
            "end_date": "2026-02-15",  # 46 days: stress in 28-day chunks, summaries in 31
            "include_uncategorized": True,
        },
    )
    assert all(_days(s, e) <= 31 for s, e in windows) and len(windows) == 2
    present = [r for r in body["data"] if not r["missing"]]
    assert [r["calendarDate"] for r in present] == ["2026-01-01", "2026-01-29"]
    for r in present:
        assert r["values"]["uncategorizedProportion"] == 0.4
        assert r["values"]["uncategorizedDurationInMillis"] == 34_560_000
        assert r["values"]["overallStressLevel"] == 30
    assert any("merged in" in n for n in body["notes"])
    assert not any("include_uncategorized=true" in n for n in body["notes"])


@respx.mock
def test_stress_default_makes_no_summary_call_and_keeps_note(client: TestClient):
    _token()
    respx.get(url__startswith=STRESS).mock(
        return_value=httpx.Response(200, json=[_stress_row("2026-01-02")])
    )
    summaries = respx.get(SUMMARIES).mock(return_value=httpx.Response(200, json={"data": []}))
    body = _body(
        client,
        "query_stats",
        {"metric": "stress", "start_date": "2026-01-01", "end_date": "2026-01-03"},
    )
    assert summaries.call_count == 0
    assert "uncategorizedProportion" not in body["data"][1]["values"]
    assert any("include_uncategorized=true" in n for n in body["notes"])


@respx.mock
def test_include_uncategorized_rejected_for_other_metrics(client: TestClient):
    _token()
    err, text = _call(
        client,
        "query_stats",
        {"metric": "steps", "start_date": "2026-01-01", "include_uncategorized": True},
    )
    assert err and "include_uncategorized" in text


# ---- 6 / 7. unknown status and nearest records --------------------------------------------


@respx.mock
def test_vo2max_empty_is_unknown_without_nearest(client: TestClient):
    _token()
    route = respx.get(url__startswith=VO2).mock(return_value=httpx.Response(200, json=[]))
    body = _body(
        client,
        "query_stats",
        {"metric": "vo2max", "start_date": "2026-03-01", "end_date": "2026-03-07"},
    )
    assert body["status"] == "unknown"
    assert route.call_count == 1  # no extra lookup unless asked
    assert any("include_nearest=true" in n for n in body["notes"])


@respx.mock
def test_vo2max_nearest_records_one_extra_call(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        _context, "_utcnow", lambda: dt.datetime(2026, 6, 30, 12, tzinfo=dt.timezone.utc)
    )
    _token()
    windows: list[tuple[str, str]] = []

    def vo2(request: httpx.Request) -> httpx.Response:
        s, e = request.url.path.split("/")[-2:]
        windows.append((s, e))
        rows = [
            {"generic": {"calendarDate": d, "vo2MaxPreciseValue": v}, "userId": 999999}
            for d, v in [
                ("2025-10-01", 44.0),
                ("2026-02-10", 45.5),
                ("2026-04-02", 46.1),
                ("2026-05-20", 46.4),
            ]
            if s <= d <= e
        ]
        return httpx.Response(200, json=rows)

    respx.get(url__startswith=VO2).mock(side_effect=vo2)
    body = _body(
        client,
        "query_stats",
        {
            "metric": "vo2max",
            "start_date": "2026-03-01",
            "end_date": "2026-03-31",
            "include_nearest": True,
        },
    )
    assert len(windows) == 2  # the window itself + exactly one wider lookup
    lo, hi = windows[1]
    assert lo == "2025-09-02" and _days(lo, hi) <= 366  # 180 days back, single call
    assert body["status"] == "empty"  # records exist, so the metric is supported
    near = {o["nearest"]: o for o in body["outside_range"]}
    assert near["before"]["calendarDate"] == "2026-02-10"
    assert near["after"]["calendarDate"] == "2026-04-02"
    assert near["before"]["generic"]["vo2MaxPreciseValue"] == 45.5
    assert "userId" not in near["before"]
    assert all(r["missing"] for r in body["data"])


@respx.mock
def test_nearest_lookup_is_capped_at_one_call_for_long_windows(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        _context, "_utcnow", lambda: dt.datetime(2026, 12, 31, tzinfo=dt.timezone.utc)
    )
    _token()
    windows: list[tuple[str, str]] = []
    respx.get(url__startswith=f"{PERSONAL_BASE}/hrv-service/hrv/daily/").mock(
        side_effect=lambda r: windows.append(tuple(r.url.path.split("/")[-2:]))
        or httpx.Response(200, json={"hrvSummaries": []})
    )
    body = _body(
        client,
        "query_stats",
        {
            "metric": "hrv",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "include_nearest": True,
        },
    )
    assert len(windows) == 2 and _days(*windows[1]) == 366
    assert body["status"] == "empty" and body["outside_range"] == []


@respx.mock
def test_include_nearest_rejected_for_dense_metrics(client: TestClient):
    _token()
    err, text = _call(
        client,
        "query_stats",
        {"metric": "steps", "start_date": "2026-01-01", "include_nearest": True},
    )
    assert err and "include_nearest" in text and "vo2max" in text


# ---- 8. compact daily summaries -------------------------------------------------------------


@respx.mock
def test_daily_summaries_compact_view(client: TestClient):
    _token()
    respx.get(SUMMARIES).mock(return_value=httpx.Response(200, json={"data": [DAILY_SUMMARY_FULL]}))
    args = {"metric": "daily_summaries", "start_date": "2026-01-15", "end_date": "2026-01-15"}
    compact = _body(client, "query_stats", args)["data"][0]
    raw = _body(client, "query_stats", {**args, "raw": True})["data"][0]

    assert len(json.dumps(compact)) <= 0.6 * len(json.dumps(raw))  # at least 40% smaller
    assert compact["bodyBattery"] == {
        "charged": 40,
        "drained": 55,
        "highest": 90,
        "lowest": 30,
        "mostRecent": 45,
    }
    assert compact["stress"]["uncategorizedProportion"] == 0.42
    assert "levels" not in compact["stress"]
    assert compact["movement"]["steps"] == {"value": 10234, "goal": 8000, "distanceInMeters": 7800}
    assert compact["heartRate"]["restingValue"] == 52
    assert compact["intensityMinutes"]["vigorous"] == 5
    assert compact["calories"]["total"] == 2100
    assert "wellnessChronology" not in compact and "respiration" not in compact
    assert raw["bodyBattery"]["events"][0]["eventType"] == "SLEEP"  # raw keeps everything


# ---- 9. get_hrv samples -----------------------------------------------------------------------


@respx.mock
def test_get_hrv_readings_opt_in(client: TestClient):
    _token()
    respx.get(f"{PERSONAL_BASE}/hrv-service/hrv/2026-01-15").mock(
        return_value=httpx.Response(200, json=HRV_DAY)
    )
    slim = _body(client, "get_hrv", {"date": "2026-01-15"})
    assert slim["hrvReadings"] == "[66 samples omitted; pass include_samples=true]"
    assert slim["hrvSummary"]["lastNightAvg"] == 48
    full = _body(client, "get_hrv", {"date": "2026-01-15", "include_samples": True})
    assert len(full["hrvReadings"]) == 66


@respx.mock
def test_short_hrv_readings_are_still_omitted(client: TestClient):
    """hrvReadings is always collapsed by default, even when shorter than MAX_SAMPLES."""
    _token()
    short = {**HRV_DAY, "hrvReadings": HRV_DAY["hrvReadings"][:5]}
    respx.get(f"{PERSONAL_BASE}/hrv-service/hrv/2026-01-15").mock(
        return_value=httpx.Response(200, json=short)
    )
    assert "5 samples omitted" in _body(client, "get_hrv", {"date": "2026-01-15"})["hrvReadings"]


# ---- 10. validation errors --------------------------------------------------------------------


@pytest.mark.parametrize(
    "args, expected",
    [
        (
            {"metric": "steps", "start_date": "2026-13-40"},
            "start_date: '2026-13-40' is not a valid calendar date (YYYY-MM-DD)",
        ),
        ({"metric": "heartbeat", "start_date": "2026-01-01"}, "metric: Input should be 'steps'"),
    ],
)
@respx.mock
def test_validation_errors_are_field_problem_lines(client: TestClient, args: dict, expected: str):
    _token()
    err, text = _call(client, "query_stats", args)
    assert err
    assert text.startswith(expected)
    for noise in ("validation error", "pydantic.dev", "type=", "input_value", "Value error"):
        assert noise not in text
    assert len(text.splitlines()) == 1


@respx.mock
def test_multiple_validation_errors_one_line_each(client: TestClient):
    _token()
    err, text = _call(
        client, "get_activities", {"limit": 0, "start_date": "2026-02-30", "offset": -1}
    )
    assert err
    lines = text.splitlines()
    assert sorted(line.split(":")[0] for line in lines) == ["limit", "offset", "start_date"]


# ---- 11. caller time zone -------------------------------------------------------------------

# 2026-01-15 19:00 UTC is 2026-01-16 00:30 in Asia/Kolkata (UTC+5:30): just past local midnight.
AFTER_IST_MIDNIGHT = dt.datetime(2026, 1, 15, 19, 0, tzinfo=dt.timezone.utc)
BEFORE_IST_MIDNIGHT = dt.datetime(2026, 1, 15, 18, 29, tzinfo=dt.timezone.utc)


def _echo_summaries():
    return respx.get(SUMMARIES).mock(
        side_effect=lambda r: httpx.Response(
            200, json={"data": [{"calendarDate": r.url.params["startDate"], "steps": 10}]}
        )
    )


@respx.mock
def test_today_follows_caller_tz_around_local_midnight(client: TestClient, monkeypatch):
    _token()
    route = _echo_summaries()

    monkeypatch.setattr(_context, "_utcnow", lambda: AFTER_IST_MIDNIGHT)
    utc = _body(client, "get_daily_summary", {})  # server default UTC: still the 15th
    ist = _body(client, "get_daily_summary", {"tz": "Asia/Kolkata"})  # already the 16th
    assert utc["calendarDate"] == "2026-01-15" and utc["partial"] is True
    assert ist["calendarDate"] == "2026-01-16" and ist["partial"] is True
    # For an IST user the 15th is over, even though it is still the 15th in UTC.
    past = _body(client, "get_daily_summary", {"date": "2026-01-15", "tz": "Asia/Kolkata"})
    assert past["partial"] is False

    monkeypatch.setattr(_context, "_utcnow", lambda: BEFORE_IST_MIDNIGHT)
    ist = _body(client, "get_daily_summary", {"tz": "Asia/Kolkata"})
    assert ist["calendarDate"] == "2026-01-15"
    assert route.call_count == 4


@respx.mock
def test_x_timezone_header_and_argument_precedence(client: TestClient, monkeypatch):
    monkeypatch.setattr(_context, "_utcnow", lambda: AFTER_IST_MIDNIGHT)
    _token()
    _echo_summaries()

    def summary(args: dict, headers: dict) -> dict:
        r = client.post(
            "/mcp",
            headers={
                "x-garmin-api-key": "test-key-1",
                "accept": "application/json, text/event-stream",
                **headers,
            },
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_daily_summary", "arguments": args},
            },
        )
        return json.loads(r.json()["result"]["content"][0]["text"])

    assert summary({}, {"x-timezone": "Asia/Kolkata"})["calendarDate"] == "2026-01-16"
    # The tz argument wins over the header.
    assert summary({"tz": "UTC"}, {"x-timezone": "Asia/Kolkata"})["calendarDate"] == "2026-01-15"


@respx.mock
def test_query_stats_default_end_and_partial_use_tz(client: TestClient, monkeypatch):
    monkeypatch.setattr(_context, "_utcnow", lambda: AFTER_IST_MIDNIGHT)
    _token()
    respx.get(url__startswith=f"{PERSONAL_BASE}/usersummary-service/stats/steps/").mock(
        return_value=httpx.Response(200, json=[])
    )
    body = _body(
        client, "query_stats", {"metric": "steps", "start_date": "2026-01-14", "tz": "Asia/Kolkata"}
    )
    assert body["end_date"] == "2026-01-16"
    assert [r.get("partial", False) for r in body["data"]] == [False, False, True]


@pytest.mark.parametrize("bad", ["Mars/Olympus_Mons", "../../etc/passwd", "UTC+5:30"])
@respx.mock
def test_bad_time_zone_is_a_clear_error(client: TestClient, bad: str):
    _token()
    err, text = _call(client, "get_daily_summary", {"tz": bad})
    assert err
    assert text.startswith("tz: unknown IANA time zone") and "Asia/Kolkata" in text


@respx.mock
def test_bad_x_timezone_header_is_a_clear_error(client: TestClient):
    _token()
    r = client.post(
        "/mcp",
        headers={
            "x-garmin-api-key": "test-key-1",
            "x-timezone": "Nowhere/Land",
            "accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_sleep", "arguments": {}},
        },
    )
    result = r.json()["result"]
    assert result["isError"]
    assert (
        "X-Timezone header: unknown IANA time zone 'Nowhere/Land'" in result["content"][0]["text"]
    )
