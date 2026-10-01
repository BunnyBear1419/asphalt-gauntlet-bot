"""Exactly-once tournament reward settlement shared by web and Discord completion paths.

Tournament documents snapshot their reward configuration at creation time. Zero is a
valid default so existing tournaments do not silently mint currency or XP.
"""
from __future__ import annotations

from .rsl_economy_ledger import apply_coin_transaction
from .rsl_xp import award_xp

REWARD_KEYS = (
    "participation_coins", "finalist_coins", "third_place_coins",
    "runner_up_coins", "champion_coins",
    "participation_xp", "finalist_xp", "third_place_xp",
    "runner_up_xp", "champion_xp",
)
DEFAULT_TOURNAMENT_REWARDS = {key: 0 for key in REWARD_KEYS}


def normalize_tournament_rewards(value: dict | None) -> dict:
    value = value if isinstance(value, dict) else {}
    return {
        key: max(0, int(value.get(key, DEFAULT_TOURNAMENT_REWARDS[key]) or 0))
        for key in REWARD_KEYS
    }


async def _entrant_users(db, tournament: dict, entrant_id: str) -> list[str]:
    entrant_id = str(entrant_id or "")
    if not entrant_id:
        return []
    if int(tournament.get("team_size", 1) or 1) > 1:
        users = []
        cursor = db.tournament_club_registrations.find({
            "tournament_id": str(tournament.get("_id")),
            "club_id": entrant_id,
            "status": {"$in": ["accepted", "checked_in"]},
        })
        async for registration in cursor:
            users.extend(str(uid) for uid in (registration.get("lineup") or []) if uid)
        return list(dict.fromkeys(users))
    return [entrant_id]


async def settle_tournament_rewards(db, tournament: dict) -> dict:
    """Settle configured completion rewards exactly once per player/reward type."""
    if str(tournament.get("status")) != "completed":
        return {"ok": False, "settled": 0, "reason": "not_completed"}

    rewards = normalize_tournament_rewards(tournament.get("rewards"))
    standings = list(tournament.get("standings") or [])
    if not standings:
        return {"ok": True, "settled": 0, "reason": "no_standings"}

    placements = {}
    for index, row in enumerate(standings[:4]):
        entrant = str(row.get("entrant_id") or "")
        if entrant:
            placements[entrant] = (
                "champion" if index == 0 else
                "runner_up" if index == 1 else
                "third_place" if index == 2 else
                "finalist"
            )

    settled = 0
    for entrant_id, placement in placements.items():
        users = await _entrant_users(db, tournament, entrant_id)
        for user_id in users:
            coin_amount = rewards.get(f"{placement}_coins", 0)
            xp_amount = rewards.get(f"{placement}_xp", 0)
            if coin_amount:
                result = await apply_coin_transaction(
                    db,
                    guild_id=str(tournament.get("guild_id")),
                    user_id=user_id,
                    amount=coin_amount,
                    transaction_type="tournament_reward",
                    reference_id=f"tournament:{tournament.get('_id')}:{placement}:coins",
                    reason=f"Tournament {placement.replace('_', ' ').title()} reward",
                    metadata={"tournament_id": str(tournament.get("_id")), "placement": placement},
                )
                if not result.get("ok"):
                    return {"ok": False, "settled": settled, "reason": result.get("reason", "coin_reward_failed")}
                if not result.get("duplicate"):
                    settled += 1
            if xp_amount:
                result = await award_xp(
                    db,
                    guild_id=str(tournament.get("guild_id")),
                    user_id=user_id,
                    amount=xp_amount,
                    source="tournament_reward",
                    event_id=f"{tournament.get('_id')}:{placement}",
                    metadata={"tournament_id": str(tournament.get("_id")), "placement": placement},
                )
                if not result.get("ok") and not result.get("restricted"):
                    return {"ok": False, "settled": settled, "reason": "xp_reward_failed"}
                if not result.get("duplicate"):
                    settled += 1

    marker = f"tournament:{tournament.get('_id')}:rewards_settled"
    await db.tournaments.update_one(
        {"_id": tournament.get("_id")},
        {"$set": {"rewards_settled": True, "rewards_settled_marker": marker}},
    )
    return {"ok": True, "settled": settled, "marker": marker}
