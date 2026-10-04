"""Weekly RSL challenge routes for the Reference Hub."""
from .._web_context import *
from datetime import datetime, timezone, timedelta
import hashlib


class WeeklyChallengeMixin:
    async def gauntlet_weekly_challenges(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        now = datetime.now(timezone.utc)
        docs = []
        cursor = self.bot.db.rsl_weekly_challenges.find(
            {"guild_id": str(guild_id), "status": {"$in": ["published", "closed"]}}
        ).sort("week_start", -1).limit(12)
        async for row in cursor:
            challenge_id = str(row.get("_id") or "")
            mine = await self.bot.db.rsl_weekly_challenge_submissions.find_one(
                {"guild_id": str(guild_id), "challenge_id": challenge_id, "user_id": str(user.user_id)}
            )
            docs.append({
                "id": challenge_id,
                "week": str(row.get("week") or ""),
                "title": str(row.get("title") or ""),
                "prompt": str(row.get("prompt") or ""),
                "course": str(row.get("course") or ""),
                "car": str(row.get("car") or ""),
                "target_time": str(row.get("target_time") or ""),
                "points": int(row.get("points", 100) or 100),
                "week_start": row.get("week_start"),
                "week_end": row.get("week_end"),
                "status": str(row.get("status") or "published"),
                "is_current": bool(row.get("week_end", 0) and float(row.get("week_end") or 0) >= now.timestamp()),
                "my_submission": ({
                    "time": str(mine.get("time") or ""),
                    "proof_url": str(mine.get("proof_url") or ""),
                    "status": str(mine.get("status") or "pending"),
                    "score": int(mine.get("score", 0) or 0),
                } if mine else None),
            })
        return web.json_response({"challenges": docs})

    async def gauntlet_weekly_challenge_leaderboard(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_member(request)
        challenge_id = str(request.query.get("challenge_id") or "").strip()
        if not challenge_id:
            raise web.HTTPBadRequest(text="challenge_id is required.")
        challenge = await self.bot.db.rsl_weekly_challenges.find_one(
            {"_id": challenge_id, "guild_id": str(guild_id), "status": {"$in": ["published", "closed"]}}
        )
        if not challenge:
            raise web.HTTPNotFound(text="Weekly challenge not found.")
        rows = []
        cursor = self.bot.db.rsl_weekly_challenge_submissions.find(
            {"guild_id": str(guild_id), "challenge_id": challenge_id, "status": "approved"}
        ).sort([("score", -1), ("ms", 1), ("created_at", 1)]).limit(100)
        async for row in cursor:
            profile = await self.bot.db.drivers.find_one(
                {"_id": f"{guild_id}_{row.get('user_id')}"}
            ) or {}
            rows.append({
                "user_id": str(row.get("user_id") or ""),
                "name": str(profile.get("game_id") or profile.get("username") or row.get("user_id") or "RSL Driver"),
                "time": str(row.get("time") or ""),
                "score": int(row.get("score", 0) or 0),
                "proof_url": str(row.get("proof_url") or ""),
            })
        return web.json_response({
            "challenge_id": challenge_id,
            "title": str(challenge.get("title") or ""),
            "rows": rows,
        })

    async def gauntlet_weekly_challenge_submit(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        challenge_id = str(payload.get("challenge_id") or "").strip()
        challenge = await self.bot.db.rsl_weekly_challenges.find_one(
            {"_id": challenge_id, "guild_id": str(guild_id), "status": "published"}
        )
        if not challenge:
            raise web.HTTPNotFound(text="Active weekly challenge not found.")
        now = time.time()
        if float(challenge.get("week_end") or 0) and now > float(challenge.get("week_end") or 0):
            raise web.HTTPConflict(text="This weekly challenge has ended.")
        lap = str(payload.get("time") or "").strip()[:30]
        proof = str(payload.get("proof_url") or "").strip()[:500]
        if not lap or not proof:
            raise web.HTTPBadRequest(text="Time and proof URL are required.")
        if not proof.lower().startswith(("http://", "https://")):
            raise web.HTTPBadRequest(text="Proof URL must be an http(s) URL.")
        try:
            if ":" in lap:
                mm, ss = lap.split(":", 1)
                ms = int((float(mm) * 60 + float(ss)) * 1000)
            else:
                ms = int(float(lap) * 1000)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Time must be mm:ss.xx or seconds.")
        if ms <= 0 or ms > 3600000:
            raise web.HTTPBadRequest(text="Invalid lap time.")
        target_ms = 0
        target = str(challenge.get("target_time") or "").strip()
        try:
            if ":" in target:
                mm, ss = target.split(":", 1)
                target_ms = int((float(mm) * 60 + float(ss)) * 1000)
            elif target:
                target_ms = int(float(target) * 1000)
        except (TypeError, ValueError):
            target_ms = 0
        base_points = max(1, min(1000, int(challenge.get("points", 100) or 100)))
        score = base_points
        if target_ms > 0:
            score = max(1, min(base_points, int(round(base_points * target_ms / ms))))
        submission_id = hashlib.sha256(
            f"{guild_id}:{challenge_id}:{user.user_id}".encode()
        ).hexdigest()
        existing = await self.bot.db.rsl_weekly_challenge_submissions.find_one(
            {"_id": submission_id, "guild_id": str(guild_id)}
        )
        if existing and existing.get("status") == "approved":
            raise web.HTTPConflict(text="You already have an approved submission for this challenge.")
        doc = {
            "_id": submission_id,
            "guild_id": str(guild_id),
            "challenge_id": challenge_id,
            "user_id": str(user.user_id),
            "time": lap,
            "ms": ms,
            "proof_url": proof,
            "score": score,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        await self.bot.db.rsl_weekly_challenge_submissions.update_one(
            {"_id": submission_id, "guild_id": str(guild_id)},
            {"$set": doc},
            upsert=True,
        )
        await self._audit(str(guild_id), str(user.user_id), f"Weekly RSL challenge submission: {challenge_id}")
        return web.json_response({"ok": True, "status": "pending", "score": score})

    async def admin_weekly_challenge_create(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        title = str(payload.get("title") or "").strip()[:140]
        prompt = str(payload.get("prompt") or "").strip()[:1000]
        course = str(payload.get("course") or "").strip()[:140]
        car = str(payload.get("car") or "").strip()[:140]
        target = str(payload.get("target_time") or "").strip()[:30]
        if not title or not prompt or not course or not car:
            raise web.HTTPBadRequest(text="Title, prompt, track, and car are required.")
        try:
            week_start = datetime.fromisoformat(str(payload.get("week_start") or "").replace("Z", "+00:00"))
            if week_start.tzinfo is None:
                week_start = week_start.replace(tzinfo=timezone.utc)
            week_start = week_start.astimezone(timezone.utc)
        except Exception:
            now = datetime.now(timezone.utc)
            week_start = now - timedelta(days=now.weekday(), hours=now.hour, minutes=now.minute, seconds=now.second, microseconds=now.microsecond)
        week_key = week_start.strftime("%G-W%V")
        challenge_id = f"{guild_id}_{week_key}"
        week_end = week_start + timedelta(days=7)
        try:
            points = max(1, min(1000, int(payload.get("points", 100) or 100)))
        except (TypeError, ValueError):
            points = 100
        now = time.time()
        await self.bot.db.rsl_weekly_challenges.update_one(
            {"_id": challenge_id, "guild_id": str(guild_id)},
            {"$set": {
                "guild_id": str(guild_id), "week": week_key, "title": title, "prompt": prompt,
                "course": course, "car": car, "target_time": target, "points": points,
                "week_start": week_start.timestamp(), "week_end": week_end.timestamp(),
                "status": "published", "updated_at": now, "created_by": str(user.user_id),
            }, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        await self._audit(str(guild_id), str(user.user_id), f"Published weekly RSL challenge: {challenge_id}")
        return web.json_response({"ok": True, "challenge_id": challenge_id, "week": week_key})

    async def admin_weekly_challenge_review_queue(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        rows = []
        cursor = self.bot.db.rsl_weekly_challenge_submissions.find(
            {"guild_id": str(guild_id), "status": "pending"}
        ).sort("created_at", 1).limit(100)
        async for row in cursor:
            challenge = await self.bot.db.rsl_weekly_challenges.find_one(
                {"_id": str(row.get("challenge_id") or ""), "guild_id": str(guild_id)}
            ) or {}
            rows.append({
                "id": str(row.get("_id") or ""),
                "challenge_id": str(row.get("challenge_id") or ""),
                "challenge": str(challenge.get("title") or row.get("challenge_id") or ""),
                "user_id": str(row.get("user_id") or ""),
                "time": str(row.get("time") or ""),
                "proof_url": str(row.get("proof_url") or ""),
                "score": int(row.get("score", 0) or 0),
            })
        return web.json_response({"rows": rows})

    async def admin_weekly_challenge_review(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        submission_id = str(payload.get("submission_id") or "").strip()
        action = str(payload.get("action") or "").strip().lower()
        if action not in {"approve", "reject"} or not submission_id:
            raise web.HTTPBadRequest(text="submission_id and approve/reject action are required.")
        result = await self.bot.db.rsl_weekly_challenge_submissions.update_one(
            {"_id": submission_id, "guild_id": str(guild_id), "status": "pending"},
            {"$set": {
                "status": "approved" if action == "approve" else "rejected",
                "reviewed_by": str(user.user_id), "reviewed_at": time.time(),
            }},
        )
        if result.modified_count != 1:
            raise web.HTTPNotFound(text="Pending challenge submission not found.")
        await self._audit(str(guild_id), str(user.user_id), f"Weekly challenge submission {action}: {submission_id}")
        return web.json_response({"ok": True, "status": "approved" if action == "approve" else "rejected"})
