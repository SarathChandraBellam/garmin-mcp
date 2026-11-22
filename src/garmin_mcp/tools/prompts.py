"""MCP prompts: ready-made conversations that steer the model to the analytics tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from pydantic import Field

Focus = Annotated[
    str | None, Field(max_length=200, description="Anything to pay special attention to")
]


def _focus(focus: str | None) -> str:
    return f"\n\nPay special attention to: {focus.strip()}" if focus and focus.strip() else ""


def weekly_review(focus: Focus = None) -> str:
    """Review the past week: wellness, training and recovery, with two or three suggestions."""
    return (
        "Give me a short review of my past week from my Garmin data.\n"
        "1. Call get_wellness_overview with period=last_7d.\n"
        "2. Call get_activity_summary with period=last_7d.\n"
        "3. Call get_recovery_status for today.\n"
        "Summarise what went well, what slipped compared with the week before, and give two or "
        "three concrete, gentle suggestions for next week. Use the numbers from the tools; do "
        "not invent values. This is not medical advice." + _focus(focus)
    )


def sleep_coach(focus: Focus = None) -> str:
    """Coach my sleep from the last 30 nights: consistency, stages and sleep debt."""
    return (
        "Act as a supportive sleep coach using my Garmin data.\n"
        "1. Call get_sleep_analysis with period=last_30d and detail=daily.\n"
        "2. Call get_trends with metrics=[sleep_hours, sleep_score, hrv] and period=last_30d.\n"
        "Explain my bedtime and wake-time consistency, stage balance and sleep debt in plain "
        "words, point out the nights that stand out, and suggest one habit to try for the next "
        "two weeks. This is not medical advice." + _focus(focus)
    )


def training_load_check(focus: Focus = None) -> str:
    """Check whether my recent training load matches my recovery."""
    return (
        "Check my training load against my recovery.\n"
        "1. Call get_activity_summary with period=last_30d and group_by=week.\n"
        "2. Call get_trends with metrics=[hrv, resting_hr, body_battery] and period=last_30d.\n"
        "3. Call get_recovery_status for today.\n"
        "Tell me whether load is rising, steady or falling, whether recovery is keeping up, and "
        "whether today suits a hard, easy or rest day. This is not medical advice." + _focus(focus)
    )


def month_in_review(focus: Focus = None) -> str:
    """Review last month compared with the month before."""
    return (
        "Give me a month-in-review from my Garmin data.\n"
        "1. Call get_wellness_overview with period=last_month.\n"
        "2. Call get_activity_summary with period=last_month and group_by=type.\n"
        "3. Call get_goal_streaks with metric=steps and period=last_month.\n"
        "Highlight the biggest changes against the month before, my best streak, and one goal "
        "for this month." + _focus(focus)
    )


PROMPTS: tuple[Callable[..., str], ...] = (
    weekly_review,
    sleep_coach,
    training_load_check,
    month_in_review,
)
