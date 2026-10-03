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
    limits = {key: (1000000 if key.endswith("_xp") else 100000) for key in REWARD_KEYS}
    normalized = {}
    for key in REWARD_KEYS:
        try:
            amount = int(value.get(key, DEFAULT_TOURNAMENT_REWARDS[key]) or 0)
        except (TypeError, ValueError):
            raise ValueError("Invalid tournament reward: " + key)
        if amount < 0 or amount > limits[key]:
            raise ValueError("Tournament reward out of range: " + key)
        normalized[key] = amount
    return normalized

async def _entrant_users(db, tournament: dict, entrant_id: str) -> list[str]:
    entrant_id = str(entrant_id or "")
    if not entrant_id:
        return []
    if int(tournament.get("team_size", 1) or 1) > 1:
        users = []
        cursor = db.tournament_club_registrations.find({
            "tournament_id": str(tournament.get("_id")),
            "club_id": entrant_id,
            "guild_id": str(tournament.get("guild_id")),
            "status": {"$in": ["accepted", "checked_in"]},
        })
        async for registration in cursor:
            users.extend(str(uid) for uid in (registration.get("lineup") or []) if uid)
        return list(dict.fromkeys(users))
    return [entrant_id]


async def tournament_role_recipients(db, tournament: dict, entrant_ids: list[str]) -> dict[str, list[str]]:
    """Resolve tournament entrant IDs to Discord user IDs, including club lineups."""
    team_event = int(tournament.get("team_size", 1) or 1) > 1
    resolved: dict[str, list[str]] = {}
    for index, entrant_id in enumerate(entrant_ids):
        entrant_id = str(entrant_id or "")
        users = await _entrant_users(db, tournament, entrant_id) if team_event else ([entrant_id] if entrant_id else [])
        resolved[str(index)] = list(dict.fromkeys(str(uid) for uid in users if uid))
    return resolved


async def _all_participant_users(db, tournament: dict) -> list[str]:
    """Return every accepted/checked-in tournament participant as individual users."""
    tournament_id = str(tournament.get("_id"))
    if int(tournament.get("team_size", 1) or 1) > 1:
        users = []
        cursor = db.tournament_club_registrations.find({
            "tournament_id": tournament_id,
            "guild_id": str(tournament.get("guild_id")),
            "status": {"$in": ["accepted", "checked_in"]},
        })
        async for registration in cursor:
            users.extend(str(uid) for uid in (registration.get("lineup") or []) if uid)
        return list(dict.fromkeys(users))

    users = []
    cursor = db.tournament_registrations.find({
        "tournament_id": tournament_id,
        "status": {"$in": ["accepted", "checked_in"]},
    })
    async for registration in cursor:
        user_id = registration.get("user_id")
        if user_id:
            users.append(str(user_id))
    return list(dict.fromkeys(users))


async def settle_tournament_rewards(db, tournament: dict) -> dict:
    """Settle configured completion rewards exactly once per player/reward type."""
    if str(tournament.get("status")) != "completed":
        return {"ok": False, "settled": 0, "reason": "not_completed"}

    rewards = normalize_tournament_rewards(tournament.get("rewards"))
    standings = list(tournament.get("standings") or [])
    participant_users = await _all_participant_users(db, tournament)
    if not standings and not participant_users:
        return {"ok": True, "settled": 0, "reason": "no_participants"}

    tournament_id = str(tournament.get("_id"))
    guild_id = str(tournament.get("guild_id"))
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

    async def reward_user(user_id: str, placement: str | None) -> bool:
        nonlocal settled
        user_id = str(user_id)
        if not user_id:
            return True
        prefix = f"tournament:{tournament_id}:{user_id}:{placement or 'participation'}"
        coin_key = f"{placement}_coins" if placement else "participation_coins"
        xp_key = f"{placement}_xp" if placement else "participation_xp"
        coin_amount = rewards.get(coin_key, 0)
        xp_amount = rewards.get(xp_key, 0)

        if coin_amount:
            result = await apply_coin_transaction(
                db,
                guild_id=guild_id,
                user_id=user_id,
                amount=coin_amount,
                transaction_type="tournament_reward",
                reference_id=f"{prefix}:coins",
                reason=f"Tournament {(placement or 'participation').replace('_', ' ').title()} reward",
                metadata={
                    "tournament_id": tournament_id,
                    "placement": placement or "participation",
                    "user_id": user_id,
                },
            )
            if not result.get("ok"):
                return False
            if not result.get("duplicate"):
                settled += 1

        if xp_amount:
            result = await award_xp(
                db,
                guild_id=guild_id,
                user_id=user_id,
                amount=xp_amount,
                source="tournament_reward",
                event_id=f"{prefix}:xp",
                metadata={
                    "tournament_id": tournament_id,
                    "placement": placement or "participation",
                    "user_id": user_id,
                },
            )
            if not result.get("ok") and not result.get("restricted"):
                return False
            if not result.get("duplicate"):
                settled += 1
        return True

    # Participation is additive: every accepted/checked-in player receives it.
    for user_id in participant_users:
        if not await reward_user(user_id, None):
            return {"ok": False, "settled": settled, "reason": "participation_reward_failed"}

    # Placement rewards are derived only from authoritative completed standings.
    for entrant_id, placement in placements.items():
        for user_id in await _entrant_users(db, tournament, entrant_id):
            if not await reward_user(user_id, placement):
                return {"ok": False, "settled": settled, "reason": f"{placement}_reward_failed"}

    marker = f"tournament:{tournament_id}:rewards_settled"
    marker_result = await db.tournaments.update_one(
        {"_id": tournament.get("_id"), "guild_id": guild_id},
        {"$set": {"rewards_settled": True, "rewards_settled_marker": marker}},
    )
    if getattr(marker_result, "matched_count", 1) != 1:
        return {"ok": False, "settled": settled, "reason": "settlement_marker_persist_failed"}
    return {"ok": True, "settled": settled, "marker": marker}


async def sync_completed_tournament_roles(db, guild, tournament: dict, *, role_names=None, role_ids=None) -> bool:
    """Apply tournament seasonal/achievement roles using resolved entrant recipients."""
    from .rsl_role_sync import sync_tournament_season_roles, sync_tournament_achievement_roles
    champion = str(tournament.get("champion_id") or "") or None
    runner_up = third_place = None
    finalists = []
    standings = tournament.get("standings") or []
    if standings:
        ordered = [str(row.get("entrant_id")) for row in standings if row.get("entrant_id") is not None]
        champion = champion or (ordered[0] if ordered else None)
        runner_up = ordered[1] if len(ordered) > 1 else None
        third_place = ordered[2] if len(ordered) > 2 else None
        finalists = ordered[:4]
    else:
        bracket = tournament.get("bracket") or {}
        groups = []
        for key in ("rounds", "winners", "losers"):
            groups.extend(bracket.get(key) or [])
        for key in ("grand_final", "grand_final_reset"):
            if isinstance(bracket.get(key), dict):
                groups.append({"matches": [bracket[key]]})
        matches = [m for group in groups for m in group.get("matches", [])]
        finals = [m for m in matches if m.get("status") == "completed" and str(m.get("bracket") or "") == "grand_final"]
        if not finals:
            finals = [m for m in matches if m.get("status") == "completed" and not m.get("winner_to")]
        if finals:
            slots = [str(x) for x in (finals[-1].get("player_slots") or []) if x]
            winner = str(finals[-1].get("winner_id") or "")
            champion = champion or (winner or None)
            runner_up = next((x for x in slots if x != winner), None)
            finalists = slots[:4]
    if not champion:
        return False

    try:
        await settle_tournament_rewards(db, tournament)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Failed to settle tournament rewards for %s", tournament.get("_id")
        )

    recipients = await tournament_role_recipients(
        db, tournament, [champion, runner_up or "", third_place or ""] + finalists
    )
    await sync_tournament_season_roles(
        guild,
        tournament_champion=recipients.get("0", []),
        runner_up=recipients.get("1", []),
        third_place=recipients.get("2", []),
        finalists=[
            uid for index in range(3, 3 + len(finalists))
            for uid in recipients.get(str(index), [])
        ],
        role_names=role_names,
        role_ids=role_ids,
    )

    participant_users = []
    perfect_users = []
    team_event = int(tournament.get("team_size", 1) or 1) > 1
    if team_event:
        club_ids = [str(row.get("entrant_id")) for row in standings if row.get("entrant_id") is not None]
        async for registration in db.tournament_club_registrations.find({
            "tournament_id": str(tournament.get("_id")),
            "club_id": {"$in": club_ids},
            "status": {"$in": ["accepted", "checked_in"]},
        }):
            participant_users.extend(str(uid) for uid in (registration.get("lineup") or []) if uid)
    else:
        participant_users = [str(row.get("entrant_id")) for row in standings if row.get("entrant_id") is not None]

    champion_row = next((row for row in standings if str(row.get("entrant_id")) == str(champion)), None)
    if champion_row is not None and int(champion_row.get("losses", 0) or 0) == 0:
        if team_event:
            async for registration in db.tournament_club_registrations.find({
                "tournament_id": str(tournament.get("_id")),
                "club_id": str(champion),
                "status": {"$in": ["accepted", "checked_in"]},
            }):
                perfect_users.extend(str(uid) for uid in (registration.get("lineup") or []) if uid)
        else:
            perfect_users = [str(champion)]

    achievements = {}
    if participant_users:
        achievements["Tournament Participant"] = list(dict.fromkeys(participant_users))
    if perfect_users:
        achievements["Perfect Tournament Run"] = list(dict.fromkeys(perfect_users))
    await sync_tournament_achievement_roles(
        guild, achievements=achievements, role_names=role_names, role_ids=role_ids
    )
    return True
