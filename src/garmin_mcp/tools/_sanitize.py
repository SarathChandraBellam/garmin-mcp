"""Output hygiene: drop owner PII / identifiers / locations and collapse long or nested arrays."""

from __future__ import annotations

from typing import Any

PII_FIELDS = frozenset(
    {
        "ownerDisplayName",
        "ownerFullName",
        "ownerId",
        "ownerProfileImageUrlLarge",
        "ownerProfileImageUrlMedium",
        "ownerProfileImageUrlSmall",
        "startLatitude",
        "startLongitude",
        "endLatitude",
        "endLongitude",
        "userProfilePK",
        "userProfilePk",
        "userProfileId",
        "userId",
        "deviceId",
        "locationName",
        "activityUUID",
    }
)
MAX_SAMPLES = 50


def no_pii(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: no_pii(v) for k, v in x.items() if k not in PII_FIELDS}
    if isinstance(x, list):
        return [no_pii(v) for v in x]
    return x


def _omitted(n: int, flag: str) -> str:
    return f"[{n} samples omitted; pass {flag}=true]"


def strip_samples(obj: Any, keep: bool = False, flag: str = "include_samples") -> Any:
    """Replace lists longer than ``MAX_SAMPLES`` with a placeholder, at any nesting depth."""
    if keep:
        return obj
    if isinstance(obj, dict):
        return {k: strip_samples(v, flag=flag) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > MAX_SAMPLES:
            return _omitted(len(obj), flag)
        return [strip_samples(v, flag=flag) for v in obj]
    return obj


def compact(obj: Any, drop: frozenset[str] = frozenset()) -> Any:
    """Compact view of one daily record: drop ``drop`` keys and nested event/sample lists.

    Lists of objects (event logs, descriptors) and long scalar lists are replaced by a
    placeholder naming their length; short scalar lists are kept.
    """
    if isinstance(obj, dict):
        return {k: compact(v, drop) for k, v in obj.items() if k not in drop}
    if isinstance(obj, list):
        if len(obj) > MAX_SAMPLES or any(isinstance(v, (dict, list)) for v in obj):
            return f"[{len(obj)} items omitted; pass raw=true]"
        return obj
    return obj


def has_data(x: Any) -> bool:
    """True if ``x`` holds at least one real measurement.

    Garmin sometimes answers with a skeleton object whose values are all null; dates, ids
    and booleans alone do not count as data.
    """
    if isinstance(x, dict):
        return any(has_data(v) for k, v in x.items() if k not in _NON_DATA_KEYS)
    if isinstance(x, list):
        return any(has_data(v) for v in x)
    if isinstance(x, bool) or x is None:
        return False
    if isinstance(x, str):
        return bool(x.strip())
    return True


_NON_DATA_KEYS = frozenset(
    {"calendarDate", "date", "summaryDate", "id", "userProfilePK", "userProfilePk"}
)
