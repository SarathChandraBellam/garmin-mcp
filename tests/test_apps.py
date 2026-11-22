"""Phase 3 (#17): MCP Apps. Resources, ui metadata, the app-only tools, and a browser smoke test.

The browser test is optional: it runs when Python Playwright and a Chromium are available
(``uv run --with playwright pytest tests/test_apps.py``) and is skipped otherwise. Set
``APP_SCREENSHOTS=<dir>`` to also save a light and a dark screenshot of each app (synthetic data).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import respx
from fastmcp import Client, FastMCP

from garmin_mcp.apps import APPS, render
from garmin_mcp.config import get_settings
from garmin_mcp.server import create_mcp
from garmin_mcp.tools import _context
from tests.fake_garmin import FakeGarmin, activity

FROZEN = dt.datetime(2026, 1, 14, 20, 0, tzinfo=dt.timezone.utc)
UI_MIME = "text/html;profile=mcp-app"


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
        f = FakeGarmin().install(router)
        f.activities = [
            activity(21, "2026-01-13", "running", km=10, minutes=55),
            activity(20, "2026-01-10", "cycling", km=32, minutes=75),
            activity(19, "2026-01-06", "running", km=6, minutes=33),
        ]
        yield f


def call(server: FastMCP, name: str, args: dict[str, Any] | None = None) -> Any:
    async def go() -> Any:
        async with Client(server) as c:
            return await c.call_tool(name, args or {})

    return asyncio.run(go())


# ---- resources and metadata ----------------------------------------------------------------


def test_app_resources_are_served_as_mcp_apps(server):
    async def go() -> tuple[list, dict]:
        async with Client(server) as c:
            res = await c.list_resources()
            bodies = {str(r.uri): (await c.read_resource(r.uri))[0] for r in res}
            return res, bodies

    res, bodies = asyncio.run(go())
    uris = {str(r.uri) for r in res}
    assert uris == {spec.uri for spec in APPS}
    for r in res:
        assert r.mime_type == UI_MIME
        assert r.meta["ui"]["csp"] == {
            "connectDomains": [],
            "resourceDomains": [],
            "frameDomains": [],
        }
        body = bodies[str(r.uri)]
        assert body.mime_type == UI_MIME
        assert body.text.startswith("<!doctype html>")


@pytest.mark.parametrize("spec", APPS, ids=lambda s: s.file)
def test_app_html_is_self_contained(spec):
    html = render(spec.file)
    assert "@include" not in html
    assert "connect-src 'none'" in html and "default-src 'none'" in html
    # no CDN, no outside fetches, no data or secrets baked in
    assert not re.search(r"""(src|href)\s*=\s*["']?https?:""", html)
    assert "fetch(" not in html and "XMLHttpRequest" not in html and "WebSocket" not in html
    assert "innerHTML" not in html
    assert not re.search(r"(?i)x-garmin-api-key|bearer|apikey", html)
    assert "Bridge.init(" in html


def test_tools_carry_ui_metadata_and_stay_read_only(server):
    async def go() -> list:
        async with Client(server) as c:
            return await c.list_tools()

    tools = {t.name: t for t in asyncio.run(go())}
    assert tools["get_wellness_overview"].meta["ui"] == {
        "resourceUri": "ui://garmin/dashboard.html"
    }
    assert tools["pick_period"].meta["ui"]["resourceUri"] == "ui://garmin/period-picker.html"
    for spec in APPS:
        for fn in spec.tools:
            t = tools[fn.__name__]
            assert t.meta["ui"] == {"resourceUri": spec.uri, "visibility": ["app"]}
            assert t.annotations.read_only_hint is True
    for t in tools.values():
        assert t.annotations.read_only_hint is True, t.name
    assert "ui" not in (tools["get_sleep"].meta or {})


# ---- app-only tools ------------------------------------------------------------------------


def test_dashboard_data_has_daily_values(server, fake):
    out = call(server, "dashboard_data", {"period": "last_15d"}).structured_content
    assert out["window"]["days"] == 15
    assert all(len(m["daily"]) == 15 for m in out["metrics"])


def test_activity_page_and_detail_have_no_location(server, fake):
    page = call(server, "activity_page", {"period": "last_30d"}).structured_content
    assert [a["activity_id"] for a in page["items"]] == [21, 20, 19]
    assert page["has_more"] is False
    detail = call(server, "activity_detail", {"activity_id": 21}).structured_content
    assert detail["activity"]["activity_id"] == 21
    assert detail["hr_zone_min"] == [1.0, 10.0, 15.0, 3.0, 1.0]
    assert [s["index"] for s in detail["splits"]] == [1, 2]
    text = json.dumps([page, detail])
    for banned in ("Latitude", "Longitude", "REDACTED", "polyline"):
        assert banned not in text


def test_activity_detail_survives_missing_splits(server, fake):
    fake.splits_status = 500
    out = call(server, "activity_detail", {"activity_id": 20}).structured_content
    assert out["splits"] == [] and out["notes"]


def test_sleep_series_and_trend_data(server, fake):
    sleep = call(server, "sleep_series", {}).structured_content
    assert sleep["window"]["days"] == 30 and len(sleep["daily"]) == 30
    trend = call(server, "trend_data", {"metric": "hrv", "period_a": "last_7d"}).structured_content
    assert len(trend["a_daily"]) == len(trend["b_daily"]) == 7
    assert trend["window_b"]["end"] == "2026-01-07"


def test_pick_period_works_without_apps(server):
    r = call(server, "pick_period", {"question": "Which window?"})
    assert r.structured_content["question"] == "Which window?"
    assert "last_30d" in r.content[0].text  # a text-only client still sees the options


# ---- browser smoke test --------------------------------------------------------------------

HOST = """<!doctype html><html><body style="margin:0">
<iframe id="app" sandbox="allow-scripts" style="width:100%%;height:1400px;border:0"></iframe>
<script>
window.sent = []; window.calls = [];
const frame = document.getElementById("app");
const reply = (id, result) => frame.contentWindow.postMessage({jsonrpc: "2.0", id, result}, "*");
window.addEventListener("message", async (ev) => {
  if (ev.source !== frame.contentWindow) return;
  const m = ev.data;
  if (m.method === "ui/initialize") reply(m.id, {protocolVersion: "2026-01-26",
      hostInfo: {name: "test-host", version: "1"}, hostCapabilities: {},
      hostContext: {theme: %(theme)s}});
  else if (m.method === "ui/notifications/initialized")
    frame.contentWindow.postMessage({jsonrpc: "2.0", method: "ui/notifications/tool-result",
      params: %(initial)s}, "*");
  else if (m.method === "tools/call") {
    window.calls.push(m.params.name);
    reply(m.id, JSON.parse(await window.pyCallTool(m.params.name, JSON.stringify(m.params.arguments))));
  } else if (m.method === "ui/message") { window.sent.push(m.params); reply(m.id, {}); }
});
frame.srcdoc = %(html)s;
</script></body></html>"""

OPENING = {
    "dashboard.html": ("get_wellness_overview", {"period": "last_7d"}),
    "activities.html": ("get_activity_summary", {"period": "last_30d"}),
    "sleep.html": ("get_sleep_analysis", {"period": "last_7d"}),
    "trends.html": (
        "compare_periods",
        {"metric": "steps", "period_a": "this_month", "period_b": "last_month"},
    ),
    "period-picker.html": ("pick_period", {}),
}


def _playwright() -> Any:
    sync_api = pytest.importorskip("playwright.sync_api")
    return sync_api.sync_playwright


def _launch(p: Any) -> Any:
    exe = os.environ.get("CHROMIUM_PATH") or "/opt/pw-browsers/chromium"
    try:
        return p.chromium.launch(executable_path=exe if Path(exe).exists() else None)
    except Exception as e:  # no browser in this environment
        pytest.skip(f"Chromium not available: {e}")


def _result_json(r: Any) -> str:
    return json.dumps(
        {
            "content": [c.model_dump(mode="json") for c in r.content],
            "structuredContent": r.structured_content,
            "isError": r.is_error,
        }
    )


@pytest.mark.parametrize("spec", APPS, ids=lambda s: s.file)
def test_app_renders_in_a_browser(spec, server, fake):
    sync_playwright = _playwright()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    tool, args = OPENING[spec.file]
    initial = call(server, tool, args)

    def py_call_tool(name: str, arguments: str) -> str:
        return pool.submit(lambda: _result_json(call(server, name, json.loads(arguments)))).result()

    shots = os.environ.get("APP_SCREENSHOTS")
    with sync_playwright() as p:
        browser = _launch(p)
        for theme in ("light", "dark") if shots else ("light",):
            page = browser.new_page(viewport={"width": 760, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            page.on("console", lambda m, errors=errors: m.type == "error" and errors.append(m.text))
            outside: list[str] = []
            page.route(
                "**/*",
                lambda route, outside=outside: (
                    outside.append(route.request.url),
                    route.abort(),
                ),
            )
            page.expose_function("pyCallTool", py_call_tool)
            page.set_content(
                HOST
                % {
                    "theme": json.dumps(theme),
                    "initial": _result_json(initial).replace("</", "<\\/"),
                    # "</" would end the host's own <script> early
                    "html": json.dumps(render(spec.file)).replace("</", "<\\/"),
                }
            )
            app = page.frame_locator("#app")
            _exercise(spec.file, page, app)
            if shots:
                Path(shots).mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(Path(shots) / f"{spec.file.removesuffix('.html')}-{theme}.png"),
                    full_page=False,
                )
            assert not errors, errors
            assert not outside, outside  # CSP + no network: nothing left the iframe
            page.close()
        browser.close()
    pool.shutdown()


def _exercise(file: str, page: Any, app: Any) -> None:
    def calls() -> list[str]:
        return list(page.evaluate("window.calls"))

    if file == "dashboard.html":
        app.get_by_text("Overnight HRV").wait_for()
        app.locator("svg.chart").first.wait_for()
        app.get_by_role("radio", name="30 days").click()
        app.get_by_text("(30 days,", exact=False).wait_for()
        assert calls().count("dashboard_data") >= 2
    elif file == "activities.html":
        app.get_by_text("Running 21").wait_for()
        row = app.locator("tr.row").first
        row.focus()
        row.press("Enter")
        app.get_by_text("Heart-rate zones").wait_for()
        app.get_by_text("Zone 3").wait_for()
        assert "activity_detail" in calls()
        page.keyboard.press("Escape")
        app.locator("#drawer").wait_for(state="hidden")
        row.press("Enter")  # reopen so a screenshot shows the drawer
        app.get_by_text("Splits").wait_for()
    elif file == "sleep.html":
        app.get_by_text("Average sleep").wait_for()
        app.locator("#nights svg rect").first.wait_for()
        app.locator("#night").select_option(index=3)
        app.get_by_text("h asleep", exact=False).wait_for()
        assert "sleep_series" in calls()
    elif file == "trends.html":
        app.get_by_text("Change A", exact=False).wait_for()
        app.locator("path.line.s1").wait_for()
        assert calls()[0] == "trend_data"
    elif file == "period-picker.html":
        app.get_by_role("button", name="Last 30 days").click()
        app.get_by_text("Sent: Last 30 days").wait_for()
        sent = page.evaluate("window.sent")
        assert sent[0]["content"][0]["text"] == "Use the period last_30d (Last 30 days)."
