"""MCP tools. Each module exposes ``register(mcp)``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from ..contracts import READ_ONLY
from . import activities, profile, stats, wellness

ALL_TOOLS: tuple[Callable[..., Any], ...] = (
    profile.get_profile,
    activities.get_activities,
    activities.get_activity,
    *wellness.TOOLS,
    stats.query_stats,
)


def register_all(mcp: FastMCP) -> None:
    for fn in ALL_TOOLS:
        mcp.tool(annotations=READ_ONLY)(fn)


__all__ = ["ALL_TOOLS", "register_all"]
