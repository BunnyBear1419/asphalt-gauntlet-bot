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


async def record_activity_event(
    db,
    *,
    guild_id: str,
    user_id: str,
    activity_type: str,
    event_id: str,
    season_number: int | None = None,
    count: int = 1,
) -> bool:
    """Record one qualified activity event exactly once.

    The unique event key makes retries/replays harmless. This ledger is
    intentionally separate from competitive standings: activity recognition
    can be rebuilt without changing Gauntlet ELO/points.
    """
    activity_type = str(activity_type).strip()
    event_id = str(event_id).strip()
    if not activity_type or not event_id or int(count or 0) <= 0:
        return False
    key = f"{guild_id}:{user_id}:{activity_type}:{event_id}"
    doc = {
        "_id": key,
        "guild_id": str(guild_id),
        "user_id": str(user_id),
        "activity_type": activity_type,
        "event_id": event_id,
        "season_number": int(season_number) if season_number is not None else None,
        "count": max(1, int(count)),
        "created_at": __import__("time").time(),
    }
    try:
        await db.rsl_activity_events.insert_one(doc)
        return True
    except Exception as exc:
        if exc.__class__.__name__ in {"DuplicateKeyError"}:
            return False
        raise


async def collect_overall_activity_stats(db, *, guild_id: str, season_number: int) -> list[dict]:
    """Rebuild current-season Overall RSL Activity from authoritative records.

    Competitive records remain authoritative; the activity ledger is used for
    explicitly approved community activity. Re-running this function is
    deterministic and therefore safe after restarts or partial failures.
    """
    guild_id = str(guild_id)
    season_number = int(season_number)
    stats: dict[str, dict] = {}

    def row(user_id: str) -> dict:
        user_id = str(user_id)
        return stats.setdefault(user_id, {"user_id": user_id, **{k: 0 for k in ACTIVITY_WEIGHTS}})

    match_cursor = db.matches.find(
        {
            "guild_id": guild_id,
            "settlement_status": "completed",
            "reverted": {"$ne": True},
            "season_number": season_number,
        },
        {
            "challenger_id": 1,
            "opponent_id": 1,
            "w_id": 1,
        },
    )
    async for match in match_cursor:
        challenger = str(match.get("challenger_id") or "")
        defender = str(match.get("opponent_id") or "")
        winner = str(match.get("w_id") or "")
        if challenger:
            row(challenger)["gauntlet_matches"] += 1
            row(challenger)["challenges"] += 1
        if defender:
            row(defender)["gauntlet_matches"] += 1
            row(defender)["defenses"] += 1

    # Tournament brackets are embedded in tournament documents. Count only
    # verified/completed matches from the current season and only real entrants.
    async for tournament in db.tournaments.find(
        {"guild_id": guild_id, "season_number": season_number},
        {"bracket": 1, "status": 1},
    ):
        bracket = tournament.get("bracket") or {}
        groups = []
        for key in ("rounds", "winners", "losers"):
            groups.extend(bracket.get(key) or [])
        for key in ("grand_final", "grand_final_reset"):
            if isinstance(bracket.get(key), dict):
                groups.append({"matches": [bracket[key]]})
        for group in groups:
            for match in group.get("matches", []):
                if match.get("status") != "completed" or match.get("result_status") != "verified":
                    continue
                for user_id in {str(x) for x in (match.get("player_slots") or []) if x}:
                    row(user_id)["tournament_matches"] += 1

    # Approved tournament media is a qualified community activity source.
    async for media in db.tournament_media.find(
        {"status": "approved", "guild_id": guild_id},
        {"submitted_by": 1, "user_id": 1, "created_at": 1},
    ):
        owner = str(media.get("submitted_by") or media.get("user_id") or "")
        if owner:
            row(owner)["media_posts"] += 1

    # Explicitly approved, non-competitive activities are idempotent ledger
    # events. Chat XP is deliberately not included, preventing chat farming
    # from becoming a competitive activity-ranking shortcut.
    async for event in db.rsl_activity_events.find(
        {"guild_id": guild_id, "season_number": season_number},
        {"user_id": 1, "activity_type": 1, "count": 1},
    ):
        activity_type = str(event.get("activity_type") or "")
        if activity_type in {"rsl_events", "approved_activity"}:
            owner = str(event.get("user_id") or "")
            if owner and activity_type in ACTIVITY_WEIGHTS:
                row(owner)[activity_type] += max(0, int(event.get("count", 1) or 1))

    result = [with_overall_activity_score(value) for value in stats.values()]
    result.sort(key=lambda item: (-item["overall_activity_score"], str(item["user_id"])))
    return result
