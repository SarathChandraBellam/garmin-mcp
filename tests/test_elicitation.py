"""Phase 2 (#16): elicitation that works on stateless HTTP, with a fallback when it can't."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import Iterator
from typing import Any

import httpx2
import mcp_types as mt
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from starlette.testclient import TestClient

from garmin_mcp.config import get_settings
from garmin_mcp.server import App, create_mcp
from garmin_mcp.tools import _context, _elicit
from tests.fake_garmin import FakeGarmin, activity

FROZEN = dt.datetime(2026, 1, 14, 20, 0, tzinfo=dt.timezone.utc)
KEY = "test-key-elicit-9f3a"


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_context, "_utcnow", lambda: FROZEN)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[FastMCP]:
    monkeypatch.setenv("GARMIN_API_KEY", KEY)
    get_settings.cache_clear()
    yield create_mcp()
    get_settings.cache_clear()


@pytest.fixture
def fake() -> Iterator[FakeGarmin]:
    with respx.mock(assert_all_called=False) as router:
        yield FakeGarmin().install(router)


class Answers:
    """A scripted user: answers questions in order and records what was asked."""

    def __init__(self, *answers: Any):
        self.answers = list(answers)
        self.asked: list[tuple[str, dict]] = []

    async def __call__(self, message: str, response_type: Any, params: Any, context: Any) -> Any:
        self.asked.append((message, params.requested_schema))
        return self.answers.pop(0)


def run(server: FastMCP | Client, name: str, args: dict, user: Answers | None = None) -> Any:
    async def go() -> Any:
        client = server if isinstance(server, Client) else Client(server, elicitation_handler=user)
        async with client as c:
            return await c.call_tool(name, args)

    return asyncio.run(go())


def http_client(app: Any, user: Answers | None, key: str = KEY) -> Client:
    """A real 2026-07-28 MCP client over stateless HTTP, in-process (no sockets)."""

    def factory(headers: Any = None, timeout: Any = None, auth: Any = None, **_: Any) -> Any:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://localhost",
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    transport = StreamableHttpTransport(
        "http://localhost/mcp", headers={"x-garmin-api-key": key}, httpx_client_factory=factory
    )
    return Client(transport, elicitation_handler=user)


# ---- the round trip -------------------------------------------------------------------------


def test_compare_periods_asks_for_the_missing_period(server, fake):
    user = Answers({"period_b": "last_week"})
    r = run(server, "compare_periods", {"metric": "steps", "period_a": "this_week"}, user)
    assert len(user.asked) == 1
    message, schema = user.asked[0]
    assert "Compare" in message
    assert {o["const"] for o in schema["properties"]["period_b"]["oneOf"]} >= {
        "previous",
        "last_week",
    }
    out = r.structured_content
    assert (out["window_b"]["start"], out["window_b"]["end"]) == ("2026-01-05", "2026-01-11")
    assert out["notes"] == []


def test_declining_uses_the_default_and_says_so(server, fake):
    user = Answers(mt.ElicitResult(action="decline"))
    out = run(server, "compare_periods", {"metric": "steps"}, user).structured_content
    assert out["window_b"]["period"] == "previous_this_week"
    assert any("previous window" in n for n in out["notes"])


def test_client_without_elicitation_gets_default_plus_note(server, fake):
    out = run(server, "compare_periods", {"metric": "hrv"}, None).structured_content
    assert out["window_b"]["end"] == "2026-01-11"
    assert any("previous window" in n for n in out["notes"])


def test_plain_calls_never_ask(server, fake):
    user = Answers()  # would fail (pop from empty list) if anything were asked
    for name, args in [
        ("compare_periods", {"metric": "steps", "period_b": "previous"}),
        ("get_wellness_overview", {}),
        ("get_trends", {"metrics": ["steps"]}),
        ("get_goal_streaks", {}),
        ("get_recovery_status", {}),
        ("get_sleep_analysis", {}),
    ]:
        assert not run(server, name, args, user).is_error, name
    assert user.asked == []


def test_two_questions_in_one_call_keep_the_first_answer(server, fake, monkeypatch):
    """Timezone, then goal: request_state carries the first answer into the third round."""
    monkeypatch.delenv("DEFAULT_TIMEZONE", raising=False)
    get_settings.cache_clear()
    fake.step_goal = None
    user = Answers({"timezone": "Asia/Kolkata"}, {"goal": 8000})
    out = run(server, "get_goal_streaks", {"period": "today"}, user).structured_content
    assert [m for m, _ in user.asked][0].startswith("Which timezone")
    assert "goal" in user.asked[1][0]
    assert out["window"]["start"] == "2026-01-15"  # Kolkata's today, not UTC's
    assert out["window"]["timezone_source"] == "elicited"
    assert (out["goal"], out["goal_source"]) == (8000, "elicited")


def test_unknown_timezone_without_elicitation_assumes_default(server, fake, monkeypatch):
    monkeypatch.delenv("DEFAULT_TIMEZONE", raising=False)
    get_settings.cache_clear()
    out = run(server, "get_recovery_status", {}).structured_content
    assert out["date"] == "2026-01-14"
    assert any("Assumed timezone UTC" in n for n in out["notes"])


def test_goal_without_garmin_goal_falls_back_to_a_default(server, fake):
    fake.step_goal = None
    out = run(server, "get_goal_streaks", {"period": "last_7d"}).structured_content
    assert (out["goal"], out["goal_source"]) == (10_000, "default")


def test_which_activity(server, fake):
    fake.activities = [
        activity(11, "2026-01-13", "running", km=5),
        activity(12, "2026-01-13", "running", km=12),
    ]
    user = Answers({"activity_id": "12"})
    r = run(server, "get_activity", {"date": "2026-01-13", "activity_type": "running"}, user)
    labels = [o["title"] for o in user.asked[0][1]["properties"]["activity_id"]["oneOf"]]
    assert any("12 km" in label for label in labels)
    body = json.loads(r.content[0].text)
    assert body["activityId"] == 12
    assert "startLatitude" not in body and "ownerFullName" not in body


def test_which_activity_without_elicitation_lists_the_others(server, fake):
    fake.activities = [activity(11, "2026-01-13"), activity(12, "2026-01-13")]
    body = json.loads(run(server, "get_activity", {"date": "2026-01-13"}).content[0].text)
    assert body["activityId"] == 11
    assert [o["activity_id"] for o in body["other_matches"]] == [12]


def test_large_range_confirmation(server, fake):
    user = Answers({"choice": "shorten"})
    r = run(
        server,
        "query_stats",
        {"metric": "daily_summaries", "start_date": "2025-01-15", "end_date": "2026-01-14"},
        user,
    )
    assert "12 calls" in user.asked[0][0]
    body = json.loads(r.content[0].text)
    assert body["days"] == 31 and body["start_date"] == "2025-12-15"
    assert len(fake.calls) == 1


def test_large_overview_can_be_shortened_or_rolled_up(server, fake):
    user = Answers({"choice": "weekly"})
    out = run(
        server,
        "get_trends",
        {"metrics": ["steps", "stress", "sleep_hours"], "period": "last_90d", "detail": "daily"},
        user,
    ).structured_content
    assert len(user.asked) == 1 and "20 calls" in user.asked[0][0]  # 7 + 7 + 6 chunks
    assert out["granularity"] == "week"
    assert all(dt.date.fromisoformat(d["date"]).weekday() == 0 for d in out["metrics"][0]["daily"])


# ---- stateless HTTP ------------------------------------------------------------------------


def test_round_trip_over_stateless_http(fake):
    user = Answers({"period_b": "last_month"})
    r = run(
        http_client(App(), user), "compare_periods", {"metric": "steps", "period_a": "this_month"}
    )
    out = r.structured_content
    assert len(user.asked) == 1
    assert (out["window_b"]["start"], out["window_b"]["end"]) == ("2025-12-01", "2025-12-31")


def test_request_state_never_holds_the_key(fake, monkeypatch):
    seen: list[str] = []
    real_init = _elicit.Elicitor.__init__

    def spy(self: Any, ctx: Any, tool: str, args: dict) -> None:
        if ctx is not None and ctx.request_state:
            seen.append(ctx.request_state)
        real_init(self, ctx, tool, args)

    monkeypatch.setattr(_elicit.Elicitor, "__init__", spy)
    wire: list[bytes] = []
    app = App()

    async def recording(scope: Any, receive: Any, send: Any) -> None:
        async def capture(msg: Any) -> None:
            if msg["type"] == "http.response.body":
                wire.append(msg.get("body", b""))
            await send(msg)

        await app(scope, receive, capture)

    fake.step_goal = None
    user = Answers({"goal": 7000})
    out = run(http_client(recording, user), "get_goal_streaks", {"period": "last_7d"})
    assert out.structured_content["goal"] == 7000
    assert seen, "the retry should carry request_state"
    for state in seen:
        parsed = json.loads(state)
        assert parsed["tool"] == "get_goal_streaks" and parsed["args"]["period"] == "last_7d"
        assert KEY not in state
    assert all(KEY.encode() not in body for body in wire)
    assert any(b"requestState" in body for body in wire)


def test_state_drops_credential_like_arguments():
    el = _elicit.Elicitor(None, "t", {"period": "x", "api_key": "s3cret", "token": "t0k"})
    state = el.state()
    assert "s3cret" not in state and "t0k" not in state and '"period":"x"' in state


def test_handshake_era_http_client_gets_the_fallback(fake):
    """A 2025-06-18 client over stateless JSON HTTP has no back-channel: no question, a note."""
    with TestClient(App(), base_url="http://localhost") as client:
        r = client.post(
            "/mcp",
            headers={
                "x-garmin-api-key": KEY,
                "accept": "application/json, text/event-stream",
                "mcp-protocol-version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "compare_periods", "arguments": {"metric": "steps"}},
            },
        )
    result = r.json()["result"]
    assert result.get("resultType") != "input_required"
    out = result["structuredContent"]
    assert any("previous window" in n for n in out["notes"])
