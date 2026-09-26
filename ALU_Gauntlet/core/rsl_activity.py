"""RSL activity progression and virtual-currency helpers."""
from __future__ import annotations

from math import floor, sqrt

CHAT_XP = 10
CHAT_CREDITS = 100
CHAT_COOLDOWN_SECONDS = 120
DAILY_CHAT_REWARD_CAP = 30


def activity_level(xp: int) -> int:
    """Return the player's community activity level from lifetime XP."""
    return max(1, floor(sqrt(max(0, int(xp)) / 250)) + 1)


def xp_for_level(level: int) -> int:
    """Lifetime XP required to reach a level."""
    level = max(1, int(level))
    return 250 * (level - 1) ** 2


def xp_to_next_level(xp: int) -> int:
    """Return XP still needed for the next activity level."""
    current = activity_level(xp)
    return max(0, xp_for_level(current + 1) - max(0, int(xp)))


def chat_reward_available(*, last_reward_at: float | None, reward_date: str | None,
                          today: str, reward_count: int, now: float) -> bool:
    """Pure guard used by the Discord activity listener and regression tests."""
    # The daily cap belongs to the current UTC/local guild day. A prior day's
    # count must never carry over and block today's first eligible reward.
    if reward_date != today:
        return True
    if reward_count >= DAILY_CHAT_REWARD_CAP:
        return False
    if last_reward_at is not None:
        return (now - float(last_reward_at)) >= CHAT_COOLDOWN_SECONDS
    return True


# Canonical cross-RSL activity weights used by the seasonal Top Active role.
# Inputs must already be validated/rate-limited by the event ingestion layer.
ACTIVITY_WEIGHTS = {
    "gauntlet_matches": 5,
    "tournament_matches": 5,
    "rsl_events": 3,
    "media_posts": 2,
    "defenses": 3,
    "challenges": 3,
    "approved_activity": 1,
}


def overall_activity_score(record: dict) -> int:
    """Return the deterministic overall RSL activity score for a player."""
    total = 0
    for field, weight in ACTIVITY_WEIGHTS.items():
        try:
            count = max(0, int(record.get(field, 0) or 0))
        except (TypeError, ValueError):
            count = 0
        total += count * weight
    return total


def with_overall_activity_score(record: dict) -> dict:
    """Copy an activity record and attach its canonical overall score."""
    result = dict(record)
    result["overall_activity_score"] = overall_activity_score(record)
    return result
