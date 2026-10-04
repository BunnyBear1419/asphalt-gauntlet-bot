"""Beat-the-reference competitions for the RSL Reference Hub."""
from .._web_context import *
import hashlib, time


class BeatReferenceMixin:
    async def gauntlet_reference_beats(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        rows = []
        cursor = self.bot.db.rsl_reference_beats.find(
            {"guild_id": str(guild_id), "status": "published"}
        ).sort("created_at", -1).limit(50)
        async for row in cursor:
            beat = await self.bot.db.rsl_reference_beat_submissions.find_one({
                "guild_id": str(guild_id), "beat_id": str(row.get("_id")), "user_id": str(user.user_id)
            })
            rows.append({
                "id": str(row.get("_id") or ""), "title": str(row.get("title") or ""),
                "course": str(row.get("course") or ""), "car": str(row.get("car") or ""),
                "reference_time": str(row.get("reference_time") or ""),
                "points": int(row.get("points", 100) or 100),
                "my_submission": ({
                    "time": str(beat.get("time") or ""), "status": str(beat.get("status") or "pending"),
                    "score": int(beat.get("score", 0) or 0), "beat": bool(beat.get("beat"))
                } if beat else None)
            })
        return web.json_response({"rows": rows})

    async def gauntlet_reference_beat_submit(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        beat_id = str(payload.get("beat_id") or "").strip()
        challenge = await self.bot.db.rsl_reference_beats.find_one(
            {"_id": beat_id, "guild_id": str(guild_id), "status": "published"}
        )
        if not challenge:
            raise web.HTTPNotFound(text="Beat-the-reference competition not found.")
        lap = str(payload.get("time") or "").strip()[:30]
        proof = str(payload.get("proof_url") or "").strip()[:500]
        if not lap or not proof or not proof.lower().startswith(("http://", "https://")):
            raise web.HTTPBadRequest(text="Time and an http(s) proof URL are required.")
        try:
            if ":" in lap:
                mm, ss = lap.split(":", 1); ms = int((float(mm) * 60 + float(ss)) * 1000)
            else: ms = int(float(lap) * 1000)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Time must be mm:ss.xx or seconds.")
        if ms <= 0 or ms > 3600000:
            raise web.HTTPBadRequest(text="Invalid lap time.")
        target = str(challenge.get("reference_time") or "")
        try:
            if ":" in target:
                mm, ss = target.split(":", 1); target_ms = int((float(mm) * 60 + float(ss)) * 1000)
            else: target_ms = int(float(target) * 1000)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Competition reference time is invalid.")
        beat = ms < target_ms
        base = max(1, min(1000, int(challenge.get("points", 100) or 100)))
        score = base if beat else 0
        sid = hashlib.sha256(f"{guild_id}:{beat_id}:{user.user_id}".encode()).hexdigest()
        await self.bot.db.rsl_reference_beat_submissions.update_one(
            {"_id": sid, "guild_id": str(guild_id)},
            {"$set": {"_id": sid, "guild_id": str(guild_id), "beat_id": beat_id, "user_id": str(user.user_id),
                      "time": lap, "ms": ms, "proof_url": proof, "beat": beat, "score": score,
                      "status": "pending", "updated_at": time.time()},
             "$setOnInsert": {"created_at": time.time()}}, upsert=True)
        await self._audit(str(guild_id), str(user.user_id), f"Beat-reference submission: {beat_id}")
        return web.json_response({"ok": True, "beat": beat, "score": score, "status": "pending"})

    async def gauntlet_reference_beat_leaderboard(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_member(request)
        beat_id = str(request.query.get("beat_id") or "").strip()
        if not beat_id: raise web.HTTPBadRequest(text="beat_id is required.")
        rows = []
        cursor = self.bot.db.rsl_reference_beat_submissions.find(
            {"guild_id": str(guild_id), "beat_id": beat_id, "status": "approved", "beat": True}
        ).sort([("ms", 1), ("created_at", 1)]).limit(100)
        async for row in cursor:
            profile = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{row.get('user_id')}"} ) or {}
            rows.append({"user_id": str(row.get("user_id") or ""), "name": str(profile.get("game_id") or profile.get("username") or row.get("user_id") or "RSL Driver"), "time": str(row.get("time") or ""), "score": int(row.get("score", 0) or 0)})
        return web.json_response({"rows": rows})

    async def admin_reference_beat_create(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        title = str(payload.get("title") or "").strip()[:140]
        course = str(payload.get("course") or "").strip()[:140]
        car = str(payload.get("car") or "").strip()[:140]
        reference_time = str(payload.get("reference_time") or "").strip()[:30]
        if not title or not course or not car or not reference_time:
            raise web.HTTPBadRequest(text="Title, track, car, and reference time are required.")
        try: points = max(1, min(1000, int(payload.get("points", 100) or 100)))
        except (TypeError, ValueError): points = 100
        beat_id = hashlib.sha256(f"{guild_id}:{title}:{course}:{car}:{reference_time}".encode()).hexdigest()
        await self.bot.db.rsl_reference_beats.update_one(
            {"_id": beat_id, "guild_id": str(guild_id)},
            {"$set": {"guild_id": str(guild_id), "title": title, "course": course, "car": car,
                      "reference_time": reference_time, "points": points, "status": "published",
                      "updated_at": time.time(), "created_by": str(user.user_id)},
             "$setOnInsert": {"created_at": time.time()}}, upsert=True)
        await self._audit(str(guild_id), str(user.user_id), f"Published beat-reference competition: {beat_id}")
        return web.json_response({"ok": True, "beat_id": beat_id})

    async def admin_reference_beat_review_queue(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        rows = []
        cursor = self.bot.db.rsl_reference_beat_submissions.find({"guild_id": str(guild_id), "status": "pending"}).sort("created_at", 1).limit(100)
        async for row in cursor:
            rows.append({"id": str(row.get("_id") or ""), "beat_id": str(row.get("beat_id") or ""), "user_id": str(row.get("user_id") or ""), "time": str(row.get("time") or ""), "proof_url": str(row.get("proof_url") or ""), "beat": bool(row.get("beat")), "score": int(row.get("score", 0) or 0)})
        return web.json_response({"rows": rows})

    async def admin_reference_beat_review(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        sid, action = str(payload.get("submission_id") or "").strip(), str(payload.get("action") or "").strip().lower()
        if not sid or action not in {"approve", "reject"}: raise web.HTTPBadRequest(text="submission_id and approve/reject action are required.")
        result = await self.bot.db.rsl_reference_beat_submissions.update_one(
            {"_id": sid, "guild_id": str(guild_id), "status": "pending"},
            {"$set": {"status": "approved" if action == "approve" else "rejected", "reviewed_by": str(user.user_id), "reviewed_at": time.time()}})
        if result.modified_count != 1: raise web.HTTPNotFound(text="Pending beat submission not found.")
        return web.json_response({"ok": True})
