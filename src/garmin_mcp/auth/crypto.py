"""Seal pydantic claims into opaque, tamper-proof strings (AES-256-GCM).

Every OAuth artefact this server hands out (client id, authorization code, access and refresh
token, pending consent request) is one of these. The purpose prefix is bound as associated
data, so a token of one kind can never be replayed as another.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import zlib
from typing import TypeVar

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

PREFIXES = {
    "client": "gmcp_client_",
    "pending": "gmcp_req_",
    "code": "gmcp_code_",
    "access": "gmcp_at_",
    "refresh": "gmcp_rt_",
}


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Sealer:
    def __init__(self, secret: str | None):
        if not secret:
            log.warning(
                "GARMIN_MCP_SECRET is not set: using a random per-process key. OAuth clients, "
                "codes and tokens will not survive a restart or work across instances."
            )
            raw = os.urandom(32)
        else:
            raw = secret.encode()
        self._key = hashlib.sha256(b"garmin-mcp/seal/v1|" + raw).digest()
        self._mac_key = hashlib.sha256(b"garmin-mcp/mac/v1|" + raw).digest()
        self._aead = AESGCM(self._key)

    def seal(self, kind: str, claims: BaseModel) -> str:
        prefix = PREFIXES[kind]
        nonce = os.urandom(12)
        body = zlib.compress(claims.model_dump_json(exclude_none=True).encode())
        return prefix + _b64e(nonce + self._aead.encrypt(nonce, body, prefix.encode()))

    def open(self, kind: str, token: str, model: type[M]) -> M | None:
        prefix = PREFIXES[kind]
        if not token.startswith(prefix) or len(token) > 16_384:
            return None
        try:
            blob = _b64d(token[len(prefix) :])
            body = self._aead.decrypt(blob[:12], blob[12:], prefix.encode())
            return model.model_validate_json(zlib.decompress(body))
        except (InvalidTag, ValueError, ValidationError, zlib.error):
            return None

    def mac(self, value: str) -> str:
        """Deterministic secret derived from ``value`` (used as DCR client_secret)."""
        return hmac.new(self._mac_key, value.encode(), hashlib.sha256).hexdigest()
