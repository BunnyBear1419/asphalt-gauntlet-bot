"""Community guide routes for the RSL Reference Hub.

Guides are guild-owned, moderated before publication, and deliberately separate
from the existing reference-video/intel/request systems.
"""
import hashlib
import re

from aiohttp import web


class CommunityGuidesMixin:
    async def gauntlet_reference_guides(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_member(request)
        q = str(request.query.get("q") or "").strip()[:100]
        category = str(request.query.get("category") or "").strip()[:60]
        query = {"guild_id": str(guild_id), "status": {"$in": ["approved", "published"]}}
        if category:
            query["category"] = category
        if q:
            rx = re.escape(q)
            query["$or"] = [
                {"title": {"$regex": rx, "$options": "i"}},
                {"body": {"$regex": rx, "$options": "i"}},
                {"tags": {"$regex": rx, "$options": "i"}},
                {"driver": {"$regex": rx, "$options": "i"}},
            ]
        rows = []
        async for item in self.bot.db.reference_guides.find(query).sort([("helpful", -1), ("created_at", -1)]).limit(100):
            rows.append({
                "id": str(item.get("_id") or ""),
                "title": str(item.get("title") or ""),
                "category": str(item.get("category") or "Strategy"),
                "tags": list(item.get("tags") or [])[:12],
                "body": str(item.get("body") or ""),
                "driver": str(item.get("driver") or ""),
                "user_id": str(item.get("user_id") or ""),
                "video_url": str(item.get("video_url") or ""),
                "helpful": int(item.get("helpful") or 0),
                "created_at": item.get("created_at") or 0,
            })
        return web.json_response({"rows": rows})


    async def gauntlet_reference_guide_submit(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        title = str(payload.get("title") or "").strip()[:120]
        category = str(payload.get("category") or "Strategy").strip()[:60]
        body = str(payload.get("body") or "").strip()[:6000]
        tags = []
        raw_tags = payload.get("tags")
        if isinstance(raw_tags, str):
            raw_tags = raw_tags.split(",")
        if isinstance(raw_tags, (list, tuple)):
            for value in raw_tags:
                tag = str(value or "").strip()[:30]
                if tag and tag.casefold() not in {x.casefold() for x in tags}:
                    tags.append(tag)
                if len(tags) >= 12:
                    break
        video_url = str(payload.get("video_url") or "").strip()[:500]
        if not title or not body:
            raise web.HTTPBadRequest(text="Guide title and body are required.")
        if video_url and not re.match(r"^https?://", video_url, re.I):
            raise web.HTTPBadRequest(text="Guide video URL must use http:// or https://.")
        profile = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        driver = str(profile.get("game_id") or profile.get("username") or getattr(user, "display_name", "") or user.user_id)[:100]
        fingerprint = hashlib.sha256(f"{guild_id}:{user.user_id}:{title.casefold()}:{body}".encode()).hexdigest()
        guide_id = f"guide_{guild_id}_{fingerprint[:24]}"
        existing = await self.bot.db.reference_guides.find_one({"_id": guide_id, "guild_id": str(guild_id)})
        if existing:
            raise web.HTTPConflict(text="A guide with the same title and content is already submitted.")
        now = __import__("time").time()
        doc = {
            "_id": guide_id,
            "guild_id": str(guild_id),
            "user_id": str(user.user_id),
            "driver": driver,
            "title": title,
            "category": category or "Strategy",
            "tags": tags,
            "body": body,
            "video_url": video_url,
            "status": "pending",
            "helpful": 0,
            "fingerprint": fingerprint,
            "created_at": now,
            "updated_at": now,
        }
        await self.bot.db.reference_guides.insert_one(doc)
        await self._audit(str(guild_id), str(user.user_id), "Community guide submitted for review")
        return web.json_response({"ok": True, "id": guide_id, "status": "pending"})


    async def gauntlet_reference_guide_vote(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        guide_id = str(payload.get("id") or "").strip()
        if not guide_id:
            raise web.HTTPBadRequest(text="Guide id is required.")
        guide = await self.bot.db.reference_guides.find_one({
            "_id": guide_id, "guild_id": str(guild_id), "status": {"$in": ["approved", "published"]}
        })
        if not guide:
            raise web.HTTPNotFound(text="Guide not found.")
        vote_id = hashlib.sha256(f"{guild_id}:{guide_id}:{user.user_id}".encode()).hexdigest()
        try:
            await self.bot.db.reference_guide_votes.insert_one({
                "_id": vote_id, "guild_id": str(guild_id), "guide_id": guide_id,
                "user_id": str(user.user_id), "created_at": __import__("time").time(),
            })
        except Exception as exc:
            if type(exc).__name__ == "DuplicateKeyError":
                return web.json_response({"ok": True, "duplicate": True, "helpful": int(guide.get("helpful") or 0)})
            raise
        result = await self.bot.db.reference_guides.update_one(
            {"_id": guide_id, "guild_id": str(guild_id), "status": {"$in": ["approved", "published"]}},
            {"$inc": {"helpful": 1}},
        )
        if getattr(result, "modified_count", 0) != 1:
            raise web.HTTPConflict(text="Guide changed before the vote could be recorded.")
        return web.json_response({"ok": True, "helpful": int(guide.get("helpful") or 0) + 1})


    async def admin_reference_guide_review_queue(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        rows = []
        async for item in self.bot.db.reference_guides.find({
            "guild_id": str(guild_id), "status": "pending"
        }).sort("created_at", 1).limit(100):
            rows.append({
                "id": str(item.get("_id") or ""),
                "title": str(item.get("title") or ""),
                "category": str(item.get("category") or ""),
                "tags": list(item.get("tags") or []),
                "body": str(item.get("body") or ""),
                "driver": str(item.get("driver") or ""),
                "video_url": str(item.get("video_url") or ""),
                "created_at": item.get("created_at") or 0,
            })
        return web.json_response({"queue": rows})


    async def admin_reference_guide_review(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        guide_id = str(payload.get("id") or "").strip()
        decision = str(payload.get("decision") or "").strip().casefold()
        if decision not in {"approve", "reject"}:
            raise web.HTTPBadRequest(text="Decision must be approve or reject.")
        status = "approved" if decision == "approve" else "rejected"
        result = await self.bot.db.reference_guides.update_one(
            {"_id": guide_id, "guild_id": str(guild_id), "status": "pending"},
            {"$set": {
                "status": status,
                "reviewed_by": str(user.user_id),
                "reviewed_at": __import__("time").time(),
                "updated_at": __import__("time").time(),
            }},
        )
        if getattr(result, "modified_count", 0) != 1:
            raise web.HTTPNotFound(text="Pending guide not found.")
        await self._audit(str(guild_id), str(user.user_id), f"Community guide {decision}d")
        return web.json_response({"ok": True, "status": status})
