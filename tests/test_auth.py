"""MCP authorization (OAuth 2.1 + PKCE + DCR) end to end, with Garmin mocked."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from garmin_mcp.auth.crypto import Sealer
from garmin_mcp.contracts import AccessTokenClaims
from garmin_mcp.sdk import PERSONAL_BASE, TOKEN_PATH
from garmin_mcp.server import App
from tests.conftest import fake_jwt
from tests.fixtures import PROFILE

BASE = "http://localhost"
REDIRECT = "http://127.0.0.1:33418/callback"
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


@pytest.fixture
def client():
    with TestClient(App(), base_url=BASE, follow_redirects=False) as c:
        yield c


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _register(client: TestClient, **extra) -> dict:
    r = client.post(
        "/register",
        json={
            "redirect_uris": [REDIRECT],
            "client_name": "Test Client",
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _authorize(client: TestClient, client_id: str, challenge: str) -> str:
    r = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "scope": "garmin:read",
            "resource": f"{BASE}/mcp",
        },
    )
    assert r.status_code == 302, r.text
    consent = urlparse(r.headers["location"])
    assert consent.path == "/oauth/consent"
    return parse_qs(consent.query)["request"][0]


def _consent(client: TestClient, request: str, key: str = "test-key-1", action: str = "approve"):
    return client.post(
        "/oauth/consent", data={"request": request, "api_key": key, "action": action}
    )


def _login(client: TestClient) -> tuple[dict, dict]:
    reg = _register(client)
    verifier, challenge = _pkce()
    request = _authorize(client, reg["client_id"], challenge)
    page = client.get("/oauth/consent", params={"request": request})
    assert page.status_code == 200
    assert "Test Client" in page.text and "127.0.0.1:33418" in page.text
    r = _consent(client, request)
    assert r.status_code == 303
    cb = parse_qs(urlparse(r.headers["location"]).query)
    assert cb["state"] == ["xyz"]
    tok = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": cb["code"][0],
            "redirect_uri": REDIRECT,
            "client_id": reg["client_id"],
            "code_verifier": verifier,
        },
    )
    assert tok.status_code == 200, tok.text
    return reg, tok.json()


def test_discovery_metadata(client: TestClient):
    prm = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert prm["resource"] == f"{BASE}/mcp"
    assert prm["authorization_servers"] == [f"{BASE}/"]
    assert "garmin:read" in prm["scopes_supported"]
    asm = client.get("/.well-known/oauth-authorization-server").json()
    assert asm["authorization_endpoint"] == f"{BASE}/authorize"
    assert asm["token_endpoint"] == f"{BASE}/token"
    assert asm["registration_endpoint"] == f"{BASE}/register"
    assert asm["code_challenge_methods_supported"] == ["S256"]


def test_registration_rejects_insecure_redirect(client: TestClient):
    r = client.post(
        "/register",
        json={"redirect_uris": ["http://evil.example/cb"], "token_endpoint_auth_method": "none"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_redirect_uri"


def test_registration_is_stateless(client: TestClient):
    reg = _register(client)
    assert reg["client_id"].startswith("gmcp_client_")
    # A fresh App (new process, same secret) still recognises the client.
    with TestClient(App(), base_url=BASE, follow_redirects=False) as other:
        _authorize(other, reg["client_id"], _pkce()[1])


@respx.mock
def test_full_oauth_flow_and_tool_call(client: TestClient):
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(200, text=fake_jwt()))
    respx.get(f"{PERSONAL_BASE}/userprofile-service/userprofile/settings").mock(
        return_value=httpx.Response(200, json=PROFILE)
    )
    reg, tok = _login(client)
    assert tok["token_type"] == "Bearer"
    assert tok["access_token"].startswith("gmcp_at_")
    assert tok["refresh_token"].startswith("gmcp_rt_")
    assert tok["scope"] == "garmin:read"
    assert "test-key-1" not in tok["access_token"]  # key is encrypted, not encoded

    r = client.post(
        "/mcp",
        headers={**MCP_HEADERS, "authorization": f"Bearer {tok['access_token']}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_profile", "arguments": {}},
        },
    )
    assert r.status_code == 200, r.text
    assert "example_user" in r.json()["result"]["content"][0]["text"]

    refreshed = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
            "client_id": reg["client_id"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access_token"].startswith("gmcp_at_")


@respx.mock
def test_code_is_single_use_and_bound_to_pkce(client: TestClient):
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(200, text=fake_jwt()))
    reg = _register(client)
    verifier, challenge = _pkce()
    request = _authorize(client, reg["client_id"], challenge)
    code = parse_qs(urlparse(_consent(client, request).headers["location"]).query)["code"][0]
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT,
        "client_id": reg["client_id"],
    }
    bad = client.post("/token", data={**form, "code_verifier": "x" * 50})
    assert bad.status_code == 400
    # The failed attempt consumed the code; it cannot be replayed even with the right verifier.
    again = client.post("/token", data={**form, "code_verifier": verifier})
    assert again.status_code == 400


@respx.mock
def test_consent_rejects_bad_key_and_handles_deny(client: TestClient):
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(401, text="nope"))
    reg = _register(client)
    request = _authorize(client, reg["client_id"], _pkce()[1])
    r = _consent(client, request, key="wrong")
    assert r.status_code == 400
    assert "did not accept" in r.text
    denied = _consent(client, request, action="deny")
    assert denied.status_code == 303
    assert parse_qs(urlparse(denied.headers["location"]).query)["error"] == ["access_denied"]


def test_consent_rejects_tampered_request(client: TestClient):
    r = client.get("/oauth/consent", params={"request": "gmcp_req_AAAA"})
    assert r.status_code == 400
    assert re.search("expired", r.text)


def test_sealed_tokens_are_purpose_bound():
    sealer = Sealer("s")
    claims = AccessTokenClaims(exp=9e9, client_id="c", scopes=["garmin:read"], garmin_key="k")
    token = sealer.seal("access", claims)
    assert sealer.open("access", token, AccessTokenClaims) == claims
    assert sealer.open("refresh", token, AccessTokenClaims) is None
    assert Sealer("other").open("access", token, AccessTokenClaims) is None
    assert sealer.open("access", token[:-4] + "AAAA", AccessTokenClaims) is None


def test_refresh_token_is_not_a_bearer(client: TestClient):
    sealer = Sealer("test-secret-not-for-production")
    claims = AccessTokenClaims(exp=9e9, client_id="c", scopes=["garmin:read"], garmin_key="k")
    as_refresh = sealer.seal("refresh", claims)
    r = client.post(
        "/mcp",
        headers={**MCP_HEADERS, "authorization": f"Bearer {as_refresh}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert r.status_code == 401
