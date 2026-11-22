"""Tiny template renderer for the bundled HTML pages (stdlib only)."""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from string import Template


@cache
def _read(name: str) -> str:
    return (files(__package__) / "templates" / name).read_text(encoding="utf-8")


def render(name: str, **values: str) -> str:
    """Render ``templates/<name>``. Values are inserted verbatim: escape them first."""
    return Template(_read(name)).substitute(css=_read("base.css"), **values)


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
