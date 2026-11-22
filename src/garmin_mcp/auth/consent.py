"""The consent page reached from ``/authorize``: the user pastes their Garmin key here."""

from __future__ import annotations

import html
from urllib.parse import urlparse

import anyio
from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from ..sdk import GarminApiError, GarminAuthError, personal_token, validate_key_shape
from ..web.render import SECURITY_HEADERS, render
from .provider import CONSENT_PATH, GarminOAuthProvider, PendingAuthorization


def _page(
    pending: PendingAuthorization, request: str, error: str = "", status: int = 200
) -> Response:
    redirect = urlparse(pending.redirect_uri)
    body = render(
        "consent.html",
        action=html.escape(CONSENT_PATH),
        client_name=html.escape(pending.client_name or "Unnamed MCP client"),
        redirect_host=html.escape(redirect.netloc or f"{redirect.scheme}:"),
        request=html.escape(request),
        error=f'<p class="error" role="alert">{html.escape(error)}</p>' if error else "",
    )
    return HTMLResponse(body, status_code=status, headers=SECURITY_HEADERS)


def _expired() -> Response:
    return HTMLResponse(
        "<!doctype html><title>Request expired</title><p>This sign-in request is invalid or has "
        "expired. Go back to your MCP client and connect again.</p>",
        status_code=400,
        headers=SECURITY_HEADERS,
    )


def consent_routes(provider: GarminOAuthProvider) -> list[Route]:
    async def show(request: Request) -> Response:
        raw = request.query_params.get("request", "")
        pending = provider.open_pending(raw)
        return _page(pending, raw) if pending else _expired()

    async def submit(request: Request) -> Response:
        form = await request.form()
        raw = str(form.get("request", ""))
        pending = provider.open_pending(raw)
        if pending is None:
            return _expired()
        if form.get("action") != "approve":
            url = construct_redirect_uri(
                pending.redirect_uri,
                error="access_denied",
                error_description="The user denied access",
                state=pending.state,
            )
            return RedirectResponse(url, status_code=303, headers=SECURITY_HEADERS)
        try:
            key = validate_key_shape(str(form.get("api_key", "")))
            await anyio.to_thread.run_sync(personal_token, key)
        except GarminAuthError:
            return _page(
                pending,
                raw,
                "Garmin did not accept that key. Check that you copied it fully and that it has "
                "not expired or been revoked.",
                status=400,
            )
        except GarminApiError:
            return _page(pending, raw, "Garmin is unreachable right now. Try again.", status=502)
        code = provider.issue_code(pending, key)
        url = construct_redirect_uri(pending.redirect_uri, code=code, state=pending.state)
        return RedirectResponse(url, status_code=303, headers=SECURITY_HEADERS)

    return [
        Route(CONSENT_PATH, show, methods=["GET"]),
        Route(CONSENT_PATH, submit, methods=["POST"]),
    ]
