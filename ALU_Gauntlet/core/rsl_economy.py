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
    """Buy the next daily ticket with the Coin debit and ticket grant in one transaction.

    The production path uses the same MongoDB transaction for the daily reset,
    ticket increment, and Coin ledger entry. This prevents a crash between the
    ticket grant and Coin charge from creating a free paid ticket (or charging
    Coins without granting the ticket).
    """
    from .gauntlet_progression import FREE_DAILY_TICKETS

    guild_id, user_id, today = str(guild_id), str(user_id), str(today)
    driver_id = f"{guild_id}_{user_id}"

    client = getattr(db, "client", None)
    if client is None:
        # Lightweight/test DB compatibility. Production MongoDB uses the
        # transaction path below.
        profile = await db.drivers.find_one(
            {"_id": driver_id},
            {"gauntlet_ticket_date": 1, "gauntlet_tickets": 1,
             "gauntlet_purchased_tickets": 1, "rsl_coins": 1},
        )
        if not profile:
            return {"ok": False, "reason": "profile_not_found"}
        if profile.get("gauntlet_ticket_date") != today:
            await db.drivers.update_one(
                {"_id": driver_id},
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
        ledger = await apply_coin_transaction(
            db, guild_id=guild_id, user_id=user_id, amount=-cost,
            transaction_type="ticket_purchase",
            reference_id=f"ticket:{today}:{purchased + 1}",
            reason=f"Extra Gauntlet Ticket #{purchased + 1}",
            metadata={"date": today, "ticket_number": purchased + 1},
        )
        if not ledger.get("ok"):
            return {"ok": False, "reason": ledger.get("reason", "insufficient_coins"), "cost": cost}
        result = await db.drivers.update_one(
            {"_id": driver_id, "gauntlet_ticket_date": today,
             "gauntlet_purchased_tickets": purchased,
             "gauntlet_tickets": {"$lt": MAX_DAILY_TICKETS}},
            {"$inc": {"gauntlet_tickets": 1, "gauntlet_purchased_tickets": 1}},
        )
        if getattr(result, "modified_count", 0) != 1:
            # This compatibility path cannot use a Mongo transaction. The Coin
            # debit already succeeded, so compensate it explicitly if the
            # ticket grant lost a race or the daily state changed underneath us.
            refund = await apply_coin_transaction(
                db, guild_id=guild_id, user_id=user_id, amount=cost,
                transaction_type="ticket_purchase_refund",
                reference_id=f"ticket:{today}:{purchased + 1}:refund",
                reason=f"Refund failed Extra Gauntlet Ticket #{purchased + 1}",
                metadata={"date": today, "ticket_number": purchased + 1, "original_transaction": ledger.get("transaction_id")},
            )
            return {
                "ok": False,
                "reason": "purchase_race_or_state_changed",
                "cost": cost,
                "refunded": bool(refund.get("ok")),
                "refund_transaction_id": refund.get("transaction_id"),
            }
        return {
            "ok": True, "cost": cost, "purchased_tickets": purchased + 1,
            "tickets_remaining": min(MAX_DAILY_TICKETS, int(profile.get("gauntlet_tickets", FREE_DAILY_TICKETS) or 0) + 1),
        }

    from time import time
    now = time()
    try:
        async with await client.start_session() as session:
            async with session.start_transaction():
                profile = await db.drivers.find_one(
                    {"_id": driver_id},
                    {"gauntlet_ticket_date": 1, "gauntlet_tickets": 1,
                     "gauntlet_purchased_tickets": 1, "rsl_coins": 1},
                    session=session,
                )
                if not profile:
                    raise ValueError("profile_not_found")

                if profile.get("gauntlet_ticket_date") != today:
                    await db.drivers.update_one(
                        {"_id": driver_id},
                        {"$set": {
                            "gauntlet_ticket_date": today,
                            "gauntlet_tickets": FREE_DAILY_TICKETS,
                            "gauntlet_purchased_tickets": 0,
                            "gauntlet_refreshes": 0,
                        }},
                        session=session,
                    )
                    profile = {
                        **profile,
                        "gauntlet_ticket_date": today,
                        "gauntlet_tickets": FREE_DAILY_TICKETS,
                        "gauntlet_purchased_tickets": 0,
                        "gauntlet_refreshes": 0,
                    }

                purchased = min(MAX_PURCHASED_TICKETS, max(0, int(profile.get("gauntlet_purchased_tickets", 0) or 0)))
                cost = extra_ticket_cost(purchased)
                if cost <= 0:
                    raise ValueError("purchase_limit")

                balance = int(profile.get("rsl_coins", 0) or 0)
                if not can_afford(balance, cost):
                    raise ValueError("insufficient_coins")

                reference_id = f"ticket:{today}:{purchased + 1}"
                transaction_id = f"{guild_id}:{user_id}:{reference_id}"
                existing = await db.rsl_economy_transactions.find_one(
                    {"_id": transaction_id},
                    session=session,
                )
                if existing:
                    profile_after = await db.drivers.find_one(
                        {"_id": driver_id},
                        {"rsl_coins": 1, "gauntlet_tickets": 1, "gauntlet_purchased_tickets": 1},
                        session=session,
                    )
                    return {
                        "ok": existing.get("status") == "completed",
                        "reason": "already_processed",
                        "cost": abs(int(existing.get("amount", 0) or 0)),
                        "purchased_tickets": int((profile_after or {}).get("gauntlet_purchased_tickets", 0) or 0),
                        "tickets_remaining": int((profile_after or {}).get("gauntlet_tickets", 0) or 0),
                        "transaction_id": transaction_id,
                    }

                document = {
                    "_id": transaction_id,
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "type": "ticket_purchase",
                    "reference_id": reference_id,
                    "reason": f"Extra Gauntlet Ticket #{purchased + 1}",
                    "amount": -cost,
                    "status": "pending",
                    "created_at": now,
                    "metadata": {"date": today, "ticket_number": purchased + 1},
                }
                await db.rsl_economy_transactions.insert_one(document, session=session)

                result = await db.drivers.update_one(
                    {
                        "_id": driver_id,
                        "gauntlet_ticket_date": today,
                        "gauntlet_purchased_tickets": purchased,
                        "gauntlet_tickets": {"$lt": MAX_DAILY_TICKETS},
                        "rsl_coins": {"$gte": cost},
                    },
                    {"$inc": {
                        "gauntlet_tickets": 1,
                        "gauntlet_purchased_tickets": 1,
                        "rsl_coins": -cost,
                    }},
                    session=session,
                )
                if getattr(result, "modified_count", 0) != 1:
                    raise ValueError("purchase_race_or_state_changed")

                profile_after = await db.drivers.find_one(
                    {"_id": driver_id},
                    {"rsl_coins": 1, "gauntlet_tickets": 1},
                    session=session,
                )
                balance_after = int((profile_after or {}).get("rsl_coins", 0) or 0)
                tickets_after = int((profile_after or {}).get("gauntlet_tickets", 0) or 0)
                await db.rsl_economy_transactions.update_one(
                    {"_id": transaction_id},
                    {"$set": {
                        "status": "completed",
                        "balance_after": balance_after,
                        "completed_at": time(),
                    }},
                    session=session,
                )
    except ValueError as exc:
        return {"ok": False, "reason": str(exc), "cost": locals().get("cost", 0)}

    return {
        "ok": True,
        "cost": cost,
        "purchased_tickets": purchased + 1,
        "tickets_remaining": min(MAX_DAILY_TICKETS, tickets_after),
    }
