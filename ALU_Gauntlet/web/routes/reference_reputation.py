"""Guild-scoped contributor reputation and achievement routes for the RSL Reference Hub."""
import time
from aiohttp import web


REPUTATION_LEVELS = (
    (600, "Hall of Fame"),
    (300, "Elite"),
    (150, "Expert"),
    (75, "Trusted"),
    (25, "Contributor"),
    (0, "Newcomer"),
)

def _level(score):
    for threshold, name in REPUTATION_LEVELS:
        if score >= threshold:
            return name
    return "Newcomer"


def _badges(stats):
    badges = []
    if stats["guides"] >= 1:
        badges.append("Guide Author")
    if stats["guides"] >= 3:
        badges.append("Guide Builder")
    if stats["helpful"] >= 10:
        badges.append("Helpful Voice")
    if stats["intel"] >= 5:
        badges.append("Track Scout")
    if stats["references"] >= 5:
        badges.append("Reference Racer")
    if stats["corrections"] >= 1:
        badges.append("Data Fixer")
    if stats["total"] >= 10:
        badges.append("Community Builder")
    return badges


class ReferenceReputationMixin:
    async def _reference_reputation_reset(self, guild_id, user_id):
        row = await self.bot.db.reference_reputation_resets.find_one(
            {"guild_id": str(guild_id), "user_id": str(user_id)}
        )
        return float(row.get("reset_at") or 0) if row else 0.0

    async def _reference_reputation_stats(self, guild_id, user_id):
        guild = str(guild_id)
        uid = str(user_id)
        reset_at = await self._reference_reputation_reset(guild, uid)
        created = {"$gt": reset_at} if reset_at else {"$exists": True}

        guides = await self.bot.db.reference_guides.count_documents({
            "guild_id": guild, "user_id": uid,
            "status": {"$in": ["approved", "published"]}, "created_at": created,
        })
        helpful = 0
        async for row in self.bot.db.reference_guides.find({
            "guild_id": guild, "user_id": uid,
            "status": {"$in": ["approved", "published"]}, "created_at": created,
        }, {"helpful": 1}):
            helpful += max(0, int(row.get("helpful") or 0))

        intel = await self.bot.db.reference_intel.count_documents({
            "guild_id": guild, "user_id": uid, "created_at": created,
        })
        references = await self.bot.db.gauntlet_references.count_documents({
            "guild_id": guild,
            "$or": [{"created_by": uid}, {"submitted_by": uid}],
            "created_at": created,
        })
        corrections = await self.bot.db.reference_requests.count_documents({
            "guild_id": guild, "user_id": uid, "kind": {"$in": ["correction", "data"]},
            "status": "completed", "created_at": created,
        })
        total = guides + intel + references + corrections

        score = guides * 25 + min(helpful, 50) * 2 + intel * 10 + references * 20 + corrections * 15
        badges = _badges({
            "guides": guides, "helpful": helpful, "intel": intel,
            "references": references, "corrections": corrections, "total": total,
        })
        return {
            "user_id": uid, "score": int(score), "level": _level(int(score)),
            "badges": badges, "guides": int(guides), "helpful": int(helpful),
            "intel": int(intel), "references": int(references),
            "corrections": int(corrections), "total": int(total),
            "reset_at": reset_at,
        }

    async def gauntlet_reference_reputation(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        stats = await self._reference_reputation_stats(guild_id, user.user_id)
        profile = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        stats["driver"] = str(profile.get("game_id") or profile.get("username") or getattr(user, "display_name", "") or user.user_id)
        return web.json_response(stats)

    async def gauntlet_reference_reputation_leaderboard(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_member(request)
        guild = str(guild_id)
        user_ids = set()
        for collection, query in (
            ("reference_guides", {"guild_id": guild}),
            ("reference_intel", {"guild_id": guild}),
            ("gauntlet_references", {"guild_id": guild}),
            ("reference_requests", {"guild_id": guild}),
        ):
            async for row in self.bot.db[collection].find(query, {"user_id": 1, "created_by": 1, "submitted_by": 1}):
                for key in ("user_id", "created_by", "submitted_by"):
                    value = str(row.get(key) or "")
                    if value:
                        user_ids.add(value)
        rows = []
        for uid in user_ids:
            stats = await self._reference_reputation_stats(guild, uid)
            if stats["score"] <= 0 and stats["total"] <= 0:
                continue
            profile = await self.bot.db.drivers.find_one({"_id": f"{guild}_{uid}"}) or {}
            stats["driver"] = str(profile.get("game_id") or profile.get("username") or uid)
            rows.append(stats)
        rows.sort(key=lambda x: (-x["score"], -x["helpful"], -x["total"], x["driver"].casefold()))
        for index, row in enumerate(rows[:50], 1):
            row["rank"] = index
        return web.json_response({"rows": rows[:50]})

    async def admin_reference_reputation_reset(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        target_id = str(payload.get("user_id") or "").strip()
        if not target_id:
            raise web.HTTPBadRequest(text="user_id is required.")
        now = time.time()
        await self.bot.db.reference_reputation_resets.update_one(
            {"guild_id": str(guild_id), "user_id": target_id},
            {"$set": {"reset_at": now, "reset_by": str(user.user_id), "updated_at": now}},
            upsert=True,
        )
        await self._audit(str(guild_id), str(user.user_id), f"Contributor reputation reset for {target_id}")
        return web.json_response({"ok": True, "user_id": target_id, "reset_at": now});
