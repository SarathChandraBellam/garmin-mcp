"""Wellness contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TrainingReadinessProxy(BaseModel):
    """The Personal API has no Training Readiness endpoint; these are its main inputs."""

    note: str = (
        "Garmin's Personal API does not expose Training Readiness; showing its main inputs instead."
    )
    date: str
    hrv: Any = None
    sleep: Any = None
    body_battery: Any = None
