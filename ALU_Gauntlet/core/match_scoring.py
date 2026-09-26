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
    """Apply the one-time RSL margin adjustment to a settled Gauntlet match.

    The existing ELO calculation remains the base rating change. This helper
    only adds the race-margin adjustment and records it on the match so a
    retry cannot award the same bonus twice.
    """
    courses_beat = int(match_data.get("courses_beat", 0) or 0)
    margin = rsl_performance_bonus(courses_beat)

    # A 3-2 result is intentionally neutral relative to the existing ELO
    # settlement, but we still persist the scoring metadata for history/UI.
    await db.matches.update_one(
        {"_id": match_data["_id"]},
        {"$set": {
            "rsl_performance_bonus": margin if courses_beat >= 3 else -margin,
            "rsl_performance_score": f"{courses_beat}-{5 - courses_beat}",
            "rsl_performance_scoring_version": 1,
        }},
    )

    if margin == 0:
        await record_match_fairness_stats(db, match_data)
        return 0

    # Atomically claim the one-time adjustment. Only the first settlement
    # attempt for this match is allowed to change driver ELO.
    claim = await db.matches.update_one(
        {"_id": match_data["_id"], "rsl_margin_bonus_applied": {"$ne": True}},
        {"$set": {"rsl_margin_bonus_applied": True}},
    )
    if getattr(claim, "modified_count", 0) != 1:
        return 0

    challenger_id = str(match_data.get("challenger_id"))
    opponent_id = str(match_data.get("opponent_id"))
    winner_id = str(match_data.get("w_id") or match_data.get("winner_id") or "")
    loser_id = opponent_id if winner_id == challenger_id else challenger_id

    if winner_id not in {challenger_id, opponent_id}:
        # Never mutate an ambiguous settlement.
        await db.matches.update_one(
            {"_id": match_data["_id"]},
            {"$unset": {"rsl_margin_bonus_applied": ""}},
        )
        raise ValueError("Settled match does not contain a valid winner")

    await db.drivers.update_one(
        {"_id": f"{match_data.get('guild_id')}_{winner_id}"},
        {"$inc": {"elo": margin}},
    )
    await db.drivers.update_one(
        {"_id": f"{match_data.get('guild_id')}_{loser_id}"},
        {"$inc": {"elo": -margin}},
    )
    await db.matches.update_one(
        {"_id": match_data["_id"]},
        {"$set": {
            "rsl_performance_bonus_applied": margin,
            "rsl_performance_winner_bonus": margin,
            "rsl_performance_loser_penalty": -margin,
        }},
    )
    await record_match_fairness_stats(db, match_data)
    return margin if winner_id == challenger_id else -margin
