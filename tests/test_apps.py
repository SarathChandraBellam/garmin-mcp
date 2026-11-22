"""Phase 3 (#17): MCP Apps. Resources, ui metadata, the app-only tools, and a browser smoke test.

The browser test is optional: it runs when Python Playwright and a Chromium are available
(``uv run --with playwright pytest tests/test_apps.py``) and is skipped otherwise. Set
``APP_SCREENSHOTS=<dir>`` to regenerate every committed image from the apps' built-in sample data
(``?demo=1``) only: per-view screenshots, compact crops, the README hero, a GIF and the OG image.
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

    # Run on a worker thread: Playwright's sync API keeps an event loop on the main thread.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, go()).result()


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


# ---- browser tests -------------------------------------------------------------------------
#
# A minimal host page embeds the app in a sandboxed iframe and speaks the MCP Apps protocol.
# Real-data tests answer tools/call from the in-process server (synthetic FakeGarmin data).
# Demo tests load the app with ?demo=1 and assert it never calls the host for data.

HOST = """<!doctype html><html><head><style>
:root { color-scheme: %(scheme)s; }
body { margin: 0; background: %(page_bg)s; }
#wrap { padding: %(pad)spx; width: %(outer)spx; }
iframe { display: block; width: 100%%; height: %(height)spx; border: 0; }
</style></head><body><div id="wrap">%(before)s<iframe id="app" %(src)s sandbox="allow-scripts"></iframe></div>
<script>
window.sent = []; window.calls = []; window.failNext = %(fail)s;
const frame = document.getElementById("app");
const reply = (id, result) => frame.contentWindow.postMessage({jsonrpc: "2.0", id, result}, "*");
window.addEventListener("message", async (ev) => {
  if (ev.source !== frame.contentWindow) return;
  const m = ev.data;
  if (m.method === "ui/initialize") reply(m.id, {protocolVersion: "2026-01-26",
      hostInfo: {name: "test-host", version: "1"}, hostCapabilities: {}, hostContext: %(context)s});
  else if (m.method === "ui/notifications/initialized" && %(initial)s)
    frame.contentWindow.postMessage({jsonrpc: "2.0", method: "ui/notifications/tool-result",
      params: %(initial)s}, "*");
  else if (m.method === "ui/notifications/size-changed" && %(autosize)s)
    frame.style.height = Math.ceil(m.params.height) + "px";
  else if (m.method === "tools/call") {
    window.calls.push(m.params.name);
    if (window.failNext > 0) {
      window.failNext--;
      reply(m.id, {isError: true, content: [{type: "text", text: "Garmin is unavailable (502)."}]});
      return;
    }
    reply(m.id, JSON.parse(await window.pyCallTool(m.params.name, JSON.stringify(m.params.arguments))));
  } else if (m.method === "ui/message") { window.sent.push(m.params); reply(m.id, {}); }
});
%(boot)s
</script></body></html>"""

APP_URL = "https://garmin-mcp.invalid/"  # reserved TLD: never resolves
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
        return p.chromium.launch(
            executable_path=exe if Path(exe).exists() else None,
            args=["--no-proxy-server"],  # the tests need no network at all
        )
    except Exception as e:  # no browser in this environment
        pytest.skip(f"Chromium not available: {e}")


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    sync_playwright = _playwright()
    with sync_playwright() as p:
        b = _launch(p)
        yield b
        b.close()


def _result_json(r: Any) -> str:
    return json.dumps(
        {
            "content": [c.model_dump(mode="json") for c in r.content],
            "structuredContent": r.structured_content,
            "isError": r.is_error,
        }
    )


def _js(value: Any) -> str:
    # "</" would end the host's own <script> early
    return json.dumps(value).replace("</", "<\\/")


class Host:
    """One host page with one app in it. ``app`` is the iframe's frame locator."""

    def __init__(
        self,
        browser: Any,
        file: str,
        *,
        width: int = 760,
        theme: str = "light",
        demo: bool = False,
        server: FastMCP | None = None,
        initial: Any = None,
        fail: int = 0,
        styles: dict[str, Any] | None = None,
        scale: int = 1,
        height: int = 900,
        autosize: bool = True,
        before: str = "",
        pad: int = 24,
        page_bg: str | None = None,
    ) -> None:
        self.errors: list[str] = []
        self.outside: list[str] = []
        self.page = browser.new_page(
            viewport={"width": width + 2 * pad, "height": height + 2 * pad},
            device_scale_factor=scale,
            color_scheme=theme,
        )
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        html = render(file)

        def route(r: Any) -> None:
            if r.request.url.startswith(APP_URL):
                r.fulfill(body=html, content_type="text/html")
            else:
                self.outside.append(r.request.url)
                r.abort()

        self.page.route("**/*", route)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        if server is not None:

            def py_call_tool(name: str, arguments: str) -> str:
                job = lambda: _result_json(call(server, name, json.loads(arguments)))  # noqa: E731
                return self.pool.submit(job).result()

            self.page.expose_function("pyCallTool", py_call_tool)
        context: dict[str, Any] = {"theme": theme, "containerDimensions": {"width": width}}
        if styles:
            context["styles"] = styles
        src, boot = "", f"frame.srcdoc = {_js(html)};"
        if demo:
            src, boot = f'src="{APP_URL}{file}?demo=1"', ""
        dark = theme == "dark"
        self.page.set_content(
            HOST
            % {
                "scheme": theme,
                "page_bg": page_bg or ("#1e1e1e" if dark else "#ffffff"),
                "pad": pad,
                "outer": width,
                "height": height,
                "before": before,
                "src": src,
                "fail": fail,
                "context": _js(context),
                "initial": _js(initial) if initial is not None else "null",
                "autosize": "true" if autosize else "false",
                "boot": boot,
            }
        )
        self.app = self.page.frame_locator("#app")

    def calls(self) -> list[str]:
        return list(self.page.evaluate("window.calls"))

    def settle(self) -> None:
        """Wait for loading to finish and animations to end (for stable screenshots)."""
        self.app.locator("main").wait_for()
        self.app.locator(".sk").first.wait_for(state="detached", timeout=10000)
        self.app.locator(".busy").first.wait_for(state="detached", timeout=10000)
        self.page.wait_for_timeout(700)

    def shot(self, path: Path, max_height: int | None = None) -> None:
        """Screenshot the app's content box (cropped to ``max_height`` CSS px if given)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        box = self.page.locator("#wrap").bounding_box()
        assert box
        height = min(box["height"], max_height) if max_height else box["height"]
        self.page.set_viewport_size(
            {"width": int(box["width"]), "height": int(box["y"] + max(height, box["height"]))}
        )
        clip = {"x": box["x"], "y": box["y"], "width": box["width"], "height": height}
        self.page.screenshot(path=str(path), clip=clip)

    def close(self) -> None:
        assert not self.errors, self.errors
        assert not self.outside, self.outside  # CSP + no network: nothing left the iframe
        self.page.close()
        self.pool.shutdown()


def _opening(server: FastMCP, file: str) -> Any:
    tool, args = OPENING[file]
    return json.loads(_result_json(call(server, tool, args)))


# ---- real (synthetic) data ----------------------------------------------------------------


@pytest.mark.parametrize("spec", APPS, ids=lambda s: s.file)
def test_app_renders_in_a_browser(spec, server, fake, browser):
    host = Host(browser, spec.file, server=server, initial=_opening(server, spec.file))
    _exercise(spec.file, host)
    host.close()


def _exercise(file: str, host: Host) -> None:
    app, page = host.app, host.page
    if file == "dashboard.html":
        app.get_by_text("Overnight HRV").wait_for()
        app.locator("svg.chart").first.wait_for()
        app.get_by_role("radio", name="Last 30 days").click()
        app.locator("#window", has_text="· 30 days vs the 30 days before").wait_for()
        assert host.calls().count("dashboard_data") >= 2
    elif file == "activities.html":
        app.get_by_text("Running 21").wait_for()
        assert app.locator("td", has_text="Running").count() >= 1  # humanised type
        row = app.locator("tr.row").first
        row.focus()
        row.press("Enter")
        app.get_by_text("Heart-rate zones").wait_for()
        app.get_by_text("Zone 3").wait_for()
        assert "activity_detail" in host.calls()
        # focus moves to the drawer heading, not the whole card
        assert app.locator("#drawer-title").evaluate("n => n === document.activeElement")
        assert app.locator("#drawer").evaluate("n => getComputedStyle(n).outlineStyle") == "none"
        page.keyboard.press("Escape")
        app.locator("#drawer").wait_for(state="hidden")
        assert row.evaluate("n => n === document.activeElement")
    elif file == "sleep.html":
        app.get_by_text("Average sleep").wait_for()
        app.locator("#nights svg rect").first.wait_for()
        app.locator("#night").select_option(index=3)
        app.locator(".night-times", has_text="asleep").wait_for()
        assert host.calls() == ["sleep_series"]
        # the window line matches the series on screen: opened with last_7d -> 7 nights
        assert "7 nights" in app.locator("#window").inner_text()
        assert app.locator("#nights svg g.colg").count() == 7
        app.get_by_role("radio", name="Last 30 days").click()
        app.locator("#window", has_text="· 30 nights").wait_for()
        assert app.locator("#nights svg g.colg").count() == 30
    elif file == "trends.html":
        app.get_by_text("Change", exact=True).wait_for()
        app.locator("path.line.s1").wait_for()
        assert host.calls()[0] == "trend_data"
        assert app.locator(".key-line.dashed").count() >= 1  # B legend swatch is dashed
        app.get_by_role("radio", name="The same length just before").click()
        page.wait_for_function("window.calls.length >= 2")
    elif file == "period-picker.html":
        first = app.get_by_role("button", name="Today")
        assert not first.evaluate("n => n === document.activeElement")  # no first-paint ring
        page.keyboard.press("Tab")
        assert first.evaluate("n => n === document.activeElement")
        page.keyboard.press("ArrowRight")
        assert app.get_by_role("button", name="Last 7 days").evaluate(
            "n => n === document.activeElement"
        )
        app.get_by_role("button", name="Last 30 days").click()
        app.get_by_text("Sent “Last 30 days” to the chat.").wait_for()
        sent = page.evaluate("window.sent")
        assert sent[0]["content"][0]["text"] == "Use the period last_30d (Last 30 days)."


def test_activities_empty_window_is_an_empty_state_not_zeros(server, fake, browser):
    fake.activities = []
    host = Host(
        browser, "activities.html", server=server, initial=_opening(server, "activities.html")
    )
    host.app.get_by_text("No activities in this range").wait_for()
    assert host.app.locator("#totals").count() == 0  # no "0 km" tiles
    assert host.app.locator("#split").is_hidden()
    host.close()


def test_sleep_without_nights_hides_legend_and_picker(server, fake, browser):
    today = FROZEN.date()
    fake.missing = {(today - dt.timedelta(days=i)).isoformat() for i in range(120)}
    host = Host(browser, "sleep.html", server=server, initial=_opening(server, "sleep.html"))
    host.app.get_by_text("No nights recorded").wait_for()
    assert host.app.locator("#legend").is_hidden()
    assert host.app.locator("#night-card").is_hidden()
    host.close()


@pytest.mark.parametrize("file", ["dashboard.html", "sleep.html", "trends.html"])
def test_tool_error_shows_retry_and_recovers(file, server, fake, browser):
    host = Host(browser, file, server=server, initial={"content": []}, fail=1)
    notice = host.app.locator(".notice.error")
    notice.wait_for()
    assert "Garmin is unavailable" in notice.inner_text()
    assert host.app.locator("#window").inner_text() == ""  # no stale "Waiting for data…"
    host.app.get_by_role("button", name="Retry").click()
    notice.wait_for(state="detached")
    host.app.locator("svg.chart").first.wait_for()
    host.close()


def test_host_styles_and_compact_width_are_applied(server, fake, browser):
    styles = {
        "variables": {
            "--color-background-secondary": "rgb(1, 2, 3)",
            "--font-sans": "Georgia, serif",
            "not-a-var": "red",
        },
        "css": {"fonts": "/* host fonts */"},
    }
    host = Host(
        browser,
        "dashboard.html",
        server=server,
        initial=_opening(server, "dashboard.html"),
        width=400,
        styles=styles,
    )
    host.app.get_by_text("Overnight HRV").wait_for()
    root = host.app.locator("html")
    assert root.get_attribute("data-size") == "compact"
    assert root.get_attribute("data-host-styles") == ""
    card = host.app.locator("article.card").first
    assert card.evaluate("n => getComputedStyle(n).backgroundColor") == "rgb(1, 2, 3)"
    assert "Georgia" in card.evaluate("n => getComputedStyle(n).fontFamily")
    assert host.app.locator("#host-fonts").count() == 1
    # 2 columns at 400px, and the page itself does not scroll sideways
    cols = host.app.locator("#tiles").evaluate("n => getComputedStyle(n).gridTemplateColumns")
    assert len(cols.split()) == 2
    assert host.app.locator("html").evaluate("n => n.scrollWidth <= n.clientWidth")
    host.close()


# ---- demo (sample-data) mode ------------------------------------------------------------------


@pytest.mark.parametrize("width", [760, 400])
@pytest.mark.parametrize("spec", APPS, ids=lambda s: s.file)
def test_demo_mode_uses_sample_data_only(spec, width, browser):
    host = Host(browser, spec.file, demo=True, width=width)
    host.app.get_by_text("Sample data").wait_for()
    host.settle()
    if spec.file == "activities.html":
        host.app.locator("tr.row").nth(1).click()
        host.app.get_by_text("Heart-rate zones").wait_for()
    if spec.file == "period-picker.html":
        host.app.get_by_role("button", name="Last 7 days").click()
        host.app.get_by_text("Sent “Last 7 days” to the chat.").wait_for()
    assert host.calls() == []  # never asks the host for data
    assert host.page.evaluate("window.sent") == []  # and never posts a chat message
    assert host.app.locator("html").evaluate("n => n.scrollWidth <= n.clientWidth")
    expected = "compact" if width < 560 else "regular"
    assert host.app.locator("html").get_attribute("data-size") == expected
    host.close()


# ---- promo assets (APP_SCREENSHOTS=<dir>) ---------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "src" / "garmin_mcp" / "web" / "static"

CHAT = """<div style="font:15px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:%(fg)s;
  max-width:%(w)spx;margin:0 0 14px">
<div style="display:flex;justify-content:flex-end;margin-bottom:14px"><div style="background:%(bubble)s;
  padding:9px 14px;border-radius:16px;max-width:75%%">How was my week? Show me my wellness dashboard.</div></div>
<div style="font-size:12px;color:%(muted)s;margin-bottom:6px">Called <code>get_wellness_overview</code></div>
<div>Here is your last week next to the week before. Tap a range to change it.</div></div>"""


# Host style variables (MCP Apps theming) for the hero, so the view sits on the host's surface.
HOST_STYLES = {
    "light": {
        "--color-background-primary": "#ffffff",
        "--color-background-secondary": "#ffffff",
        "--color-background-tertiary": "#f3f3f2",
        "--color-border-primary": "#e6e4df",
        "--color-text-primary": "#1f1f1f",
        "--color-text-secondary": "#62615d",
    },
    "dark": {
        "--color-background-primary": "#212121",
        "--color-background-secondary": "#292929",
        "--color-background-tertiary": "#333333",
        "--color-border-primary": "#3a3a3a",
        "--color-text-primary": "#ececec",
        "--color-text-secondary": "#a8a8a8",
    },
}


def _shots_dir() -> Path:
    shots = os.environ.get("APP_SCREENSHOTS")
    if not shots:
        pytest.skip("set APP_SCREENSHOTS=<dir> to regenerate the screenshots")
    return Path(shots)


def _chat(theme: str, width: int) -> str:
    dark = theme == "dark"
    return CHAT % {
        "fg": "#ececec" if dark else "#1f1f1f",
        "muted": "#9b9b9b" if dark else "#6b6b6b",
        "bubble": "#2f2f2f" if dark else "#f0f0f0",
        "w": width,
    }


def _prepare(host: Host, file: str) -> None:
    host.app.get_by_text("Sample data").wait_for()
    host.settle()
    if file == "activities.html":
        host.app.locator("tr.row").nth(1).click()
        host.app.get_by_text("Heart-rate zones").wait_for()
        host.page.wait_for_timeout(700)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("spec", APPS, ids=lambda s: s.file)
def test_screenshots(spec, theme, browser):
    out = _shots_dir()
    name = spec.file.removesuffix(".html")
    host = Host(browser, spec.file, demo=True, theme=theme, scale=2)
    _prepare(host, spec.file)
    host.shot(out / f"{name}-{theme}.png", max_height=1120)
    host.close()
    if spec.file in ("dashboard.html", "activities.html"):
        host = Host(browser, spec.file, demo=True, theme=theme, scale=2, width=400)
        _prepare(host, spec.file)
        host.shot(out / f"{name}-compact-{theme}.png", max_height=1180)
        host.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_hero_and_og_image(theme, browser):
    out = _shots_dir()
    host = Host(
        browser,
        "dashboard.html",
        demo=True,
        theme=theme,
        scale=2,
        width=800,
        pad=32,
        before=_chat(theme, 800),
        page_bg="#ffffff" if theme == "light" else "#212121",
        styles={"variables": HOST_STYLES[theme]},
    )
    _prepare(host, "dashboard.html")
    host.shot(out / f"hero-{theme}.png")
    host.shot(STATIC / f"hero-{theme}.png")
    host.close()
    if theme != "light":
        return
    page = browser.new_page(viewport={"width": 1200, "height": 630})
    page.route("**/*", lambda r: r.abort())
    page.set_content(_og_html((out / "hero-light.png").read_bytes()))
    page.wait_for_timeout(300)
    page.screenshot(path=str(STATIC / "og.png"))
    page.screenshot(path=str(out / "og.png"))
    page.close()


def _og_html(png: bytes) -> str:
    import base64

    img = base64.b64encode(png).decode()
    return f"""<!doctype html><html><body style="margin:0;width:1200px;height:630px;overflow:hidden;
background:linear-gradient(135deg,#f7f8fa,#e6f1ff);font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif">
<div style="position:absolute;left:64px;top:96px;width:500px;color:#12161c">
<div style="display:flex;align-items:center;gap:12px;font-weight:800;font-size:28px">
<span style="width:44px;height:44px;border-radius:12px;background:#0a6ce0;display:grid;place-items:center">
<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"
stroke-linejoin="round"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg></span>garmin-mcp</div>
<div style="font-size:50px;line-height:1.08;font-weight:800;letter-spacing:-.03em;margin:34px 0 20px">
Your Garmin data, inside your AI assistant.</div>
<div style="font-size:22px;color:#5b6573;line-height:1.4">Open-source MCP server with interactive views.
Official Personal API. Stores nothing.</div></div>
<img src="data:image/png;base64,{img}" style="position:absolute;right:48px;top:50%;width:580px;
transform:translateY(-50%);border-radius:18px;box-shadow:0 20px 60px rgba(16,24,40,.18)"></body></html>"""


def test_demo_gif(browser):
    out = _shots_dir()
    image = pytest.importorskip("PIL.Image")
    host = Host(
        browser, "activities.html", demo=True, width=760, height=640, autosize=False, pad=16
    )
    raw: list[tuple[bytes, int]] = []

    def grab(ms: int) -> None:
        raw.append((host.page.screenshot(), ms))

    host.app.get_by_text("Sample data").wait_for()
    host.settle()
    grab(1400)
    host.app.get_by_role("radio", name="Last 90 days").click()
    for _ in range(4):
        host.page.wait_for_timeout(110)
        grab(110)
    host.settle()
    grab(1500)
    host.app.locator("tr.row").nth(2).click()
    for _ in range(5):
        host.page.wait_for_timeout(70)
        grab(70)
    host.page.wait_for_timeout(700)
    grab(2600)
    host.close()
    import io

    frames = [
        image.open(io.BytesIO(png))
        .convert("RGB")
        .quantize(colors=256, method=2, dither=image.Dither.NONE)
        for png, _ in raw
    ]
    frames[0].save(
        out / "demo.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[ms for _, ms in raw],
        loop=0,
        optimize=True,
    )
