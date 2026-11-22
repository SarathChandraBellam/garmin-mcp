"""The FastMCP server: tools + stateless OAuth 2.1 auth, served over Streamable HTTP at /mcp.

Auth (HTTP): MCP clients discover ``/.well-known/oauth-protected-resource/mcp`` from the 401
challenge and sign in with OAuth 2.1 + PKCE; the user pastes their Garmin Personal API key on
the consent page. Clients may instead send the key directly as ``X-Garmin-Api-Key`` or
``Authorization: Bearer <key>``. In stdio mode the key comes from ``GARMIN_API_KEY``.
Headers are never logged.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.types import Receive, Scope, Send

from .auth import GarminOAuthProvider
from .auth.consent import consent_routes
from .auth.middleware import GarminKeyHeaderMiddleware, HttpsOnlyMiddleware
from .config import Settings, get_settings
from .tools import register_all
from .web.pages import MCP_PATH
from .web.pages import routes as page_routes

INSTRUCTIONS = (
    "Live, read-only access to the caller's own Garmin Connect data via the official Garmin "
    "Personal API. Nothing is cached or stored server-side; each call fetches from Garmin. "
    "Dates are YYYY-MM-DD in the user's local calendar."
)


def create_mcp(settings: Settings | None = None) -> FastMCP:
    settings = settings or get_settings()
    provider = GarminOAuthProvider(settings)
    mcp = FastMCP(name="garmin-mcp", instructions=INSTRUCTIONS, auth=provider)
    register_all(mcp)
    for route in [*page_routes, *consent_routes(provider)]:
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
            GarminKeyHeaderMiddleware(app), allow_insecure=self.settings.allow_insecure_http
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
