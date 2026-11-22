"""The FastMCP server: read-only Garmin tools over stateless Streamable HTTP at /mcp.

Auth (HTTP): each MCP client sends ITS OWN Garmin Personal API key on every request,
``X-Garmin-Api-Key: <key>`` (preferred) or ``Authorization: Bearer <key>``. Missing or invalid
key -> 401. In stdio mode the key comes from ``GARMIN_API_KEY``. Headers are never logged.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.types import Receive, Scope, Send

from .auth import GarminKeyGate, HttpsOnlyMiddleware
from .config import Settings, get_settings
from .tools import register_all
from .web.pages import MCP_PATH
from .web.pages import routes as page_routes

INSTRUCTIONS = (
    "Live, read-only access to the caller's own Garmin Connect data via the official Garmin "
    "Personal API. Nothing is cached or stored server-side; each call fetches from Garmin. "
    "Dates are YYYY-MM-DD in the user's local calendar."
)


def create_mcp() -> FastMCP:
    mcp = FastMCP(name="garmin-mcp", instructions=INSTRUCTIONS)
    register_all(mcp)
    for route in page_routes:
        mcp.custom_route(route.path, methods=sorted(route.methods or ["GET"]))(route.endpoint)
    return mcp


mcp = create_mcp()


def build_app(server: FastMCP | None = None) -> Starlette:
    return (server or mcp).http_app(path=MCP_PATH, stateless_http=True, json_response=True)


class App:
    """ASGI entry. Uses one shared app when the host runs ASGI lifespan; otherwise (some
    serverless runtimes) builds a throwaway app per request and runs its lifespan around it."""

    def __init__(self, server: FastMCP | None = None, settings: Settings | None = None):
        self.server = server or mcp
        self.settings = settings or get_settings()
        self.shared = build_app(self.server)
        self.lifespan_started = False

    def _wrap(self, app: Any) -> Any:
        return HttpsOnlyMiddleware(
            GarminKeyGate(app, path_prefix=MCP_PATH),
            allow_insecure=self.settings.allow_insecure_http,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":

            async def rcv() -> Any:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    self.lifespan_started = True
                return msg

            return await self.shared(scope, rcv, send)
        if self.lifespan_started:
            return await self._wrap(self.shared)(scope, receive, send)
        app = build_app(self.server)
        async with app.router.lifespan_context(app):
            return await self._wrap(app)(scope, receive, send)


app = App()


def main() -> None:
    """stdio entry point (key from GARMIN_API_KEY)."""
    mcp.run()


if __name__ == "__main__":
    main()
