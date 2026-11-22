"""Profile tools."""

from __future__ import annotations

from typing import Any

from ._context import call, source


def get_profile() -> Any:
    """Garmin profile settings (display name, units, locale). Use to check the key works."""
    return call(source().profile_settings)
