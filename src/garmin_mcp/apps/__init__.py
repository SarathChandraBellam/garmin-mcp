"""MCP Apps (``io.modelcontextprotocol/ui``): interactive views for MCP hosts that support them.

Each app is one static, self-contained HTML file bundled in this package (vanilla JS, an
inlined chart helper, no CDN). Its CSP blocks all outside network access; the app gets its data
only through the host's ``tools/call``, which reuses the caller's connection and key header, so
the server stays stateless. The HTML never contains a key, a token or user data.

Clients without Apps support ignore the ``ui`` metadata and get the tools' typed output and
text summary as before.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, ResourceCSP
from pydantic import BaseModel

from ..contracts import READ_ONLY
from ..contracts.analytics import SleepAnalysis, WellnessOverview
from ..tools import app_data

_INCLUDE = re.compile(r"/\*@include:([\w.\-]+)\*/")


@dataclass(frozen=True)
class AppSpec:
    file: str
    title: str
    description: str
    opening: tuple[str, ...]  # model-facing tools whose results open this app
    tools: tuple[Callable[..., Any], ...]  # tools only this app calls

    @property
    def uri(self) -> str:
        return f"ui://garmin/{self.file}"


APPS: tuple[AppSpec, ...] = (
    AppSpec(
        "dashboard.html",
        "Wellness dashboard",
        "Body Battery ring, sleep chart, KPI tiles and a 1/7/15/30/90-day switcher.",
        ("get_wellness_overview",),
        (app_data.dashboard_data,),
    ),
    AppSpec(
        "activities.html",
        "Activity explorer",
        "Totals, time per type, an activity list and details with HR zones and splits (no maps).",
        ("get_activity_summary",),
        (app_data.activity_page, app_data.activity_detail),
    ),
    AppSpec(
        "sleep.html",
        "Sleep view",
        "Sleep score, bedtime, stages per night for 7/30/90 nights, and one night in detail.",
        ("get_sleep_analysis",),
        (app_data.sleep_series,),
    ),
    AppSpec(
        "trends.html",
        "Trend compare",
        "Two windows of one metric, lined up by day, with the change.",
        ("compare_periods", "get_trends"),
        (app_data.trend_data,),
    ),
    AppSpec(
        "period-picker.html",
        "Period picker",
        "Click a time window instead of typing it.",
        ("pick_period",),
        (),
    ),
)

APP_TOOL_MODELS: dict[str, type[BaseModel]] = {
    **app_data.OUTPUT_MODELS,
    "dashboard_data": WellnessOverview,
    "sleep_series": SleepAnalysis,
}

# Empty CSP declarations: the host allows no outside origins for connect/resource/frame.
APP_CSP = ResourceCSP(connect_domains=[], resource_domains=[], frame_domains=[])


def _read(name: str) -> str:
    return (files(__package__) / "templates" / name).read_text(encoding="utf-8")


@cache
def render(name: str) -> str:
    """The app's HTML with its shared CSS/JS includes inlined (recursively)."""

    def expand(text: str, depth: int = 0) -> str:
        if depth > 3:
            raise ValueError("include nesting too deep")
        return _INCLUDE.sub(lambda m: expand(_read(m.group(1)), depth + 1), text)

    return expand(_read(name))


def opening_app(tool_name: str) -> AppConfig | None:
    """``ui`` metadata for a model-facing tool whose result opens an app."""
    for spec in APPS:
        if tool_name in spec.opening:
            return AppConfig(resource_uri=spec.uri)
    return None


def _page(name: str) -> Callable[[], str]:
    def page() -> str:
        return render(name)

    page.__name__ = name.removesuffix(".html").replace("-", "_") + "_app"
    return page


def register_apps(mcp: FastMCP) -> None:
    for spec in APPS:
        mcp.resource(
            spec.uri,
            name=spec.file.removesuffix(".html"),
            title=spec.title,
            description=spec.description,
            app=AppConfig(csp=APP_CSP, prefers_border=True),
        )(_page(spec.file))
        for fn in spec.tools:
            model = APP_TOOL_MODELS.get(fn.__name__)
            mcp.tool(
                annotations=READ_ONLY,
                output_schema=model.model_json_schema() if model else None,
                app=AppConfig(resource_uri=spec.uri, visibility=["app"]),
            )(fn)


APP_TOOLS: tuple[Callable[..., Any], ...] = tuple(fn for spec in APPS for fn in spec.tools)

__all__ = ["APPS", "APP_TOOLS", "opening_app", "register_apps", "render"]
