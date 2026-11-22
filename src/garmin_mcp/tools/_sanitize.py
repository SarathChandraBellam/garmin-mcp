"""Output hygiene: drop owner PII / coordinates and collapse long sample arrays."""

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
    }
)
MAX_SAMPLES = 50


def no_pii(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: no_pii(v) for k, v in x.items() if k not in PII_FIELDS}
    if isinstance(x, list):
        return [no_pii(v) for v in x]
    return x


def strip_samples(obj: Any, keep: bool = False) -> Any:
    if keep or not isinstance(obj, dict):
        return obj
    return {
        k: (
            f"[{len(v)} samples omitted; pass include_samples=true]"
            if isinstance(v, list) and len(v) > MAX_SAMPLES
            else v
        )
        for k, v in obj.items()
    }
