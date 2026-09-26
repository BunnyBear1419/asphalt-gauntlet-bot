"""RSL virtual economy rules shared by Discord, web, and moderation flows.

The helpers here are deliberately pure so economy decisions can be regression-tested
without MongoDB or a live Discord session.
"""
from __future__ import annotations

from .rsl_economy_ledger import apply_coin_transaction
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


async def purchase_daily_ticket(db, *, guild_id: str, user_id: str, today: str) -> dict:
    """Atomically buy the next daily ticket after resetting an expired day.

    The purchase is one MongoDB update: the Coin balance must cover the
    current escalating price and fewer than five paid tickets may exist.
    """
    from .gauntlet_progression import FREE_DAILY_TICKETS

    driver_id = f"{guild_id}_{user_id}"
    profile = await db.drivers.find_one(
        {"_id": driver_id},
        {"gauntlet_ticket_date": 1, "gauntlet_tickets": 1,
         "gauntlet_purchased_tickets": 1, "rsl_coins": 1},
    )
    if not profile:
        return {"ok": False, "reason": "profile_not_found"}

    if profile.get("gauntlet_ticket_date") != today:
        await db.drivers.update_one(
            {"_id": driver_id, "gauntlet_ticket_date": {"$ne": today}},
            {"$set": {
                "gauntlet_ticket_date": today,
                "gauntlet_tickets": FREE_DAILY_TICKETS,
                "gauntlet_purchased_tickets": 0,
            }},
        )
        profile = await db.drivers.find_one(
            {"_id": driver_id},
            {"gauntlet_ticket_date": 1, "gauntlet_tickets": 1,
             "gauntlet_purchased_tickets": 1, "rsl_coins": 1},
        )

    purchased = min(MAX_PURCHASED_TICKETS, max(0, int(profile.get("gauntlet_purchased_tickets", 0) or 0)))
    cost = extra_ticket_cost(purchased)
    if cost <= 0:
        return {"ok": False, "reason": "purchase_limit", "cost": 0}
    if not can_afford(int(profile.get("rsl_coins", 0) or 0), cost):
        return {"ok": False, "reason": "insufficient_coins", "cost": cost}

    result = await db.drivers.update_one(
        {
            "_id": driver_id,
            "gauntlet_ticket_date": today,
            "gauntlet_purchased_tickets": purchased,
            "gauntlet_tickets": {"$lt": MAX_DAILY_TICKETS},
        },
        {"$inc": {"gauntlet_tickets": 1, "gauntlet_purchased_tickets": 1}},
    )
    if getattr(result, "modified_count", 0) != 1:
        return {"ok": False, "reason": "purchase_race_or_state_changed", "cost": cost}

    ledger = await apply_coin_transaction(
        db, guild_id=guild_id, user_id=user_id, amount=-cost,
        transaction_type="ticket_purchase",
        reference_id=f"ticket:{today}:{purchased + 1}",
        reason=f"Extra Gauntlet Ticket #{purchased + 1}",
        metadata={"date": today, "ticket_number": purchased + 1},
    )
    if not ledger.get("ok") or ledger.get("duplicate"):
        await db.drivers.update_one(
            {"_id": driver_id, "gauntlet_ticket_date": today, "gauntlet_purchased_tickets": purchased + 1},
            {"$inc": {"gauntlet_tickets": -1, "gauntlet_purchased_tickets": -1}},
        )
        return {"ok": False, "reason": "purchase_race_or_state_changed" if ledger.get("duplicate") else "insufficient_coins", "cost": cost}

    return {
        "ok": True, "cost": cost, "purchased_tickets": purchased + 1,
        "tickets_remaining": min(MAX_DAILY_TICKETS, int(profile.get("gauntlet_tickets", FREE_DAILY_TICKETS) or 0) + 1),
    }
