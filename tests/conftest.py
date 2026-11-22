"""Shared fixtures. All Garmin HTTP is mocked; tests never need a real key."""

from __future__ import annotations

import base64
import json
import os
import time

# Deterministic settings before any garmin_mcp import.
os.environ.setdefault("ALLOW_INSECURE_HTTP", "1")
os.environ.setdefault("DEFAULT_TIMEZONE", "UTC")

import pytest  # noqa: E402

from garmin_mcp.sdk import token  # noqa: E402


def fake_jwt(exp: float | None = None) -> str:
    """Build a structurally valid unsigned JWT for unit tests (not a real token)."""

    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    payload = {"exp": int(exp if exp is not None else time.time() + 86_400), "sub": "test-user"}
    return f"{b64({'alg': 'none'})}.{b64(payload)}.sig"


@pytest.fixture(autouse=True)
def _reset_token_cache():
    token.cache.clear()
    yield
    token.cache.clear()
