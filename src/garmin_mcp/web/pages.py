"""Public pages: product landing page, JSON info and health check."""

from __future__ import annotations

import html
import inspect

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .. import __version__
from ..config import get_settings
from ..tools import ALL_TOOLS
from .render import SECURITY_HEADERS, render

MCP_PATH = "/mcp"


def _tool_rows() -> str:
    rows = []
    for fn in ALL_TOOLS:
        doc = inspect.getdoc(fn) or ""
        summary = doc.split(". ")[0].rstrip(".").replace("`", "") + "."
        rows.append(
            f"            <tr><td><code>{html.escape(fn.__name__)}</code></td>"
            f"<td>{html.escape(summary)}</td></tr>"
        )
    return "\n".join(rows)


def _base_url(request: Request) -> str:
    configured = get_settings().public_base_url
    return (configured or str(request.base_url)).rstrip("/")


async def index(request: Request) -> HTMLResponse:
    base = _base_url(request)
    body = render(
        "index.html",
        version=html.escape(__version__),
        mcp_url=html.escape(base + MCP_PATH),
        tools_rows=_tool_rows(),
    )
    headers = {**SECURITY_HEADERS, "Cache-Control": "public, max-age=300"}
    return HTMLResponse(body, headers=headers)


async def info(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "name": "garmin-mcp",
            "version": __version__,
            "transport": "streamable-http (stateless)",
            "endpoint": MCP_PATH,
            "auth": "send your own Garmin Personal API key in header X-Garmin-Api-Key "
            "(or Authorization: Bearer <key>)",
            "stores_data": False,
        }
    )


async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


routes = [
    Route("/", index, methods=["GET"]),
    Route("/info", info, methods=["GET"]),
    Route("/healthz", healthz, methods=["GET"]),
]
