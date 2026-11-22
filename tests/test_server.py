from __future__ import annotations

import os

import httpx
import pytest
import respx
from starlette.testclient import TestClient

# Isolate HTTPS and timezone defaults before importing the app module.
os.environ.setdefault("ALLOW_INSECURE_HTTP", "1")
os.environ.setdefault("DEFAULT_TIMEZONE", "UTC")

from garmin_mcp.garmin import PERSONAL_BASE, TOKEN_PATH  # noqa: E402
from garmin_mcp.server import (  # noqa: E402
    App,
    _check_range,
    _no_pii,
    _shift,
    _slim_activity,
    _strip_samples,
    extract_key,
)
from tests.conftest import fake_jwt
from tests.fixtures import ACTIVITY, DAILY_SUMMARY, HEART_RATE, PROFILE, SLEEP, STEPS


def test_extract_key_headers():
    assert extract_key({"X-Garmin-Api-Key": "  abc  "}) == "abc"
    assert extract_key({"authorization": "Bearer xyz"}) == "xyz"
    assert extract_key({"Authorization": "bearer xyz"}) == "xyz"
    assert extract_key({"authorization": "Basic no"}) is None
    assert extract_key({}) is None
    # Prefer the dedicated header when both are present.
    assert (
        extract_key({"x-garmin-api-key": "from-header", "authorization": "Bearer other"})
        == "from-header"
    )


def test_slim_strip_and_range():
    slim = _slim_activity(ACTIVITY)
    assert slim["activity_id"] == 1001
    assert slim["type"] == "running"
    assert slim["distance_km"] == 5.0
    assert slim["duration_min"] == 30.0
    assert "ownerFullName" not in slim
    assert "startLatitude" not in slim

    cleaned = _no_pii(ACTIVITY)
    assert "ownerFullName" not in cleaned
    assert "startLatitude" not in cleaned
    assert cleaned["activityName"] == "Morning Run"

    samples = {"heartRateValues": list(range(80)), "restingHeartRate": 52}
    stripped = _strip_samples(samples, keep=False)
    assert "omitted" in stripped["heartRateValues"]
    assert _strip_samples(samples, keep=True)["heartRateValues"] == samples["heartRateValues"]

    _check_range("2026-01-01", "2026-01-31")
    with pytest.raises(Exception, match="start_date"):
        _check_range("2026-02-01", "2026-01-01")
    with pytest.raises(Exception, match="too long"):
        _check_range("2020-01-01", "2024-01-02")
    assert _shift("2026-01-31", -1) == "2026-01-30"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_HTTP", "1")
    # A fresh App per test: StreamableHTTPSessionManager.run() can start only once.
    with TestClient(App()) as c:
        yield c


def test_info_and_healthz(client: TestClient):
    info = client.get("/").json()
    assert info["name"] == "garmin-mcp"
    assert info["stores_data"] is False
    assert client.get("/healthz").json() == {"ok": True}


def test_mcp_missing_key_is_401(client: TestClient):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    assert r.json()["error"] == "missing_garmin_api_key"
    assert "X-Garmin-Api-Key" in r.headers.get("www-authenticate", "")


@respx.mock
def test_mcp_invalid_key_is_401(client: TestClient):
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(401, text="nope"))
    r = client.post(
        "/mcp",
        headers={"x-garmin-api-key": "not-a-real-key"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_garmin_api_key"


def test_https_required_for_non_local_hosts(monkeypatch):
    monkeypatch.delenv("ALLOW_INSECURE_HTTP", raising=False)
    with TestClient(App()) as c:
        r = c.post(
            "/mcp",
            headers={"host": "example.com", "x-garmin-api-key": "k"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert r.status_code == 403
    assert r.json()["error"] == "https_required"


def _init(client: TestClient, key: str = "test-key-1"):
    return client.post(
        "/mcp",
        headers={"x-garmin-api-key": key, "accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
    )


def _call(client: TestClient, name: str, arguments: dict | None = None, key: str = "test-key-1"):
    r = client.post(
        "/mcp",
        headers={"x-garmin-api-key": key, "accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    text = result["content"][0]["text"] if result.get("content") else ""
    return result.get("isError", False), text


@respx.mock
def test_tools_list_and_get_activities(client: TestClient):
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(200, text=fake_jwt()))
    respx.get(f"{PERSONAL_BASE}/activitylist-service/activities/search/activities").mock(
        return_value=httpx.Response(200, json=[ACTIVITY])
    )
    init = _init(client)
    assert init.status_code == 200
    assert init.json()["result"]["serverInfo"]["name"] == "garmin-mcp"
    listed = client.post(
        "/mcp",
        headers={
            "authorization": "Bearer test-key-1",
            "accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    names = [t["name"] for t in listed.json()["result"]["tools"]]
    assert "get_activities" in names
    assert "query_stats" in names

    err, text = _call(client, "get_activities", {"limit": 5})
    assert not err
    body = __import__("json").loads(text)
    assert body[0]["activity_id"] == 1001
    assert body[0]["type"] == "running"
    assert "ownerFullName" not in body[0]
    assert "startLatitude" not in body[0]


@respx.mock
def test_daily_summary_and_sleep_and_stats(client: TestClient):
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(200, text=fake_jwt()))
    respx.get(f"{PERSONAL_BASE}/usersummary-service/v2/dailysummaries").mock(
        return_value=httpx.Response(200, json=DAILY_SUMMARY)
    )
    respx.get(f"{PERSONAL_BASE}/sleep-service/sleep/dailySleep").mock(
        return_value=httpx.Response(200, json=SLEEP)
    )
    respx.get(f"{PERSONAL_BASE}/wellness-service/wellness/dailyHeartRate").mock(
        return_value=httpx.Response(200, json=HEART_RATE)
    )
    respx.get(f"{PERSONAL_BASE}/usersummary-service/stats/steps/daily/2026-01-01/2026-01-15").mock(
        return_value=httpx.Response(200, json=STEPS)
    )
    respx.get(f"{PERSONAL_BASE}/userprofile-service/userprofile/settings").mock(
        return_value=httpx.Response(200, json=PROFILE)
    )
    _init(client)
    err, text = _call(client, "get_daily_summary", {"date": "2026-01-15"})
    assert not err
    assert "2100" in text or "totalKilocalories" in text
    assert "userProfilePk" not in text

    err, text = _call(client, "get_sleep", {"date": "2026-01-15"})
    assert not err
    assert "27000" in text or "sleepTimeSeconds" in text

    err, text = _call(client, "get_heart_rate", {"date": "2026-01-15"})
    assert not err
    assert "omitted" in text  # long sample array stripped by default

    err, text = _call(
        client,
        "query_stats",
        {"metric": "steps", "start_date": "2026-01-01", "end_date": "2026-01-15"},
    )
    assert not err
    assert "10234" in text

    err, text = _call(client, "get_profile")
    assert not err
    assert "example_user" in text


def test_asgi_entry_exports_the_same_app():
    from garmin_mcp.asgi import app as asgi_app
    from garmin_mcp.server import app as server_app

    assert asgi_app is server_app
