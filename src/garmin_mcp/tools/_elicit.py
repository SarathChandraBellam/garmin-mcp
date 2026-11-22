"""Ask the user a question, using whatever the connection supports.

* **2026-07-28 clients** (stateless HTTP included): the tool returns an ``InputRequiredResult``;
  the client asks the user and calls the tool again with ``input_responses`` and the echoed,
  sealed ``request_state``. The server keeps nothing between the two calls.
* **Older clients over stdio** that declared the elicitation capability: classic ``ctx.elicit``.
* **Everyone else** (older clients over stateless HTTP, clients without elicitation): no
  question; the tool uses a sensible default and says so in a note.

``request_state`` holds only the tool's own arguments and the user's earlier answers in this
round trip, never the Garmin key, tokens or Garmin data. Never ask for secrets here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

import mcp_types as mt
from fastmcp import Context
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

log = logging.getLogger(__name__)

Mode = Literal["input_required", "push", "none"]
STATE_VERSION = 1
_SECRET_HINTS = ("key", "token", "secret", "password", "authorization")


@dataclass(frozen=True)
class Answer:
    """``status`` is accepted (``value`` holds the form), declined, or unavailable."""

    status: Literal["accepted", "declined", "unavailable"]
    value: dict[str, Any] | None = None

    @property
    def accepted(self) -> bool:
        return self.status == "accepted" and self.value is not None


def choice_schema(field: str, options: list[tuple[str, str]], title: str) -> dict[str, Any]:
    """A single-select form: ``options`` are (value, label) pairs."""
    return {
        "type": "object",
        "properties": {
            field: {
                "type": "string",
                "title": title,
                "oneOf": [{"const": v, "title": label} for v, label in options],
            }
        },
        "required": [field],
    }


def _safe_args(args: dict[str, Any]) -> dict[str, Any]:
    """Tool arguments for request_state, minus anything that could be a credential."""
    return {
        k: v
        for k, v in args.items()
        if not any(h in k.lower() for h in _SECRET_HINTS)
        and isinstance(v, (str, int, float, bool, list, type(None)))
    }


def _client_can_elicit(ctx: Context) -> bool:
    try:
        caps = ctx.session.client_capabilities
    except (RuntimeError, AttributeError):
        return False
    return caps is not None and getattr(caps, "elicitation", None) is not None


def _mode(ctx: Context) -> Mode:
    rc = ctx.request_context
    if rc is None or not _client_can_elicit(ctx):
        return "none"
    if rc.protocol_version in MODERN_PROTOCOL_VERSIONS:
        return "input_required"
    # Handshake-era push elicitation needs a back-channel; stateless JSON HTTP has none.
    return "push" if ctx.transport == "stdio" else "none"


class Elicitor:
    """Per-call question helper. Create one at the top of a tool with the tool's arguments."""

    def __init__(self, ctx: Context | None, tool: str, args: dict[str, Any]):
        self.ctx, self.tool, self.args = ctx, tool, _safe_args(args)
        self.mode: Mode = _mode(ctx) if ctx is not None else "none"
        self.answers: dict[str, dict[str, Any] | None] = {}
        if ctx is None or self.mode == "none":
            return
        state = ctx.request_state
        if state:
            try:
                parsed = json.loads(state)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and parsed.get("tool") == tool:
                self.answers.update(parsed.get("answers") or {})
        for k, r in (ctx.input_responses or {}).items():
            if isinstance(r, mt.ElicitResult):
                self.answers[k] = dict(r.content or {}) if r.action == "accept" else None

    def state(self) -> str:
        return json.dumps(
            {"v": STATE_VERSION, "tool": self.tool, "args": self.args, "answers": self.answers},
            separators=(",", ":"),
            sort_keys=True,
        )

    async def ask(
        self, key: str, message: str, schema: dict[str, Any]
    ) -> Answer | mt.InputRequiredResult:
        """The user's answer, or an ``InputRequiredResult`` the tool must return as-is."""
        if key in self.answers:
            v = self.answers[key]
            return Answer("accepted", v) if v is not None else Answer("declined")
        if self.mode == "input_required":
            return mt.InputRequiredResult(
                input_requests={
                    key: mt.ElicitRequest(
                        params=mt.ElicitRequestFormParams(message=message, requested_schema=schema)
                    )
                },
                request_state=self.state(),
            )
        if self.mode == "push" and self.ctx is not None:
            try:
                res = await self.ctx.session.elicit(
                    message=message, requested_schema=schema, related_request_id=self.ctx.request_id
                )
            except Exception as e:  # a client that advertised elicitation but cannot do it
                log.info("elicitation failed (%s); using the default", type(e).__name__)
                return Answer("unavailable")
            value = dict(res.content or {}) if res.action == "accept" else None
            self.answers[key] = value
            return Answer("accepted", value) if value is not None else Answer("declined")
        return Answer("unavailable")
