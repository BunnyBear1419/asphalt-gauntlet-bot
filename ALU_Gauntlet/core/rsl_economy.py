"""RSL virtual economy rules shared by Discord, web, and moderation flows.

The helpers here are deliberately pure so economy decisions can be regression-tested
without MongoDB or a live Discord session.
"""
from __future__ import annotations

from .gauntlet_progression import (
    FREE_DAILY_TICKETS,
    MAX_DAILY_TICKETS,
    MAX_PURCHASED_TICKETS,
    extra_ticket_cost,
)

# Keep automated moderation deductions meaningful but bounded.
MODERATION_PENALTIES = {
    "spam": 500,
    "swearing": 250,
    "advertising": 2_500,
    "unwanted_link": 2_500,
}
MAX_AUTOMATED_MODERATION_PENALTY_PER_INCIDENT = 2_500
MAX_AUTOMATED_MODERATION_PENALTY_PER_DAY = 10_000


def moderation_penalty(reason: str) -> int:
    """Return the bounded automatic Coin deduction for a moderation reason."""
    key = str(reason or "").strip().casefold()
    return min(
        MAX_AUTOMATED_MODERATION_PENALTY_PER_INCIDENT,
        max(0, int(MODERATION_PENALTIES.get(key, 0))),
    )


def can_afford(balance: int, cost: int) -> bool:
    """Return whether a player can spend the requested amount."""
    return max(0, int(balance or 0)) >= max(0, int(cost or 0))


def next_ticket_purchase(purchased_count: int, balance: int) -> dict:
    """Describe the next daily ticket purchase without changing state."""
    purchased = min(MAX_PURCHASED_TICKETS, max(0, int(purchased_count or 0)))
    cost = extra_ticket_cost(purchased)
    affordable = cost > 0 and can_afford(balance, cost)
    return {
        "free_tickets": FREE_DAILY_TICKETS,
        "purchased_tickets": purchased,
        "max_purchased_tickets": MAX_PURCHASED_TICKETS,
        "max_daily_tickets": MAX_DAILY_TICKETS,
        "next_cost": cost,
        "can_afford": affordable,
    }
