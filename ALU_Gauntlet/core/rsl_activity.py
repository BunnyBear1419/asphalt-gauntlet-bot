"""RSL activity progression and virtual-currency helpers."""
from __future__ import annotations

from math import floor, sqrt

CHAT_XP = 10
CHAT_CREDITS = 500
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
    if reward_count >= DAILY_CHAT_REWARD_CAP:
        return False
    if reward_date == today and last_reward_at is not None:
        return (now - float(last_reward_at)) >= CHAT_COOLDOWN_SECONDS
    return True
