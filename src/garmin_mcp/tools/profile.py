"""Profile tools."""

from __future__ import annotations

from typing import Any

from ._context import call, source
from ._sanitize import no_pii


def get_profile() -> Any:
    """Garmin profile settings (display name, units, locale). Use to check the key works.

    measurementSystem is a display preference only: Garmin data values keep their native units
    (e.g. weight in grams, distance in meters).
    """
    return no_pii(call(source().profile_settings))
