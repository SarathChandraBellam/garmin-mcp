"""A stateless OAuth 2.1 authorization server for the MCP endpoint.

Implements the MCP authorization spec (2025-06-18 / 2025-11-25):

* the MCP endpoint is an OAuth 2.1 protected resource and advertises
  ``/.well-known/oauth-protected-resource/mcp`` (RFC 9728) in ``WWW-Authenticate``;
* authorization server metadata at ``/.well-known/oauth-authorization-server`` (RFC 8414);
* Dynamic Client Registration at ``/register`` (RFC 7591);
* authorization code + PKCE S256 at ``/authorize`` and ``/token``, with refresh tokens;
* RFC 8707 ``resource`` indicators are carried through into the tokens.

The "login" step is a consent page where the user pastes their Garmin Personal API key. The
key is validated with Garmin and then sealed *inside* the authorization code and tokens, so the
server keeps no database: every artefact is an encrypted, expiring blob (see ``crypto``).

For backwards compatibility a raw Garmin Personal API key is also accepted as a bearer token
(or via ``X-Garmin-Api-Key``, which the middleware maps onto ``Authorization``).
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from urllib.parse import urlencode, urlparse

import anyio
from fastmcp.server.auth import AccessToken, OAuthProvider
from fastmcp.server.auth.auth import ClientRegistrationOptions, RevocationOptions
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from ..config import Settings
from ..contracts.auth import (
    AccessTokenClaims,
    AuthCodeClaims,
    ClientClaims,
    PendingAuthorization,
    RefreshTokenClaims,
)
from ..sdk import GarminApiError, GarminAuthError, personal_token
from .crypto import PREFIXES, Sealer
from .keys import GARMIN_KEY_CLAIM, SCOPE

log = logging.getLogger(__name__)

AUTH_CODE_TTL = 300
PENDING_TTL = 600
CONSENT_PATH = "/oauth/consent"
RAW_KEY_CLIENT_ID = "garmin-personal-api-key"


class GarminAuthorizationCode(AuthorizationCode):
    garmin_key: str


class GarminRefreshToken(RefreshToken):
    garmin_key: str


class _UsedCodes:
    """Best-effort single-use enforcement for codes on this instance (codes expire in 5 min)."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def claim(self, jti: str, exp: float) -> bool:
        now = time.time()
        with self._lock:
            self._seen = {k: v for k, v in self._seen.items() if v > now}
            if jti in self._seen:
                return False
            self._seen[jti] = exp
            return True


def _redirect_allowed(uri: str) -> bool:
    """MCP spec: redirect URIs must be HTTPS or loopback; private-use schemes are allowed."""
    p = urlparse(uri)
    if p.scheme == "https":
        return True
    if p.scheme == "http":
        return p.hostname in ("localhost", "127.0.0.1", "::1")
    return bool(p.scheme) and p.scheme not in ("javascript", "data", "file")


class GarminOAuthProvider(OAuthProvider):
    def __init__(self, settings: Settings):
        secret = settings.secret_key.get_secret_value() if settings.secret_key else None
        self.sealer = Sealer(secret)
        self.settings = settings
        self._used_codes = _UsedCodes()
        super().__init__(
            base_url=settings.base_url,
            service_documentation_url=settings.base_url + "/",
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
            ),
            revocation_options=RevocationOptions(enabled=False),
            required_scopes=[SCOPE],
        )

    # ------------------------------------------------------------ clients (RFC 7591)
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        claims = self.sealer.open("client", client_id, ClientClaims)
        if claims is None:
            return None
        info = OAuthClientInformationFull.model_validate(
            {**claims.metadata, "client_id": client_id, "client_id_issued_at": claims.iat}
        )
        if info.token_endpoint_auth_method not in (None, "none"):
            info.client_secret = self.sealer.mac(client_id)
        return info

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        for uri in client_info.redirect_uris or []:
            if not _redirect_allowed(str(uri)):
                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description="redirect_uris must use https, a loopback http address "
                    "or a private-use scheme",
                )
        metadata = client_info.model_dump(
            mode="json",
            exclude_none=True,
            exclude={
                "client_id",
                "client_secret",
                "client_id_issued_at",
                "client_secret_expires_at",
            },
        )
        client_id = self.sealer.seal("client", ClientClaims(metadata=metadata))
        # The SDK returns this same object to the client, so mutate it in place.
        client_info.client_id = client_id
        client_info.client_secret_expires_at = None
        if client_info.client_secret is not None:
            client_info.client_secret = self.sealer.mac(client_id)

    # ------------------------------------------------------------ authorize -> consent page
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        assert client.client_id is not None
        pending = PendingAuthorization(
            exp=time.time() + PENDING_TTL,
            client_id=client.client_id,
            client_name=client.client_name,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            state=params.state,
            scopes=params.scopes or [SCOPE],
            resource=params.resource,
        )
        request = self.sealer.seal("pending", pending)
        return f"{self.settings.base_url}{CONSENT_PATH}?{urlencode({'request': request})}"

    def open_pending(self, request: str) -> PendingAuthorization | None:
        pending = self.sealer.open("pending", request, PendingAuthorization)
        return None if pending is None or pending.expired else pending

    def issue_code(self, pending: PendingAuthorization, garmin_key: str) -> str:
        return self.sealer.seal(
            "code",
            AuthCodeClaims(
                exp=time.time() + AUTH_CODE_TTL,
                jti=secrets.token_urlsafe(16),
                client_id=pending.client_id,
                redirect_uri=pending.redirect_uri,
                redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
                code_challenge=pending.code_challenge,
                scopes=pending.scopes,
                resource=pending.resource,
                garmin_key=garmin_key,
            ),
        )

    # ------------------------------------------------------------ /token
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> GarminAuthorizationCode | None:
        c = self.sealer.open("code", authorization_code, AuthCodeClaims)
        if c is None or c.expired or c.client_id != client.client_id:
            return None
        if not self._used_codes.claim(c.jti, c.exp):
            return None
        return GarminAuthorizationCode(
            code=authorization_code,
            scopes=c.scopes,
            expires_at=c.exp,
            client_id=c.client_id,
            code_challenge=c.code_challenge,
            redirect_uri=c.redirect_uri,  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=c.redirect_uri_provided_explicitly,
            resource=c.resource,
            garmin_key=c.garmin_key,
        )

    def _tokens(
        self, client_id: str, scopes: list[str], resource: str | None, garmin_key: str
    ) -> OAuthToken:
        now = time.time()
        s = self.settings
        access = self.sealer.seal(
            "access",
            AccessTokenClaims(
                exp=now + s.access_token_ttl,
                client_id=client_id,
                scopes=scopes,
                resource=resource,
                garmin_key=garmin_key,
            ),
        )
        refresh = self.sealer.seal(
            "refresh",
            RefreshTokenClaims(
                exp=now + s.refresh_token_ttl,
                client_id=client_id,
                scopes=scopes,
                resource=resource,
                garmin_key=garmin_key,
            ),
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=s.access_token_ttl,
            refresh_token=refresh,
            scope=" ".join(scopes),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if not isinstance(authorization_code, GarminAuthorizationCode):
            raise TokenError("invalid_grant", "Unknown authorization code")
        assert client.client_id is not None
        return self._tokens(
            client.client_id,
            authorization_code.scopes,
            authorization_code.resource,
            authorization_code.garmin_key,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> GarminRefreshToken | None:
        r = self.sealer.open("refresh", refresh_token, RefreshTokenClaims)
        if r is None or r.expired or r.client_id != client.client_id:
            return None
        return GarminRefreshToken(
            token=refresh_token,
            client_id=r.client_id,
            scopes=r.scopes,
            expires_at=int(r.exp),
            garmin_key=r.garmin_key,
            resource=r.resource,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if not isinstance(refresh_token, GarminRefreshToken):
            raise TokenError("invalid_grant", "Unknown refresh token")
        if not set(scopes).issubset(refresh_token.scopes):
            raise TokenError("invalid_scope", "Requested scopes exceed the original grant")
        assert client.client_id is not None
        return self._tokens(
            client.client_id,
            scopes or refresh_token.scopes,
            refresh_token.resource,
            refresh_token.garmin_key,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # Stateless: nothing to delete. Revoke the Garmin key in Garmin Connect instead.
        return None

    # ------------------------------------------------------------ resource server side
    async def load_access_token(self, token: str) -> AccessToken | None:
        if token.startswith(PREFIXES["access"]):
            a = self.sealer.open("access", token, AccessTokenClaims)
            if a is None or a.expired:
                return None
            return AccessToken(
                token=token,
                client_id=a.client_id,
                scopes=a.scopes,
                expires_at=int(a.exp),
                resource=a.resource,
                claims={GARMIN_KEY_CLAIM: a.garmin_key},
            )
        if token.startswith("gmcp_"):
            return None  # one of our other artefacts (code, refresh, ...) is never a bearer
        return await self._raw_garmin_key(token)

    async def _raw_garmin_key(self, key: str) -> AccessToken | None:
        """Legacy path: the bearer *is* a Garmin Personal API key."""
        try:
            await anyio.to_thread.run_sync(personal_token, key)
        except GarminAuthError:
            return None
        except GarminApiError as e:
            log.warning("Garmin unavailable while validating a key: %s", e)
            return None
        return AccessToken(
            token=key,
            client_id=RAW_KEY_CLIENT_ID,
            scopes=[SCOPE],
            claims={GARMIN_KEY_CLAIM: key},
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        return await self.load_access_token(token)
