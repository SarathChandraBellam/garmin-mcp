"""ASGI middleware in front of the Starlette app: HTTPS-only and the Garmin API-key gate.

Auth model (like a GitHub personal access token): every MCP request carries the caller's own
Garmin Personal API key, ``X-Garmin-Api-Key: <key>`` or ``Authorization: Bearer <key>``.
The server holds no keys. Headers are never logged.
"""

from __future__ import annotations

import anyio
from starlette.types import ASGIApp, Receive, Scope, Send

from ..contracts import AuthErrorBody
from ..sdk import GarminApiError, GarminAuthError, personal_token
from .keys import CREATE_KEY_URL, extract_key

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")


def _headers(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}


class HttpsOnlyMiddleware:
    """403 for plain-HTTP requests from non-loopback hosts (keys must never cross in clear)."""

    def __init__(self, app: ASGIApp, allow_insecure: bool, exempt: tuple[str, ...] = ("/healthz",)):
        self.app, self.allow_insecure, self.exempt = app, allow_insecure, exempt

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.allow_insecure or scope["path"] in self.exempt:
            return await self.app(scope, receive, send)
        headers = _headers(scope)
        host = headers.get("host", "")
        host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        scheme = str(scope.get("scheme") or "http")
        proto = headers.get("x-forwarded-proto", scheme).split(",")[0].strip()
        if proto != "https" and host not in LOCAL_HOSTS:
            return await send_error(send, 403, AuthErrorBody(error="https_required"))
        await self.app(scope, receive, send)


class GarminKeyGate:
    """Reject MCP requests without a valid Garmin key: 401 missing/invalid, 502/429 Garmin down.

    A valid key is exchanged for a Garmin token here, which also warms the in-memory cache the
    tools use for the rest of the request.
    """

    def __init__(self, app: ASGIApp, path_prefix: str = "/mcp"):
        self.app, self.prefix = app, path_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not scope["path"].startswith(self.prefix)
            or scope["method"] == "OPTIONS"
        ):
            return await self.app(scope, receive, send)
        key = extract_key(_headers(scope))
        if not key:
            return await send_error(
                send,
                401,
                AuthErrorBody(
                    error="missing_garmin_api_key",
                    error_description="Send your Garmin Personal API key in the X-Garmin-Api-Key "
                    f"header (or Authorization: Bearer <key>). Create one at {CREATE_KEY_URL}",
                ),
            )
        try:
            await anyio.to_thread.run_sync(personal_token, key)
        except GarminAuthError as e:
            return await send_error(
                send, 401, AuthErrorBody(error="invalid_garmin_api_key", error_description=str(e))
            )
        except GarminApiError as e:
            status = 429 if e.status == 429 else 502
            return await send_error(
                send, status, AuthErrorBody(error="garmin_unavailable", error_description=str(e))
            )
        await self.app(scope, receive, send)


async def send_error(send: Send, status: int, body: AuthErrorBody) -> None:
    data = body.model_dump_json(exclude_none=True).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(data)).encode()),
        (b"cache-control", b"no-store"),
    ]
    if status == 401:
        headers.append((b"www-authenticate", b'Bearer realm="garmin-mcp"'))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": data})
