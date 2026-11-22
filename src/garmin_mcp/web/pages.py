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


async def index(_: Request) -> HTMLResponse:
    base = get_settings().base_url
    body = render(
        "index.html",
        version=html.escape(__version__),
        base_url=html.escape(base),
        mcp_url=html.escape(base + MCP_PATH),
        tools_rows=_tool_rows(),
    )
    headers = {**SECURITY_HEADERS, "Cache-Control": "public, max-age=300"}
    return HTMLResponse(body, headers=headers)


async def info(_: Request) -> JSONResponse:
    base = get_settings().base_url
    return JSONResponse(
        {
            "name": "garmin-mcp",
            "version": __version__,
            "transport": "streamable-http (stateless)",
            "endpoint": MCP_PATH,
            "auth": {
                "type": "oauth2.1",
                "protected_resource_metadata": f"{base}/.well-known/oauth-protected-resource{MCP_PATH}",
                "authorization_server_metadata": f"{base}/.well-known/oauth-authorization-server",
                "alternative": "X-Garmin-Api-Key header or Authorization: Bearer <Garmin key>",
            },
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
