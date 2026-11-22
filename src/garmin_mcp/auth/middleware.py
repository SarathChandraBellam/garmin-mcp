"""ASGI middleware that runs in front of the Starlette app."""

from __future__ import annotations

import json
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from .keys import KEY_HEADER

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")


class GarminKeyHeaderMiddleware:
    """Map ``X-Garmin-Api-Key`` onto ``Authorization: Bearer`` so one verifier handles both."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = list(scope["headers"])
            names = {k.lower() for k, _ in headers}
            if b"authorization" not in names:
                for k, v in headers:
                    if k.lower() == KEY_HEADER.encode() and v.strip():
                        headers.append((b"authorization", b"Bearer " + v.strip()))
                        scope = {**scope, "headers": headers}
                        break
        await self.app(scope, receive, send)


class HttpsOnlyMiddleware:
    """403 for plain-HTTP requests from non-loopback hosts (keys must never cross in clear)."""

    def __init__(self, app: ASGIApp, allow_insecure: bool, exempt: tuple[str, ...] = ("/healthz",)):
        self.app, self.allow_insecure, self.exempt = app, allow_insecure, exempt

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.allow_insecure or scope["path"] in self.exempt:
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        scheme = str(scope.get("scheme") or "http")
        proto = headers.get("x-forwarded-proto", scheme).split(",")[0].strip()
        if proto != "https" and host not in LOCAL_HOSTS:
            return await send_json(send, 403, {"error": "https_required"})
        await self.app(scope, receive, send)


async def send_json(send: Send, status: int, body: dict[str, Any]) -> None:
    data = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(data)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": data})
