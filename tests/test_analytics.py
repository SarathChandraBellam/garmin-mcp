"""Phase 1 (#15): time windows, per-caller timezone, chunked parallel fetches, analytics tools."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import Iterator
from typing import Any

import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from garmin_mcp.analytics import recovery, sleep, streaks
from garmin_mcp.analytics.activities import roll_up
from garmin_mcp.analytics.stats import rollup_weekly, slope, summarize, trend_of
from garmin_mcp.config import get_settings
from garmin_mcp.contracts import ActivitySummary
from garmin_mcp.contracts.analytics import DayValue, SleepNight
from garmin_mcp.server import App, create_mcp
from garmin_mcp.tools import _context, _window
from garmin_mcp.tools._window import period_bounds, previous_window, resolve_window
from tests.fake_garmin import FakeGarmin, activity
from tests.test_server import _call

# Wednesday 2026-01-14, 20:00 UTC: already Thursday 2026-01-15 in Asia/Kolkata (UTC+5:30).
FROZEN = dt.datetime(2026, 1, 14, 20, 0, tzinfo=dt.timezone.utc)
TODAY = "2026-01-14"


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_context, "_utcnow", lambda: FROZEN)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[FastMCP]:
    monkeypatch.setenv("GARMIN_API_KEY", "test-key-1")
    get_settings.cache_clear()
    yield create_mcp()
    get_settings.cache_clear()


@pytest.fixture
def fake() -> Iterator[FakeGarmin]:
    with respx.mock(assert_all_called=False) as router:
        yield FakeGarmin().install(router)


def call(server: FastMCP, name: str, args: dict[str, Any] | None = None) -> Any:
    async def go() -> Any:
        async with Client(server) as c:
            return await c.call_tool(name, args or {})

    return asyncio.run(go())


# ---- windows and timezones ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "start", "end"),
    [
        ("today", "2026-01-14", "2026-01-14"),
        ("yesterday", "2026-01-13", "2026-01-13"),
        ("last_1d", "2026-01-14", "2026-01-14"),
        ("last_7d", "2026-01-08", "2026-01-14"),
        ("last_15d", "2025-12-31", "2026-01-14"),
        ("last_30d", "2025-12-16", "2026-01-14"),
        ("last_90d", "2025-10-17", "2026-01-14"),
        ("this_week", "2026-01-12", "2026-01-14"),
        ("last_week", "2026-01-05", "2026-01-11"),
        ("this_month", "2026-01-01", "2026-01-14"),
        ("last_month", "2025-12-01", "2025-12-31"),
        ("ytd", "2026-01-01", "2026-01-14"),
    ],
)
def test_period_bounds(period: str, start: str, end: str):
    s, e = period_bounds(period, dt.date(2026, 1, 14))
    assert (s.isoformat(), e.isoformat()) == (start, end)


def test_explicit_dates_win_over_period_and_period_over_default():
    w = resolve_window("last_90d", "2026-01-01", "2026-01-03", tz="UTC")
    assert (w.start, w.end, w.days, w.period) == ("2026-01-01", "2026-01-03", 3, "custom")
    w = resolve_window("last_15d", tz="UTC", default="last_7d")
    assert (w.days, w.period) == (15, "last_15d")
    w = resolve_window(None, tz="UTC", default="last_7d")
    assert (w.start, w.end, w.period) == ("2026-01-08", TODAY, "last_7d")
    # only an end date: the default period's length, ending there
    w = resolve_window(None, None, "2026-01-10", tz="UTC")
    assert (w.start, w.end) == ("2026-01-04", "2026-01-10")
    with pytest.raises(ToolError, match="start_date"):
        resolve_window(None, "2026-01-10", "2026-01-01", tz="UTC")


def test_previous_window_has_same_length():
    p = previous_window(resolve_window("last_7d", tz="UTC"))
    assert (p.start, p.end, p.days) == ("2026-01-01", "2026-01-07", 7)


def test_today_follows_the_callers_timezone():
    assert resolve_window("today", tz="UTC").start == "2026-01-14"
    assert resolve_window("today", tz="Asia/Kolkata").start == "2026-01-15"
    assert resolve_window("today", tz="America/Los_Angeles").start == "2026-01-14"
    w = resolve_window("today", tz="Asia/Kolkata")
    assert (w.timezone, w.timezone_source) == ("Asia/Kolkata", "argument")
    with pytest.raises(ToolError, match="unknown IANA time zone"):
        resolve_window("today", tz="Mars/Olympus_Mons")


@respx.mock
def test_x_timezone_header_sets_today_over_http():
    fake = FakeGarmin().install(respx)
    with TestClient(App(), base_url="http://localhost") as client:
        hdr = {"x-timezone": "Asia/Kolkata"}
        r = client.post(
            "/mcp",
            headers={
                "x-garmin-api-key": "test-key-1",
                "accept": "application/json, text/event-stream",
                **hdr,
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "query_stats",
                    "arguments": {"metric": "steps", "period": "today"},
                },
            },
        )
    body = json.loads(r.json()["result"]["content"][0]["text"])
    assert body["window"]["start"] == "2026-01-15"
    assert body["window"]["timezone_source"] == "header"
    assert fake.calls == [("steps", "2026-01-15", "2026-01-15")]
    assert body["data"][0]["partial"] is True


# ---- chunked, parallel fetches -------------------------------------------------------------


@respx.mock
def test_daily_summaries_90_days_split_into_31_day_chunks_in_parallel():
    fake = FakeGarmin(delay=0.05).install(respx)
    with TestClient(App(), base_url="http://localhost") as client:
        err, text = _call(
            client, "query_stats", {"metric": "daily_summaries", "period": "last_90d"}
        )
    assert not err, text
    body = json.loads(text)
    assert body["days"] == 90 and body["days_with_data"] == 90
    assert body["window"]["period"] == "last_90d"
    windows = sorted(c[1:] for c in fake.calls)
    assert windows == [
        ("2025-10-17", "2025-11-16"),
        ("2025-11-17", "2025-12-17"),
        ("2025-12-18", "2026-01-14"),
    ]
    assert 1 < fake.peak_in_flight <= 4


def test_overview_fetches_every_series_with_at_most_four_in_flight(server, fake):
    fake.delay = 0.03
    r = call(server, "get_wellness_overview", {"period": "last_30d"})
    assert not r.is_error
    assert 1 < fake.peak_in_flight <= 4
    # steps/stress chunked at 28 days, never above Garmin's caps
    caps = {"steps": 28, "stress": 28, "body_battery": 31, "sleep": 31, "daily": 31, "hrv": 366}
    for kind, s, e in fake.calls:
        n = (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days + 1
        assert n <= caps[kind], (kind, s, e)


# ---- pure analytics -------------------------------------------------------------------------


def test_slope_and_trend():
    assert slope([(0, 1), (1, 2), (2, 3)]) == pytest.approx(1.0)
    assert slope([(0, 1)]) is None
    assert trend_of(1.0, 10.0, 7) == "up"
    assert trend_of(-1.0, 10.0, 7) == "down"
    assert trend_of(0.001, 10.0, 7) == "flat"


def test_summarize_skips_partial_today_for_running_totals():
    dates = ["2026-01-12", "2026-01-13", TODAY]
    vals = {"2026-01-12": 8000.0, "2026-01-13": 10000.0, TODAY: 1200.0}
    s = summarize("steps", vals, dates, today=TODAY, include_daily=True)
    assert s.average == 9000 and s.days_with_data == 2 and s.missing_days == 0
    assert s.best_day and s.best_day.date == "2026-01-13"
    assert s.daily and s.daily[-1].partial is True and s.daily[-1].value == 1200
    hr = summarize("resting_hr", {"2026-01-12": 50.0, TODAY: 54.0}, dates, today=TODAY)
    assert hr.average == 52 and hr.missing_days == 1
    assert hr.best_day and hr.best_day.value == 50  # lower resting HR is better


def test_weekly_rollup_uses_mondays():
    daily = [DayValue(date=f"2026-01-{d:02d}", value=float(d)) for d in range(5, 15)]
    weeks = rollup_weekly(daily)
    assert [w.date for w in weeks] == ["2026-01-05", "2026-01-12"]
    assert weeks[0].value == 8.0  # mean of 5..11


def test_sleep_bedtime_wraps_midnight_and_debt():
    nights = [
        SleepNight(
            date="2026-01-13",
            total_h=7,
            deep_h=1,
            light_h=4,
            rem_h=2,
            need_h=8,
            bedtime="23:30",
            wake_time="07:00",
        ),
        SleepNight(
            date="2026-01-14",
            total_h=6,
            deep_h=1,
            light_h=3,
            rem_h=2,
            need_h=8,
            bedtime="00:30",
            wake_time="07:00",
        ),
    ]
    agg = sleep.analyse(nights)
    assert agg["avg_bedtime"] == "00:00"
    assert agg["bedtime_spread_min"] == 30.0
    assert agg["sleep_debt_h"] == 3.0
    assert agg["avg_total_h"] == 6.5


def test_streaks_ignore_an_unfinished_today():
    keys = ["d1", "d2", "d3", "d4", "d5"]
    vals = {"d1": 12.0, "d2": 5.0, "d3": 11.0, "d4": 10.0, "d5": 1.0}
    hit, with_data, current, longest, _ = streaks.streaks(vals, keys, 10.0, open_key="d5")
    assert (hit, with_data, current, longest) == (3, 5, 2, 2)
    _, _, current, _, _ = streaks.streaks(vals, keys, 10.0, open_key=None)
    assert current == 0


def test_recovery_combines_available_inputs():
    comps = [
        recovery.hrv_component({"status": "BALANCED", "lastNightAvg": 48}),
        recovery.sleep_component({"sleepTimeSeconds": 8 * 3600}),
        recovery.body_battery_component(None),
    ]
    score, level = recovery.combine(comps)
    assert score == pytest.approx((85 * 0.35 + 100 * 0.35) / 0.7, abs=0.1)
    assert level == "high"
    assert recovery.combine([recovery.body_battery_component(None)]) == (None, None)


def test_roll_up_groups_and_picks_longest_and_fastest():
    acts = [
        ActivitySummary.from_garmin(activity(1, "2026-01-12", "running", km=5, minutes=25)),
        ActivitySummary.from_garmin(activity(2, "2026-01-13", "running", km=10, minutes=60)),
        ActivitySummary.from_garmin(activity(3, "2026-01-06", "cycling", km=30, minutes=70)),
    ]
    totals, groups, longest, fastest = roll_up(acts, "type")
    assert totals.count == 3 and totals.distance_km == 45
    assert [g.key for g in groups] == ["running", "cycling"]  # by time spent
    assert longest and longest.activity_id == 3
    assert fastest and fastest.activity_id == 3
    _, weeks, _, _ = roll_up(acts, "week")
    assert [g.key for g in weeks] == ["2026-01-05", "2026-01-12"]


# ---- the tools over MCP ---------------------------------------------------------------------


def test_tools_have_output_schemas_and_prompts_are_listed(server):
    async def go() -> tuple[list, list]:
        async with Client(server) as c:
            return await c.list_tools(), await c.list_prompts()

    tools, prompts = asyncio.run(go())
    by = {t.name: t for t in tools}
    for name in (
        "get_wellness_overview",
        "get_trends",
        "compare_periods",
        "get_activity_summary",
        "get_sleep_analysis",
        "get_recovery_status",
        "get_goal_streaks",
    ):
        assert by[name].output_schema, name
        assert by[name].annotations.read_only_hint is True
        assert "ctx" not in by[name].input_schema["properties"]
    assert "period" in by["query_stats"].input_schema["properties"]
    assert "tz" in by["get_sleep"].input_schema["properties"]
    assert "tz" in by["get_trends"].input_schema["properties"]
    assert "timezone" not in by["get_trends"].input_schema["properties"]
    assert {p.name for p in prompts} == {
        "weekly_review",
        "sleep_coach",
        "training_load_check",
        "month_in_review",
    }


def test_wellness_overview(server, fake):
    fake.missing = {"2026-01-10"}
    r = call(server, "get_wellness_overview", {"period": "last_7d"})
    out = r.structured_content
    assert out["window"] == {
        "start": "2026-01-08",
        "end": TODAY,
        "days": 7,
        "period": "last_7d",
        "timezone": "UTC",
        "timezone_source": "default",
    }
    assert out["previous_window"]["start"] == "2026-01-01"
    m = {x["metric"]: x for x in out["metrics"]}
    assert set(m) == {"sleep_hours", "resting_hr", "hrv", "stress", "body_battery", "steps"}
    assert m["sleep_hours"]["average"] == 7.0 and m["sleep_hours"]["missing_days"] == 1
    assert m["steps"]["days_with_data"] == 5  # one missing day, today left out (partial)
    assert m["hrv"]["previous_average"] is not None and "change" in m["hrv"]
    assert "daily" not in m["steps"]  # detail=summary keeps it small
    assert r.content[0].text.startswith("2026-01-08..2026-01-14:")
    assert "999999" not in r.content[1].text


def test_wellness_overview_raw_is_pii_free(server, fake):
    r = call(server, "get_wellness_overview", {"period": "last_1d", "detail": "raw"})
    text = json.dumps(r.structured_content)
    assert "raw" in r.structured_content and "sleep" in r.structured_content["raw"]
    assert "userProfilePK" not in text and "deviceId" not in text and "999999" not in text


def test_trends_weekly_and_daily(server, fake):
    r = call(
        server,
        "get_trends",
        {
            "metrics": ["steps", "hrv"],
            "period": "last_15d",
            "detail": "daily",
            "granularity": "week",
        },
    )
    out = r.structured_content
    assert out["granularity"] == "week"
    steps = next(m for m in out["metrics"] if m["metric"] == "steps")
    assert [d["date"] for d in steps["daily"]] == ["2025-12-29", "2026-01-05", "2026-01-12"]
    assert out["compare_window"]["end"] == "2025-12-30"


def test_compare_periods_with_both_periods(server, fake):
    r = call(
        server,
        "compare_periods",
        {"metric": "resting_hr", "period_a": "this_week", "period_b": "last_week"},
    )
    out = r.structured_content
    assert (out["window_a"]["start"], out["window_b"]["start"]) == ("2026-01-12", "2026-01-05")
    assert out["a"]["average"] is not None and out["b"]["average"] is not None
    assert out["change"] == pytest.approx(out["a"]["average"] - out["b"]["average"], abs=0.01)


def test_activity_summary(server, fake):
    fake.activities = [
        activity(3, "2026-01-13", "running", km=10, minutes=60),
        activity(2, "2026-01-08", "cycling", km=30, minutes=70),
        activity(1, "2025-11-01", "running"),  # outside last_30d
    ]
    r = call(server, "get_activity_summary", {"period": "last_30d", "detail": "daily"})
    out = r.structured_content
    assert out["totals"]["count"] == 2 and out["totals"]["distance_km"] == 40
    assert out["totals"]["hr_zone_min"][2] == 30.0  # 2 x 900 s in zone 3
    assert out["longest"]["activity_id"] == 2
    assert len(out["activities"]) == 2
    assert "startLatitude" not in json.dumps(out) and "REDACTED" not in json.dumps(out)


def test_activity_summary_empty_has_a_note(server, fake):
    out = call(server, "get_activity_summary", {"period": "last_7d"}).structured_content
    assert out["totals"]["count"] == 0
    assert any("intensity minutes" in n for n in out["notes"])


def test_sleep_analysis(server, fake):
    r = call(server, "get_sleep_analysis", {"period": "last_7d", "detail": "daily"})
    out = r.structured_content
    assert out["nights"] == 7
    assert out["avg_total_h"] == 7.0 and out["avg_score"] == 80
    assert out["avg_wake_time"] == "07:00"
    assert out["sleep_debt_h"] == 7.0  # 1 h short of the 8 h need on each of 7 nights
    assert out["daily"][0]["bedtime"] in ("23:30", "00:30")
    assert out["stage_pct"]["light"] > out["stage_pct"]["deep"]


def test_recovery_status(server, fake):
    out = call(server, "get_recovery_status", {"date": "2026-01-14"}).structured_content
    assert out["date"] == "2026-01-14"
    assert {c["name"] for c in out["components"]} == {"hrv", "sleep", "body_battery"}
    assert 0 <= out["score"] <= 100 and out["level"] in ("low", "moderate", "high")
    assert any("not Garmin's Training Readiness" in n for n in out["notes"])


def test_goal_streaks_steps_uses_garmins_goal(server, fake):
    out = call(server, "get_goal_streaks", {"period": "last_15d", "detail": "daily"})
    r = out.structured_content
    assert r["goal"] == 10_000 and r["goal_source"] == "garmin" and r["unit"] == "day"
    assert r["periods_with_data"] == 15
    assert r["longest_streak"] >= r["current_streak"] >= 0
    assert r["daily"][-1]["partial"] is True


def test_goal_streaks_intensity_is_weekly(server, fake):
    r = call(
        server, "get_goal_streaks", {"metric": "intensity_minutes", "period": "last_30d"}
    ).structured_content
    assert r["unit"] == "week" and r["goal"] == 150 and r["goal_source"] == "garmin"


def test_goal_argument_wins(server, fake):
    r = call(server, "get_goal_streaks", {"goal": 5000, "period": "last_7d"}).structured_content
    assert r["goal_source"] == "argument" and r["periods_hit"] == r["periods_with_data"]


def test_prompts_render(server):
    async def go() -> Any:
        async with Client(server) as c:
            return await c.get_prompt("weekly_review", {"focus": "running"})

    res = asyncio.run(go())
    text = res.messages[0].content.text
    assert "get_wellness_overview" in text and "running" in text


def test_frozen_clock_is_timezone_aware():
    assert _window.local_today("Asia/Kolkata").isoformat() == "2026-01-15"
    assert _context.today("Asia/Kolkata") == "2026-01-15"
