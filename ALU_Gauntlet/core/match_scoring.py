"""RSL-specific Gauntlet performance scoring.

The five-race challenge still uses a 3-of-5 win condition. RSL adds a
controlled margin adjustment to the existing ELO settlement so a 5-0 result
is worth more than 4-1, and 4-1 is worth more than 3-2. The adjustment is
zero-sum between the winner and loser and never changes the underlying
challenge outcome.
"""

from __future__ import annotations

from .fairness import record_match_fairness_stats


def rsl_performance_bonus(courses_beat: int) -> int:
    """Return the controlled ELO margin bonus for a five-race challenge.

    3-2 is the baseline. A 4-1 win/loss carries an 8-point adjustment and a
    5-0 win/loss carries a 15-point adjustment. Scores outside 0..5 are
    rejected rather than silently producing a malformed settlement.
    """
    score = int(courses_beat)
    if score < 0 or score > 5:
        raise ValueError("courses_beat must be between 0 and 5")
    return {0: 15, 1: 8, 2: 0, 3: 0, 4: 8, 5: 15}[score]


async def apply_rsl_performance_bonus(db, match_data: dict) -> int:
    """Apply the one-time RSL margin adjustment atomically when Mongo supports transactions.

    The base match settlement is authoritative. This helper is an optional,
    zero-sum post-settlement adjustment, so a retry must never award it twice
    or leave only one driver's ELO changed.
    """
    courses_beat = int(match_data.get("courses_beat", 0) or 0)
    margin = rsl_performance_bonus(courses_beat)
    signed_margin = margin if courses_beat >= 3 else -margin

    challenger_id = str(match_data.get("challenger_id"))
    opponent_id = str(match_data.get("opponent_id"))
    winner_id = str(match_data.get("w_id") or match_data.get("winner_id") or "")
    if margin and winner_id not in {challenger_id, opponent_id}:
        raise ValueError("Settled match does not contain a valid winner")
    loser_id = opponent_id if winner_id == challenger_id else challenger_id

    metadata = {
        "rsl_performance_bonus": signed_margin,
        "rsl_performance_score": f"{courses_beat}-{5 - courses_beat}",
        "rsl_performance_scoring_version": 1,
    }

    client = getattr(db, "client", None)
    if margin and client is not None:
        # Keep the claim, both ELO writes, and applied marker in one Mongo
        # transaction. A crash/rollback cannot strand a half-applied bonus.
        async with await client.start_session() as session:
            async with session.start_transaction():
                current = await db.matches.find_one(
                    {"_id": match_data["_id"]},
                    {"rsl_margin_bonus_applied": 1},
                    session=session,
                )
                if current and current.get("rsl_margin_bonus_applied") is True:
                    return 0

                await db.matches.update_one(
                    {"_id": match_data["_id"], "rsl_margin_bonus_applied": {"$ne": True}},
                    {"$set": {**metadata, "rsl_margin_bonus_applied": True}},
                    session=session,
                )
                await db.drivers.update_one(
                    {"_id": f"{match_data.get('guild_id')}_{winner_id}"},
                    {"$inc": {"elo": margin}},
                    session=session,
                )
                await db.drivers.update_one(
                    {"_id": f"{match_data.get('guild_id')}_{loser_id}"},
                    {"$inc": {"elo": -margin}},
                    session=session,
                )
    else:
        # Lightweight/test DBs may not expose transactions. Preserve the
        # idempotent claim and compensate the first ELO write if the second
        # write fails.
        await db.matches.update_one(
            {"_id": match_data["_id"]},
            {"$set": metadata},
        )
        if margin == 0:
            await record_match_fairness_stats(db, match_data)
            return 0

        claim = await db.matches.update_one(
            {"_id": match_data["_id"], "rsl_margin_bonus_applied": {"$ne": True}},
            {"$set": {"rsl_margin_bonus_applied": True}},
        )
        if getattr(claim, "modified_count", 0) != 1:
            return 0

        winner_filter = {"_id": f"{match_data.get('guild_id')}_{winner_id}"}
        loser_filter = {"_id": f"{match_data.get('guild_id')}_{loser_id}"}
        try:
            winner_result = await db.drivers.update_one(
                winner_filter, {"$inc": {"elo": margin}}
            )
            if getattr(winner_result, "modified_count", 0) != 1:
                raise RuntimeError("Winner ELO bonus could not be applied")
            loser_result = await db.drivers.update_one(
                loser_filter, {"$inc": {"elo": -margin}}
            )
            if getattr(loser_result, "modified_count", 0) != 1:
                raise RuntimeError("Loser ELO adjustment could not be applied")
        except Exception:
            # Best-effort compensation for non-transactional test/lightweight
            # stores. Production Mongo uses the transaction path above.
            try:
                await db.drivers.update_one(
                    winner_filter, {"$inc": {"elo": -margin}}
                )
            finally:
                await db.matches.update_one(
                    {"_id": match_data["_id"]},
                    {"$unset": {"rsl_margin_bonus_applied": ""}},
                )
            raise

        await db.matches.update_one(
            {"_id": match_data["_id"]},
            {"$set": {
                "rsl_performance_bonus_applied": margin,
                "rsl_performance_winner_bonus": margin,
                "rsl_performance_loser_penalty": -margin,
            }},
        )

    await record_match_fairness_stats(db, match_data)
    return signed_margin if winner_id == challenger_id else -signed_margin

