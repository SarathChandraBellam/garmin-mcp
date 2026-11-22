"""MCP tools and prompts, registered on the server by :func:`register_all`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.apps import AppConfig

from ..contracts import READ_ONLY
from . import activities, analytics, app_data, profile, prompts, stats, wellness

ALL_TOOLS: tuple[Callable[..., Any], ...] = (
    profile.get_profile,
    *analytics.TOOLS,
    activities.get_activities,
    activities.get_activity,
    *wellness.TOOLS,
    stats.query_stats,
    app_data.pick_period,
)
OUTPUT_MODELS = {**analytics.OUTPUT_MODELS, **app_data.OUTPUT_MODELS}


def register_all(
    mcp: FastMCP, app_for: Callable[[str], AppConfig | None] = lambda _name: None
) -> None:
    """Register the model-facing tools and prompts. ``app_for`` names the MCP App (if any)
    a tool's result opens in hosts that support Apps."""
    for fn in ALL_TOOLS:
        model = OUTPUT_MODELS.get(fn.__name__)
        mcp.tool(
            annotations=READ_ONLY,
            output_schema=model.model_json_schema() if model else None,
            app=app_for(fn.__name__),
        )(fn)
    for p in prompts.PROMPTS:
        mcp.prompt(p)


__all__ = ["ALL_TOOLS", "register_all"]
