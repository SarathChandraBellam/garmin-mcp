from __future__ import annotations

import httpx
import pytest
import respx

from garmin_mcp.sdk import (
    PERSONAL_BASE,
    TOKEN_PATH,
    GarminApiError,
    GarminAuthError,
    PersonalApi,
    key_fingerprint,
    personal_token,
)
from garmin_mcp.sdk.token import _jwt_exp
from tests.conftest import fake_jwt
from tests.fixtures import ACTIVITY, PROFILE


def test_jwt_exp_and_fingerprint():
    tok = fake_jwt(exp=1_800_000_000)
    assert _jwt_exp(tok) == 1_800_000_000
    assert _jwt_exp("not-a-jwt") == 0.0
    assert len(key_fingerprint("abc")) == 64
    assert key_fingerprint("abc") != key_fingerprint("abd")


@pytest.mark.parametrize("bad", ["", "   ", "a" * 5000, "line\nbreak"])
def test_personal_token_rejects_bad_keys(bad: str):
    with pytest.raises(GarminAuthError):
        personal_token(bad)


@respx.mock
def test_personal_token_success_and_cache():
    route = respx.post(PERSONAL_BASE + TOKEN_PATH).mock(
        return_value=httpx.Response(200, text=fake_jwt())
    )
    t1 = personal_token("test-key-1")
    t2 = personal_token("test-key-1")
    assert t1 == t2
    assert route.call_count == 1  # second call served from memory


@respx.mock
def test_personal_token_invalid_key():
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(401, text="nope"))
    with pytest.raises(GarminAuthError, match="rejected"):
        personal_token("expired-key")


@respx.mock
def test_personal_token_rate_limit():
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(429, text="slow"))
    with pytest.raises(GarminApiError) as exc:
        personal_token("test-key-1")
    assert exc.value.status == 429


@respx.mock
def test_personal_api_get_and_401_retry():
    token_route = respx.post(PERSONAL_BASE + TOKEN_PATH).mock(
        return_value=httpx.Response(200, text=fake_jwt())
    )
    path = "/userprofile-service/userprofile/settings"
    data_route = respx.get(PERSONAL_BASE + path).mock(
        side_effect=[
            httpx.Response(401, text="expired"),
            httpx.Response(200, json=PROFILE),
        ]
    )
    api = PersonalApi("test-key-1")
    assert api.profile_settings() == PROFILE
    assert token_route.call_count == 2  # initial + forced refresh after 401
    assert data_route.call_count == 2


@respx.mock
def test_personal_api_activities_and_empty():
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(200, text=fake_jwt()))
    respx.get(f"{PERSONAL_BASE}/activitylist-service/activities/search/activities").mock(
        return_value=httpx.Response(200, json=[ACTIVITY])
    )
    respx.get(f"{PERSONAL_BASE}/hrv-service/hrv/2026-01-15").mock(return_value=httpx.Response(204))
    api = PersonalApi("test-key-1")
    assert api.activities(limit=1)[0]["activityId"] == 1001
    assert api.hrv("2026-01-15") is None


@respx.mock
def test_personal_api_rate_limit_on_get():
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(200, text=fake_jwt()))
    respx.get(f"{PERSONAL_BASE}/userprofile-service/userprofile/settings").mock(
        return_value=httpx.Response(429, text="slow")
    )
    with pytest.raises(GarminApiError) as exc:
        PersonalApi("test-key-1").profile_settings()
    assert exc.value.status == 429
