"""The FastMCP server: read-only Garmin tools over stateless Streamable HTTP at /mcp.

Auth (HTTP): each MCP client sends ITS OWN Garmin Personal API key on every request,
``X-Garmin-Api-Key: <key>`` (preferred) or ``Authorization: Bearer <key>``. Missing or invalid
key -> 401. In stdio mode the key comes from ``GARMIN_API_KEY``. Headers are never logged.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.server.request_state import RequestStateSecurity
from starlette.applications import Starlette
from starlette.types import Receive, Scope, Send

from .apps import opening_app, register_apps
from .auth import GarminKeyGate, HttpsOnlyMiddleware
from .config import Settings, get_settings
from .tools import register_all
from .tools._errors import CleanValidationErrors
from .web.pages import MCP_PATH
from .web.pages import routes as page_routes

INSTRUCTIONS = (
    "Live, read-only access to the caller's own Garmin Connect data via the official Garmin "
    "Personal API. Nothing is cached or stored server-side; each call fetches from Garmin. "
    "Dates are YYYY-MM-DD in the user's local calendar; pass tz (IANA name) or the "
    "X-Timezone header so 'today' matches the user's day. Prefer the analytics tools "
    "(get_wellness_overview, get_trends, compare_periods, get_activity_summary, "
    "get_sleep_analysis, get_recovery_status, get_goal_streaks) with a period such as "
    "last_7d or last_30d over raw series."
)


def _request_state_security(settings: Settings) -> RequestStateSecurity | None:
    """Shared-key sealing for elicitation request_state when REQUEST_STATE_SECRET is set."""
    secret = settings.request_state_secret
    if secret is None or not secret.get_secret_value():
        return None
    if len(secret.get_secret_value().encode()) < 32:
        raise ValueError("REQUEST_STATE_SECRET must be at least 32 bytes")
    return RequestStateSecurity(keys=[secret.get_secret_value()], audience="garmin-mcp")


def create_mcp(settings: Settings | None = None) -> FastMCP:
    mcp = FastMCP(
        name="garmin-mcp",
        instructions=INSTRUCTIONS,
        request_state_security=_request_state_security(settings or get_settings()),
    )
    mcp.add_middleware(CleanValidationErrors())
    register_all(mcp, app_for=opening_app)
    register_apps(mcp)
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
