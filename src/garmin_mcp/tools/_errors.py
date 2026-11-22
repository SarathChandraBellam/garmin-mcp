"""Turn argument-validation failures into short ``field: problem`` tool errors."""

from __future__ import annotations

from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from pydantic import ValidationError

_PREFIXES = ("Value error, ", "Assertion failed, ")


def format_validation_error(err: ValidationError) -> str:
    """One ``field: problem`` line per error, without Pydantic's header, input echo or docs link."""
    lines = []
    for e in err.errors(include_url=False, include_input=False):
        field = ".".join(str(p) for p in e.get("loc", ())) or "arguments"
        msg = str(e.get("msg", "invalid value"))
        for prefix in _PREFIXES:
            if msg.startswith(prefix):
                msg = msg[len(prefix) :]
        lines.append(f"{field}: {msg}")
    return "\n".join(lines) or "Invalid arguments"


class CleanValidationErrors(Middleware):
    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        try:
            return await call_next(context)
        except FastMCPValidationError as e:
            cause = e.__cause__
            if isinstance(cause, ValidationError):
                raise ToolError(format_validation_error(cause)) from None
            raise
        except ValidationError as e:
            raise ToolError(format_validation_error(e)) from None
