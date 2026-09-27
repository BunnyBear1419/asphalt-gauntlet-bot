"""RSL advanced XP, leveling, and leaderboard mechanics.

All features are free and separate from competitive Gauntlet scoring.
"""
from __future__ import annotations

from datetime import datetime, timezone

XP_CURVES = {
    "linear": lambda level: (level * 100) + 75,
    "exponential": lambda level: (5 * (level ** 2)) + (level * 50) + 75,
    "flat": lambda level: 1000,
}
DEFAULT_XP_SETTINGS = {
    "curve": "linear",
    "multiplier": 1.0,
    "max_level": 0,
    "message_enabled": True,
    "voice_enabled": True,
    "reaction_enabled": True,
    "message_min": 15,
    "message_max": 30,
    "message_cooldown": 60,
    "voice_xp": 10,
    "voice_cooldown": 180,
    "voice_min_members": 2,
    "reaction_xp": 5,
    "reaction_cooldown": 300,
    "anti_afk": True,
    "stack_boosters": True,
    "role_boosters": [],
    "channel_boosters": [],
    "excluded_role_ids": [],
    "excluded_channel_ids": [],
    "allowed_channel_ids": [],
    "role_rewards": [],
    "leader_role_id": "",
    "leader_role_period": "weekly",
    "level_up_enabled": True,
    "level_up_channel_id": "",
    "level_up_message": "🏁 {mention} reached Level {level}!",
}
PERMANENT_LEVELS = {5: "Bronze", 10: "Silver", 25: "Gold", 50: "Platinum", 75: "Champion", 100: "Legend"}


def required_xp(level: int, settings: dict | None = None) -> int:
    settings = {**DEFAULT_XP_SETTINGS, **(settings or {})}
    curve = XP_CURVES.get(str(settings.get("curve", "linear")), XP_CURVES["linear"])
    return max(1, round(curve(max(1, int(level))) * float(settings.get("multiplier", 1.0) or 1.0)))


def level_from_xp(xp: int, settings: dict | None = None) -> int:
    settings = {**DEFAULT_XP_SETTINGS, **(settings or {})}
    xp = max(0, int(xp or 0))
    level = 0
    max_level = int(settings.get("max_level", 0) or 0)
    while True:
        if max_level and level >= max_level:
            return max_level
        needed = required_xp(level + 1, settings)
        if xp < needed:
            return level
        xp -= needed
        level += 1


def progress_for_xp(xp: int, settings: dict | None = None) -> dict:
    settings = {**DEFAULT_XP_SETTINGS, **(settings or {})}
    total = max(0, int(xp or 0))
    level = level_from_xp(total, settings)
    spent = 0
    for n in range(1, level + 1):
        spent += required_xp(n, settings)
    needed = required_xp(level + 1, settings)
    current = max(0, total - spent)
    return {"level": level, "current_xp": current, "needed_xp": needed, "percent": min(100, round((current / needed) * 100, 1))}


def period_keys(now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.now(timezone.utc)
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}", f"{now.year}-{now.month:02d}"


def xp_is_allowed(settings: dict, role_ids: list[str] | None = None, channel_id: str | None = None) -> bool:
    role_ids = {str(x) for x in (role_ids or [])}
    channel_id = str(channel_id or "")
    if role_ids & {str(x) for x in (settings.get("excluded_role_ids") or [])}:
        return False
    if channel_id in {str(x) for x in (settings.get("excluded_channel_ids") or [])}:
        return False
    allowed = {str(x) for x in (settings.get("allowed_channel_ids") or [])}
    return not allowed or channel_id in allowed


def effective_boost(settings: dict, role_ids: list[str] | None = None, channel_id: str | None = None) -> float:
    role_ids = {str(x) for x in (role_ids or [])}
    boosts = []
    for item in settings.get("role_boosters", []) or []:
        if str(item.get("role_id")) in role_ids:
            boosts.append(float(item.get("percent", 0) or 0))
    for item in settings.get("channel_boosters", []) or []:
        if str(item.get("channel_id")) == str(channel_id):
            boosts.append(float(item.get("percent", 0) or 0))
    if not boosts:
        return 1.0
    percent = sum(boosts) if settings.get("stack_boosters", True) else max(boosts)
    return max(0.0, 1.0 + (percent / 100.0))


async def award_xp(db, *, guild_id: str, user_id: str, amount: int, source: str,
                   event_id: str, role_ids=None, channel_id=None, metadata=None,
                   settings=None) -> dict:
    amount = max(0, int(amount or 0))
    if not amount:
        return {"ok": False, "duplicate": False, "amount": 0}
    settings = {**DEFAULT_XP_SETTINGS, **(settings or {})}
    if not xp_is_allowed(settings, role_ids, channel_id):
        return {"ok": False, "duplicate": False, "restricted": True, "amount": 0}
    boost = effective_boost(settings, role_ids, channel_id)
    final_amount = max(1, round(amount * boost))
    event = {
        "_id": f"{guild_id}:{user_id}:{source}:{event_id}",
        "guild_id": str(guild_id), "user_id": str(user_id), "source": str(source),
        "event_id": str(event_id), "amount": final_amount,
        "created_at": datetime.now(timezone.utc),
        "metadata": metadata or {},
    }
    try:
        await db.rsl_xp_events.insert_one(event)
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "e11000" in str(exc).lower():
            return {"ok": True, "duplicate": True, "amount": 0}
        raise
    week, month = period_keys()
    profile_id = f"{guild_id}_{user_id}"
    await db.drivers.update_one({"_id": profile_id, "$or": [{"rsl_xp_week": {"$ne": week}}, {"rsl_xp_week": {"$exists": False}}]}, {"$set": {"rsl_xp_week": week, "rsl_xp_weekly": 0}})
    await db.drivers.update_one({"_id": profile_id, "$or": [{"rsl_xp_month": {"$ne": month}}, {"rsl_xp_month": {"$exists": False}}]}, {"$set": {"rsl_xp_month": month, "rsl_xp_monthly": 0}})
    await db.drivers.update_one({"_id": profile_id}, {"$inc": {"rsl_xp": final_amount, "rsl_xp_weekly": final_amount, "rsl_xp_monthly": final_amount, "rsl_xp_message_count": 1 if source == "message" else 0, "rsl_xp_reaction_count": 1 if source == "reaction" else 0, "rsl_xp_voice_seconds": int(metadata.get("voice_seconds", 0)) if metadata else 0}, "$set": {"rsl_xp_week": week, "rsl_xp_month": month}}, upsert=False)
    return {"ok": True, "duplicate": False, "amount": final_amount, "boost": boost}


async def get_settings(db, guild_id: str) -> dict:
    doc = await db.rsl_xp_settings.find_one({"_id": str(guild_id)}) or {}
    return {**DEFAULT_XP_SETTINGS, **doc}


async def leaderboard(db, guild_id: str, *, period: str = "all", limit: int = 100) -> list[dict]:
    field = {"all": "rsl_xp", "weekly": "rsl_xp_weekly", "monthly": "rsl_xp_monthly"}.get(period, "rsl_xp")
    rows = []
    cursor = db.drivers.find({"guild_id": str(guild_id), "user_id": {"$exists": True}}).sort(field, -1).limit(max(1, min(int(limit), 100)))
    rank = 0
    async for doc in cursor:
        rank += 1
        xp = int(doc.get(field, 0) or 0)
        rows.append({
            "rank": rank, "user_id": str(doc.get("user_id", "")),
            "name": str(doc.get("game_id") or doc.get("username") or doc.get("user_id") or "Driver"),
            "xp": xp, "level": level_from_xp(int(doc.get("rsl_xp", 0) or 0)),
            "activity": int(doc.get("overall_activity_score", 0) or 0),
            "voice_seconds": int(doc.get("rsl_xp_voice_seconds", 0) or 0),
            "reactions": int(doc.get("rsl_xp_reaction_count", 0) or 0),
        })
    return rows


async def xp_history(db, guild_id: str, user_id: str, *, limit: int = 50) -> list[dict]:
    rows = []
    cursor = db.rsl_xp_events.find({"guild_id": str(guild_id), "user_id": str(user_id)}).sort("created_at", -1).limit(max(1, min(int(limit), 100)))
    async for doc in cursor:
        rows.append({"source": str(doc.get("source", "")), "amount": int(doc.get("amount", 0) or 0), "event_id": str(doc.get("event_id", "")), "created_at": doc.get("created_at").isoformat() if hasattr(doc.get("created_at"), "isoformat") else str(doc.get("created_at", "")), "metadata": doc.get("metadata") or {}})
    return rows
