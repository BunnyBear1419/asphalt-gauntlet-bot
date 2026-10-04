"""RSL career and event reference routes.

Guild-owned, moderated reference records for career milestones, event formats,
rewards, seasons, and recurring competition history.
"""
import hashlib
import re
import time

from aiohttp import web


class CareerEventReferenceMixin:
    async def gauntlet_reference_events(self, request: web.Request) -> web.Response:
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
                {"summary": {"$regex": rx, "$options": "i"}},
                {"details": {"$regex": rx, "$options": "i"}},
                {"tags": {"$regex": rx, "$options": "i"}},
                {"season": {"$regex": rx, "$options": "i"}},
            ]
        rows = []
        async for item in self.bot.db.reference_events.find(query).sort([("start_date", -1), ("created_at", -1)]).limit(100):
            rows.append({
                "id": str(item.get("_id") or ""),
                "title": str(item.get("title") or ""),
                "category": str(item.get("category") or "Event"),
                "season": str(item.get("season") or ""),
                "start_date": str(item.get("start_date") or ""),
                "end_date": str(item.get("end_date") or ""),
                "summary": str(item.get("summary") or ""),
                "details": str(item.get("details") or ""),
                "format": str(item.get("format") or ""),
                "reward": str(item.get("reward") or ""),
                "source_url": str(item.get("source_url") or ""),
                "video_url": str(item.get("video_url") or ""),
                "tags": list(item.get("tags") or [])[:12],
                "contributor": str(item.get("driver") or ""),
            })
        return web.json_response({"rows": rows})

    async def gauntlet_reference_event_submit(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        title = str(payload.get("title") or "").strip()[:140]
        category = str(payload.get("category") or "Event").strip()[:60]
        season = str(payload.get("season") or "").strip()[:80]
        start_date = str(payload.get("start_date") or "").strip()[:30]
        end_date = str(payload.get("end_date") or "").strip()[:30]
        summary = str(payload.get("summary") or "").strip()[:500]
        details = str(payload.get("details") or "").strip()[:8000]
        event_format = str(payload.get("format") or "").strip()[:120]
        reward = str(payload.get("reward") or "").strip()[:500]
        source_url = str(payload.get("source_url") or "").strip()[:500]
        video_url = str(payload.get("video_url") or "").strip()[:500]
        raw_tags = payload.get("tags")
        if isinstance(raw_tags, str):
            raw_tags = raw_tags.split(",")
        tags = []
        if isinstance(raw_tags, (list, tuple)):
            for value in raw_tags:
                tag = str(value or "").strip()[:30]
                if tag and tag.casefold() not in {x.casefold() for x in tags}:
                    tags.append(tag)
                if len(tags) >= 12:
                    break
        if not title or not summary or not details:
            raise web.HTTPBadRequest(text="Event title, summary and details are required.")
        for label, url in (("Source", source_url), ("Video", video_url)):
            if url and not re.match(r"^https?://", url, re.I):
                raise web.HTTPBadRequest(text=f"{label} URL must use http:// or https://.")
        profile = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        driver = str(profile.get("game_id") or profile.get("username") or getattr(user, "display_name", "") or user.user_id)[:100]
        fingerprint = hashlib.sha256(
            f"{guild_id}:{user.user_id}:{title.casefold()}:{season}:{summary}:{details}".encode()
        ).hexdigest()
        event_id = f"event_{guild_id}_{fingerprint[:24]}"
        if await self.bot.db.reference_events.find_one({"_id": event_id, "guild_id": str(guild_id)}):
            raise web.HTTPConflict(text="This event reference is already submitted.")
        now = time.time()
        await self.bot.db.reference_events.insert_one({
            "_id": event_id, "guild_id": str(guild_id), "user_id": str(user.user_id),
            "driver": driver, "title": title, "category": category or "Event",
            "season": season, "start_date": start_date, "end_date": end_date,
            "summary": summary, "details": details, "format": event_format,
            "reward": reward, "source_url": source_url, "video_url": video_url,
            "tags": tags, "status": "pending", "created_at": now, "updated_at": now,
        })
        await self._audit(str(guild_id), str(user.user_id), "Career/event reference submitted for review")
        return web.json_response({"ok": True, "id": event_id, "status": "pending"})

    async def admin_reference_event_review_queue(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        rows = []
        async for item in self.bot.db.reference_events.find(
            {"guild_id": str(guild_id), "status": "pending"}
        ).sort("created_at", 1).limit(100):
            rows.append({
                "id": str(item.get("_id") or ""),
                "title": str(item.get("title") or ""),
                "category": str(item.get("category") or ""),
                "season": str(item.get("season") or ""),
                "start_date": str(item.get("start_date") or ""),
                "end_date": str(item.get("end_date") or ""),
                "summary": str(item.get("summary") or ""),
                "details": str(item.get("details") or ""),
                "format": str(item.get("format") or ""),
                "reward": str(item.get("reward") or ""),
                "source_url": str(item.get("source_url") or ""),
                "video_url": str(item.get("video_url") or ""),
                "driver": str(item.get("driver") or ""),
                "tags": list(item.get("tags") or []),
            })
        return web.json_response({"queue": rows})

    async def admin_reference_event_review(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        entry_id = str(payload.get("id") or "").strip()
        decision = str(payload.get("decision") or "").strip().casefold()
        if decision not in {"approve", "reject"}:
            raise web.HTTPBadRequest(text="Decision must be approve or reject.")
        status = "approved" if decision == "approve" else "rejected"
        result = await self.bot.db.reference_events.update_one(
            {"_id": entry_id, "guild_id": str(guild_id), "status": "pending"},
            {"$set": {
                "status": status, "reviewed_by": str(user.user_id),
                "reviewed_at": time.time(), "updated_at": time.time(),
            }},
        )
        if getattr(result, "modified_count", 0) != 1:
            raise web.HTTPNotFound(text="Pending event reference not found.")
        await self._audit(str(guild_id), str(user.user_id), f"Career/event reference {decision}d")
        return web.json_response({"ok": True, "status": status})
