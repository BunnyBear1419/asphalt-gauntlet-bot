"""RSL Gauntlet settlement recovery helpers.

Recovery is deliberately conservative:
- A processing challenge with a deterministic completed match reservation is
  closed to that exact match.
- A pending/unknown reservation is never reopened or re-settled.
- A processing challenge with no reservation is reopened only after the
  15-minute processing lease has expired.
- Ticket state is never restored by recovery; the challenge already consumed
  its ticket when it was created.
"""

from __future__ import annotations

import logging
import time

from .match_scoring import apply_rsl_performance_bonus

log = logging.getLogger(__name__)

PROCESSING_LEASE_SECONDS = 15 * 60


async def reconcile_processing_challenges(db, guild_id: str) -> dict[str, int]:
    """Reconcile processing Gauntlet challenges for one guild.

    Returns counters suitable for operational logging.
    """
    guild_id = str(guild_id)
    now = time.time()
    stats = {"closed": 0, "reopened": 0, "pending": 0, "skipped": 0, "bonus_retried": 0, "bonus_failed": 0}

    async for challenge in db.active_challenges.find({
        "guild_id": guild_id,
        "status": {"$in": ["processing", "completed"]},
    }):
        challenge_id = str(challenge.get("_id") or "")
        if not challenge_id:
            stats["skipped"] += 1
            continue

        reservation = await db.matches.find_one({
            "_id": f"{challenge_id}:match",
            "guild_id": guild_id,
        })

        if reservation:
            settlement_status = str(reservation.get("settlement_status") or "").casefold()
            if settlement_status == "completed":
                # The base settlement is authoritative, but the RSL margin bonus
                # is an optional post-settlement adjustment. If the original
                # request failed after the match was committed, retry it from the
                # same deterministic reservation instead of silently losing the
                # bonus forever. The bonus helper is itself idempotent/atomic.
                if not reservation.get("rsl_margin_bonus_applied"):
                    try:
                        bonus = await apply_rsl_performance_bonus(db, reservation)
                        if bonus:
                            stats["bonus_retried"] += 1
                    except Exception:
                        log.exception("Failed to retry RSL performance bonus for settlement %s", reservation.get("_id"))
                        stats["bonus_failed"] += 1
                result = await db.active_challenges.update_one(
                    {
                        "_id": challenge_id,
                        "guild_id": guild_id,
                        "challenger_id": str(challenge.get("challenger_id") or ""),
                        "status": "processing",
                    },
                    {
                        "$set": {
                            "status": "completed",
                            "completed_at": now,
                            "match_id": reservation["_id"],
                            "ticket_burned": True,
                            "settlement_closed": True,
                            "reconciled_at": now,
                            "reconciliation_reason": "completed_settlement",
                        },
                        "$unset": {"processing_at": ""},
                    },
                )
                if getattr(result, "modified_count", 0) == 1:
                    stats["closed"] += 1
                else:
                    stats["skipped"] += 1
            else:
                # Pending/unknown reservations are intentionally left locked.
                # A second worker must never guess whether the settlement is
                # safe to repeat.
                stats["pending"] += 1
            continue

        raw_processing_at = challenge.get("processing_at")
        try:
            processing_at = float(raw_processing_at) if raw_processing_at is not None else now
        except (TypeError, ValueError):
            processing_at = now

        if now - processing_at <= PROCESSING_LEASE_SECONDS:
            stats["skipped"] += 1
            continue

        # No deterministic settlement reservation exists after the processing
        # lease. Reopen the challenge for submission, but do not refund the
        # ticket: it was consumed when the challenge was created.
        result = await db.active_challenges.update_one(
            {
                "_id": challenge_id,
                "guild_id": guild_id,
                "challenger_id": str(challenge.get("challenger_id") or ""),
                "status": "processing",
            },
            {
                "$set": {
                    "status": "active",
                    "last_reminder": 0,
                    "recovered_at": now,
                    "recovery_reason": "processing_lease_expired_without_reservation",
                    "ticket_burned": True,
                    "settlement_closed": False,
                },
                "$unset": {"processing_at": ""},
            },
        )
        if getattr(result, "modified_count", 0) == 1:
            stats["reopened"] += 1
        else:
            stats["skipped"] += 1

    return stats
