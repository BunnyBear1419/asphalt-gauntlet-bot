"""Historical ALU / game reference routes for the RSL Reference Hub.

Historical entries are guild-owned, source-backed records. They are moderated
before publication so the hub does not silently present unverified history.
"""
import hashlib
import re
import time

from aiohttp import web


class HistoricalReferenceMixin:
    async def gauntlet_reference_history(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_member(request)
        q = str(request.query.get("q") or "").strip()[:100]
        category = str(request.query.get("category") or "").strip()[:60]
        era = str(request.query.get("era") or "").strip()[:60]
        query = {"guild_id": str(guild_id), "status": {"$in": ["approved", "published"]}}
        if category:
            query["category"] = category
        if era:
            query["era"] = era
        if q:
            rx = re.escape(q)
            query["$or"] = [
                {"title": {"$regex": rx, "$options": "i"}},
                {"summary": {"$regex": rx, "$options": "i"}},
                {"details": {"$regex": rx, "$options": "i"}},
                {"tags": {"$regex": rx, "$options": "i"}},
            ]
        rows = []
        async for item in self.bot.db.reference_history.find(query).sort([("event_date", -1), ("created_at", -1)]).limit(100):
            rows.append({
                "id": str(item.get("_id") or ""),
                "title": str(item.get("title") or ""),
                "category": str(item.get("category") or "Game History"),
                "era": str(item.get("era") or ""),
                "event_date": str(item.get("event_date") or ""),
                "summary": str(item.get("summary") or ""),
                "details": str(item.get("details") or ""),
                "tags": list(item.get("tags") or [])[:12],
                "source_url": str(item.get("source_url") or ""),
                "video_url": str(item.get("video_url") or ""),
                "contributor": str(item.get("driver") or ""),
            })
        return web.json_response({"rows": rows})

    async def gauntlet_reference_history_submit(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        title = str(payload.get("title") or "").strip()[:140]
        category = str(payload.get("category") or "Game History").strip()[:60]
        era = str(payload.get("era") or "").strip()[:60]
        event_date = str(payload.get("event_date") or "").strip()[:30]
        summary = str(payload.get("summary") or "").strip()[:500]
        details = str(payload.get("details") or "").strip()[:8000]
        source_url = str(payload.get("source_url") or "").strip()[:500]
        video_url = str(payload.get("video_url") or "").strip()[:500]
        raw_tags = payload.get("tags")
        tags = []
        if isinstance(raw_tags, str):
            raw_tags = raw_tags.split(",")
        if isinstance(raw_tags, (list, tuple)):
            for value in raw_tags:
                tag = str(value or "").strip()[:30]
                if tag and tag.casefold() not in {x.casefold() for x in tags}:
                    tags.append(tag)
                if len(tags) >= 12:
                    break
        if not title or not summary or not details:
            raise web.HTTPBadRequest(text="History title, summary and details are required.")
        for label, url in (("Source", source_url), ("Video", video_url)):
            if url and not re.match(r"^https?://", url, re.I):
                raise web.HTTPBadRequest(text=f"{label} URL must use http:// or https://.")
        profile = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        driver = str(profile.get("game_id") or profile.get("username") or getattr(user, "display_name", "") or user.user_id)[:100]
        fingerprint = hashlib.sha256(
            f"{guild_id}:{user.user_id}:{title.casefold()}:{summary}:{details}".encode()
        ).hexdigest()
        history_id = f"history_{guild_id}_{fingerprint[:24]}"
        if await self.bot.db.reference_history.find_one({"_id": history_id, "guild_id": str(guild_id)}):
            raise web.HTTPConflict(text="This historical entry is already submitted.")
        now = time.time()
        await self.bot.db.reference_history.insert_one({
            "_id": history_id, "guild_id": str(guild_id), "user_id": str(user.user_id),
            "driver": driver, "title": title, "category": category or "Game History",
            "era": era, "event_date": event_date, "summary": summary, "details": details,
            "tags": tags, "source_url": source_url, "video_url": video_url,
            "status": "pending", "created_at": now, "updated_at": now,
        })
        await self._audit(str(guild_id), str(user.user_id), "Historical reference submitted for review")
        return web.json_response({"ok": True, "id": history_id, "status": "pending"})

    async def admin_reference_history_review_queue(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        rows = []
        async for item in self.bot.db.reference_history.find({
            "guild_id": str(guild_id), "status": "pending"
        }).sort("created_at", 1).limit(100):
            rows.append({
                "id": str(item.get("_id") or ""), "title": str(item.get("title") or ""),
                "category": str(item.get("category") or ""), "era": str(item.get("era") or ""),
                "event_date": str(item.get("event_date") or ""),
                "summary": str(item.get("summary") or ""), "details": str(item.get("details") or ""),
                "source_url": str(item.get("source_url") or ""), "video_url": str(item.get("video_url") or ""),
                "driver": str(item.get("driver") or ""), "tags": list(item.get("tags") or []),
            })
        return web.json_response({"queue": rows})

    async def admin_reference_history_review(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        entry_id = str(payload.get("id") or "").strip()
        decision = str(payload.get("decision") or "").strip().casefold()
        if decision not in {"approve", "reject"}:
            raise web.HTTPBadRequest(text="Decision must be approve or reject.")
        status = "approved" if decision == "approve" else "rejected"
        result = await self.bot.db.reference_history.update_one(
            {"_id": entry_id, "guild_id": str(guild_id), "status": "pending"},
            {"$set": {"status": status, "reviewed_by": str(user.user_id), "reviewed_at": time.time(), "updated_at": time.time()}},
        )
        if getattr(result, "modified_count", 0) != 1:
            raise web.HTTPNotFound(text="Pending historical entry not found.")
        await self._audit(str(guild_id), str(user.user_id), f"Historical reference {decision}d")
        return web.json_response({"ok": True, "status": status})
