"""Claims sealed inside the stateless OAuth artefacts this server issues.

Nothing here is ever written to disk or a database: each model is encrypted with the server
secret and handed to the client as an opaque string (client id, authorization code, access
token or refresh token). The server decrypts it again when the client presents it.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field


class _Expiring(BaseModel):
    exp: float

    @property
    def expired(self) -> bool:
        return self.exp < time.time()


class ClientClaims(BaseModel):
    """Dynamic Client Registration (RFC 7591) metadata, sealed into the client_id."""

    typ: Literal["client"] = "client"
    iat: int = Field(default_factory=lambda: int(time.time()))
    metadata: dict


class PendingAuthorization(_Expiring):
    """An /authorize request waiting for the user to paste their Garmin key."""

    typ: Literal["pending"] = "pending"
    client_id: str
    client_name: str | None = None
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    state: str | None = None
    scopes: list[str]
    resource: str | None = None


class AuthCodeClaims(_Expiring):
    typ: Literal["code"] = "code"
    jti: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    scopes: list[str]
    resource: str | None = None
    garmin_key: str


class AccessTokenClaims(_Expiring):
    typ: Literal["access"] = "access"
    client_id: str
    scopes: list[str]
    resource: str | None = None
    garmin_key: str


class RefreshTokenClaims(_Expiring):
    typ: Literal["refresh"] = "refresh"
    client_id: str
    scopes: list[str]
    resource: str | None = None
    garmin_key: str
