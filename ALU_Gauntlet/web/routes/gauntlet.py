import hashlib
"""RSL web gauntlet route family."""
from .._web_context import *
from ...core.rsl_recovery import reconcile_processing_challenges
from .reference_guides import CommunityGuidesMixin
from .reference_history import HistoricalReferenceMixin
from .reference_events import CareerEventReferenceMixin
from .reference_challenges import WeeklyChallengeMixin
from .reference_beats import BeatReferenceMixin
from .reference_reputation import ReferenceReputationMixin

class GauntletRoutesMixin(ReferenceReputationMixin, BeatReferenceMixin, WeeklyChallengeMixin, CareerEventReferenceMixin, HistoricalReferenceMixin, CommunityGuidesMixin):
    async def rsl_command_center_page(self, request: web.Request) -> web.StreamResponse:
        """Unified player/staff command center for activity, records, notifications, and health."""
        await self.require_user(request)
        return await self._page_response("rsl-command-center.html", request)

    async def gauntlet_registration_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-registration.html", request)

    async def gauntlet_defense_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-defense.html", request)

    async def gauntlet_matches_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-matches.html", request)

    async def gauntlet_career_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-career.html", request)

    async def xp_me(self, request: web.Request) -> web.Response:
        from ...core.rsl_xp import get_settings, progress_for_xp
        user, guild_id, _ = await self.require_guild_member(request)
        doc = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        settings = await get_settings(self.bot.db, guild_id)
        xp = int(doc.get("rsl_xp", 0) or 0)
        return web.json_response({"user_id": str(user.user_id), "name": str(doc.get("game_id") or doc.get("username") or user.username), "xp": xp, **progress_for_xp(xp, settings), "weekly_xp": int(doc.get("rsl_xp_weekly", 0) or 0), "monthly_xp": int(doc.get("rsl_xp_monthly", 0) or 0), "voice_seconds": int(doc.get("rsl_xp_voice_seconds", 0) or 0), "reactions": int(doc.get("rsl_xp_reaction_count", 0) or 0), "activity": int(doc.get("overall_activity_score", 0) or 0)})

    async def xp_history(self, request: web.Request) -> web.Response:
        from ...core.rsl_xp import xp_history
        user, guild_id, _ = await self.require_guild_member(request)
        return web.json_response({"rows": await xp_history(self.bot.db, guild_id, str(user.user_id), limit=50)})

    async def xp_leaderboard(self, request: web.Request) -> web.Response:
        from ...core.rsl_xp import leaderboard
        user = await self.require_user(request)
        live_guild_ids = await self._live_guild_ids_for_user(user)
        guild_id = str(request.query.get("guild_id") or (sorted(live_guild_ids)[0] if live_guild_ids else ""))
        if guild_id not in live_guild_ids:
            raise web.HTTPForbidden(text="You are not a member of that server.")
        period = str(request.query.get("period", "all")).lower()
        if period not in {"all", "weekly", "monthly"}:
            raise web.HTTPBadRequest(text="Invalid leaderboard period.")
        return web.json_response({"period": period, "rows": await leaderboard(self.bot.db, guild_id, period=period)})

    async def xp_settings(self, request: web.Request) -> web.Response:
        from ...core.rsl_xp import get_settings
        _, guild_id, _ = await self.require_admin(request)
        return web.json_response(await get_settings(self.bot.db, guild_id))

    async def gauntlet_leaderboard_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-leaderboard.html", request)

    async def gauntlet_references_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-references.html", request)

    async def gauntlet_references(self, request: web.Request) -> web.Response:
        """Return references for the signed-in driver in the active connected server."""
        user, guild_id, _ = await self.require_guild_member(request)
        profile=await self.bot.db.drivers.find_one({"_id":f"{guild_id}_{user.user_id}"}) or {}
        best_times=profile.get("best_times") or profile.get("track_records") or {}
        refs=[]
        def safe_int(value: Any) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0
        async for item in self.bot.db.gauntlet_references.find({"guild_id":guild_id}).sort("created_at",-1):
            course=str(item.get("course","")); mine=best_times.get(course) if isinstance(best_times,dict) else None
            if isinstance(mine,dict): my_time=mine.get("lap_time") or mine.get("lap_time_str") or mine.get("time"); my_rank=mine.get("car_rank"); my_car=mine.get("car")
            else: my_time,my_rank,my_car=(mine if mine else None),None,None
            refs.append({"id":str(item.get("_id")),"course":course,"title":str(item.get("title","")),"driver":str(item.get("driver","")),"time":str(item.get("time","")),"car":str(item.get("car","")),"car_rank":safe_int(item.get("car_rank",item.get("car_performance",0))),"video_url":str(item.get("video_url","")),"description":str(item.get("description","")),"official":bool(item.get("official",False)),"created_by":str(item.get("created_by") or item.get("submitted_by") or ""),"my_best_time":str(my_time or ""),"my_car":str(my_car or ""),"my_car_rank":safe_int(my_rank)})
        submissions=[]
        async for item in self.bot.db.reference_pending.find({"guild_id":guild_id,"user_id":str(user.user_id)}).sort("created_at",-1).limit(50):
            submissions.append({"id":str(item.get("_id")),"course":str(item.get("course") or item.get("track") or ""), "title":str(item.get("title") or ""), "driver":str(item.get("driver") or ""), "time":str(item.get("time") or item.get("lap_time") or ""), "car":str(item.get("car") or ""), "video_url":str(item.get("video_url") or item.get("video_reference") or ""), "description":str(item.get("description") or ""), "status":str(item.get("status") or "pending")})
        member=self.bot.get_guild(int(guild_id)).get_member(int(user.user_id)) if self.bot.get_guild(int(guild_id)) else None
        return web.json_response({"courses":list(ALU_TRACKS),"references":refs,"submissions":submissions,"viewer_id":str(user.user_id),"is_staff":bool(member and (member.guild_permissions.manage_guild or member.guild_permissions.administrator))})

    async def gauntlet_reference_submit(self, request: web.Request) -> web.Response:
        """Submit a player reference video to the guild-scoped moderation queue."""
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        course = str(payload.get("course", "")).strip()
        title = str(payload.get("title", "")).strip()[:120]
        video_url = str(payload.get("video_url", "")).strip()[:500]
        if course not in ALU_TRACKS or not title or not video_url:
            raise web.HTTPBadRequest(text="Course, title and video URL are required.")
        if not (video_url.startswith("https://") or video_url.startswith("http://")):
            raise web.HTTPBadRequest(text="Video URL must be an http(s) URL.")
        try:
            car_rank = max(0, int(payload.get("car_rank", 0) or 0))
        except (TypeError, ValueError):
            car_rank = 0
        profile = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        driver_name = str(profile.get("game_id") or profile.get("username") or getattr(user, "display_name", "") or user.user_id)[:100]
        fingerprint = hashlib.sha256(f"{guild_id}:{user.user_id}:{course.casefold()}:{video_url.casefold()}".encode()).hexdigest()
        submission_id = f"web_{guild_id}_{user.user_id}_{fingerprint[:24]}"
        existing = await self.bot.db.reference_pending.find_one({"_id": submission_id, "guild_id": str(guild_id)})
        if existing:
            if existing.get("status") == "pending":
                raise web.HTTPConflict(text="This reference is already pending staff review.")
            if existing.get("status") == "approved":
                raise web.HTTPConflict(text="This reference has already been approved.")
        now = time.time()
        doc = {
            "_id": submission_id, "guild_id": str(guild_id), "user_id": str(user.user_id),
            "driver": driver_name, "course": course, "track": course, "title": title,
            "time": str(payload.get("time", "")).strip()[:30], "lap_time": str(payload.get("time", "")).strip()[:30],
            "car": str(payload.get("car", "")).strip()[:100], "car_rank": car_rank,
            "video_url": video_url, "video_reference": video_url,
            "description": str(payload.get("description", "")).strip()[:1000],
            "status": "pending", "delivery_status": "web_pending", "fingerprint": fingerprint,
            "submitted_at": now, "created_at": now,
        }
        try:
            await self.bot.db.reference_pending.insert_one(doc)
        except Exception as exc:
            if type(exc).__name__ == "DuplicateKeyError":
                raise web.HTTPConflict(text="This reference submission already exists.") from exc
            raise
        await self._audit(str(guild_id), str(user.user_id), "Gauntlet reference submitted for review")
        return web.json_response({"ok": True, "id": submission_id, "status": "pending"})

    async def gauntlet_reference_notes(self, request: web.Request) -> web.Response:
        """Read public notes plus the signed-in player's private notes for a reference."""
        user, guild_id, _ = await self.require_guild_member(request)
        reference_id = str(request.match_info.get("reference_id", "")).strip()
        public_notes, own_notes = [], []
        cursor = self.bot.db.gauntlet_reference_notes.find({
            "guild_id": str(guild_id), "reference_id": reference_id,
            "$or": [{"visibility": "public"}, {"user_id": str(user.user_id)}],
        }).sort("created_at", 1).limit(100)
        async for row in cursor:
            item = {"id": str(row.get("_id", "")), "user_id": str(row.get("user_id", "")),
                    "note": str(row.get("note", "")), "seconds": float(row.get("seconds", 0) or 0),
                    "visibility": str(row.get("visibility", "public")), "created_at": row.get("created_at") or 0}
            if item["visibility"] == "public":
                public_notes.append(item)
            if item["user_id"] == str(user.user_id):
                own_notes.append(item)
        return web.json_response({"public": public_notes, "mine": own_notes})

    async def gauntlet_reference_note_action(self, request: web.Request) -> web.Response:
        """Create or delete a note owned by the signed-in player."""
        user, guild_id, _ = await self.require_guild_member(request)
        reference_id = str(request.match_info.get("reference_id", "")).strip()
        from bson import ObjectId
        try:
            oid = ObjectId(reference_id)
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid reference id.") from exc
        reference = await self.bot.db.gauntlet_references.find_one({"_id": oid, "guild_id": str(guild_id)})
        if not reference:
            raise web.HTTPNotFound(text="Reference not found.")
        if request.method == "DELETE":
            note_id = str(request.query.get("note_id", "")).strip()
            if not note_id:
                raise web.HTTPBadRequest(text="Note id is required.")
            result = await self.bot.db.gauntlet_reference_notes.delete_one({
                "_id": note_id, "guild_id": str(guild_id), "reference_id": reference_id, "user_id": str(user.user_id),
            })
            if result.deleted_count != 1:
                raise web.HTTPNotFound(text="Note not found.")
            return web.json_response({"ok": True})
        payload = await self._json_object(request)
        note = str(payload.get("note", "")).strip()[:500]
        if not note:
            raise web.HTTPBadRequest(text="Note text is required.")
        try:
            seconds = max(0.0, min(7200.0, float(payload.get("seconds", 0) or 0)))
        except (TypeError, ValueError):
            seconds = 0.0
        visibility = str(payload.get("visibility", "private")).strip().lower()
        if visibility not in {"private", "public"}:
            visibility = "private"
        note_id = hashlib.sha256(f"{guild_id}:{user.user_id}:{reference_id}:{seconds}:{note}".encode()).hexdigest()[:32]
        doc = {"_id": note_id, "guild_id": str(guild_id), "reference_id": reference_id, "user_id": str(user.user_id),
               "note": note, "seconds": seconds, "visibility": visibility, "created_at": time.time()}
        try:
            await self.bot.db.gauntlet_reference_notes.insert_one(doc)
        except Exception as exc:
            if type(exc).__name__ != "DuplicateKeyError":
                raise
        return web.json_response({"ok": True, "id": note_id, "visibility": visibility, "seconds": seconds})

    async def gauntlet_reference_practice_plan(self, request: web.Request) -> web.Response:
        """Build a practice plan from the player's best laps versus timed references."""
        user, guild_id, _ = await self.require_guild_member(request)
        personal = {}
        async for row in self.bot.db.lap_times.find({"guild_id": str(guild_id), "user_id": str(user.user_id)}).limit(500):
            try:
                ms = int(row.get("best_ms") or 0)
            except (TypeError, ValueError):
                ms = 0
            track = str(row.get("track") or "").strip()
            if track and ms > 0:
                personal[track] = min(ms, personal.get(track, 10**18))
        rows = []
        async for ref in self.bot.db.gauntlet_references.find({"guild_id": str(guild_id), "status": "approved"}).sort("created_at", -1).limit(500):
            track = str(ref.get("course") or ref.get("track") or "").strip()
            raw = ref.get("time") or ref.get("lap_time")
            try:
                if isinstance(raw, str) and ":" in raw:
                    mm, ss = raw.split(":", 1)
                    ref_seconds = float(mm) * 60 + float(ss)
                else:
                    ref_seconds = float(raw)
            except (TypeError, ValueError):
                continue
            if not track or ref_seconds <= 0 or track not in personal:
                continue
            personal_seconds = personal[track] / 1000.0
            gap = personal_seconds - ref_seconds
            if gap > 0.05:
                rows.append({"course": track, "your_time": personal_seconds, "reference_time": ref_seconds, "gap": gap, "title": str(ref.get("title") or ""), "video_url": str(ref.get("video_url") or "")})
        rows.sort(key=lambda x: x["gap"], reverse=True)
        return web.json_response({"rows": rows[:20]})

    async def gauntlet_reference_personal_records(self, request: web.Request) -> web.Response:
        """Return the signed-in driver's guild-scoped personal bests and reference gaps."""
        user, guild_id, _ = await self.require_guild_member(request)
        uid, guild = str(user.user_id), str(guild_id)
        track_filter = str(request.query.get("track") or "").strip().casefold()
        rows = []
        lap_rows = await self.bot.db.lap_times.find({"guild_id": guild, "user_id": uid}).sort("best_ms", 1).limit(500).to_list(length=500)

        def parse_ms(value):
            try:
                text = str(value or "").strip().replace(",", ".")
                if ":" in text:
                    parts = text.split(":")
                    if len(parts) != 2:
                        return 0
                    return int(round((float(parts[0]) * 60 + float(parts[1])) * 1000))
                return int(round(float(text) * 1000))
            except (TypeError, ValueError):
                return 0

        def format_ms(ms):
            ms = max(0, int(ms))
            minutes, rem = divmod(ms, 60000)
            seconds, millis = divmod(rem, 1000)
            return f"{minutes}:{seconds:02d}.{millis:03d}"

        universal = {}
        async for record in self.bot.db.map_records.find({}).limit(5000):
            track = str(record.get("track") or "").strip()
            if track:
                universal[track.casefold()] = record

        references = {}
        async for ref in self.bot.db.gauntlet_references.find({
            "guild_id": guild,
            "status": {"$in": ["approved", "published"]},
        }).sort("created_at", -1).limit(2000):
            track = str(ref.get("course") or ref.get("track") or "").strip()
            ref_ms = parse_ms(ref.get("time") or ref.get("lap_time"))
            if not track or ref_ms <= 0:
                continue
            key = track.casefold()
            current = references.get(key)
            candidate = {
                "time_ms": ref_ms,
                "title": str(ref.get("title") or "RSL Reference"),
                "car": str(ref.get("car") or ""),
                "driver": str(ref.get("driver") or ""),
                "official": bool(ref.get("official", False)),
            }
            if current is None or ref_ms < current["time_ms"] or (ref_ms == current["time_ms"] and candidate["official"] and not current["official"]):
                references[key] = candidate

        for row in lap_rows:
            track = str(row.get("track") or "").strip()
            if not track or (track_filter and track.casefold() != track_filter):
                continue
            try:
                best_ms = int(row.get("best_ms") or 0)
            except (TypeError, ValueError):
                best_ms = 0
            if best_ms <= 0:
                continue
            record = universal.get(track.casefold()) or {}
            is_record = str(record.get("user_id") or "") == uid and int(record.get("best_ms") or 0) == best_ms
            ref = references.get(track.casefold())
            gap_ms = (best_ms - int(ref["time_ms"])) if ref else None
            rows.append({
                "track": track,
                "best_ms": best_ms,
                "best_lap_time": str(row.get("best_lap_time") or row.get("time") or format_ms(best_ms)),
                "car": str(row.get("car") or row.get("car_name") or ""),
                "car_rank": int(row.get("car_rank") or row.get("car_performance") or 0),
                "track_record": bool(is_record),
                "reference_time_ms": int(ref["time_ms"]) if ref else None,
                "reference_time": format_ms(ref["time_ms"]) if ref else "",
                "reference_gap_ms": gap_ms,
                "reference_gap": format_ms(abs(gap_ms)) if gap_ms is not None else "",
                "reference_beaten": bool(gap_ms is not None and gap_ms < 0),
                "reference_title": str(ref["title"]) if ref else "",
                "reference_car": str(ref["car"]) if ref else "",
            })
        rows.sort(key=lambda x: x["best_ms"])
        return web.json_response({
            "rows": rows[:200],
            "summary": {
                "tracks": len(rows),
                "track_records": sum(1 for row in rows if row["track_record"]),
                "references_beaten": sum(1 for row in rows if row["reference_beaten"]),
                "references_compared": sum(1 for row in rows if row["reference_time_ms"] is not None),
            },
        })

    async def gauntlet_reference_practice_saved(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        row = await self.bot.db.gauntlet_practice_plans.find_one({"guild_id": str(guild_id), "user_id": str(user.user_id)})
        if not row:
            return web.json_response({"plan": None})
        return web.json_response({"plan": {"name": str(row.get("name") or "My Practice Plan"), "cars": list(row.get("cars") or [])[:5], "tracks": list(row.get("tracks") or [])[:20], "updated_at": row.get("updated_at")}})

    async def gauntlet_reference_practice_save(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        name = str(payload.get("name") or "My Practice Plan").strip()[:80] or "My Practice Plan"
        raw_cars = payload.get("cars") or []
        if isinstance(raw_cars, str):
            raw_cars = raw_cars.split(",")
        cars = []
        if isinstance(raw_cars, (list, tuple)):
            for value in raw_cars:
                car = str(value or "").strip()[:100]
                if car and car.casefold() not in {x.casefold() for x in cars}:
                    cars.append(car)
                if len(cars) >= 5:
                    break
        raw_tracks = payload.get("tracks") or []
        if isinstance(raw_tracks, str):
            raw_tracks = raw_tracks.split(",")
        tracks = []
        if isinstance(raw_tracks, (list, tuple)):
            for value in raw_tracks:
                track = str(value or "").strip()[:120]
                if track and track.casefold() not in {x.casefold() for x in tracks}:
                    tracks.append(track)
                if len(tracks) >= 20:
                    break
        if not cars:
            raise web.HTTPBadRequest(text="Add at least one practice car.")
        now = time.time()
        await self.bot.db.gauntlet_practice_plans.update_one(
            {"guild_id": str(guild_id), "user_id": str(user.user_id)},
            {"$set": {"name": name, "cars": cars, "tracks": tracks, "updated_at": now},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return web.json_response({"ok": True, "name": name, "cars": cars, "tracks": tracks})

    async def gauntlet_reference_practice_delete(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        await self.bot.db.gauntlet_practice_plans.delete_one({"guild_id": str(guild_id), "user_id": str(user.user_id)})
        return web.json_response({"ok": True})

    async def gauntlet_reference_explorer(self, request: web.Request) -> web.Response:
        """Return guild-scoped car × track reference rows for exploration."""
        _, guild_id, _ = await self.require_guild_member(request)
        course_filter = str(request.query.get("course") or "").strip()
        car_filter = str(request.query.get("car") or "").strip().casefold()
        rows_by_key = {}
        cars, tracks = set(), set()
        cursor = self.bot.db.gauntlet_references.find({
            "guild_id": str(guild_id),
            "status": {"$in": ["approved", "published"]},
        }).sort("created_at", -1).limit(1000)
        def parse_seconds(value):
            try:
                text = str(value or "").strip().replace(",", ".")
                if ":" in text:
                    parts = text.split(":")
                    if len(parts) == 2:
                        return float(parts[0]) * 60 + float(parts[1])
                return float(text)
            except (TypeError, ValueError):
                return 0.0
        async for ref in cursor:
            track = str(ref.get("course") or ref.get("track") or "").strip()
            car = str(ref.get("car") or "").strip()
            if not track or not car or (course_filter and track != course_filter):
                continue
            if car_filter and car.casefold() != car_filter:
                continue
            seconds = parse_seconds(ref.get("time") or ref.get("lap_time"))
            if seconds <= 0:
                continue
            cars.add(car); tracks.add(track)
            key = (track.casefold(), car.casefold())
            row = rows_by_key.get(key)
            candidate = {
                "course": track, "car": car, "time": seconds,
                "title": str(ref.get("title") or ""),
                "driver": str(ref.get("driver") or ""),
                "video_url": str(ref.get("video_url") or ""),
                "car_rank": int(ref.get("car_rank") or ref.get("car_performance") or 0),
                "official": bool(ref.get("official", False)),
            }
            if row is None or seconds < row["time"] or (seconds == row["time"] and candidate["official"] and not row["official"]):
                rows_by_key[key] = candidate
        rows = sorted(rows_by_key.values(), key=lambda x: (x["course"].casefold(), x["time"], x["car"].casefold()))
        return web.json_response({
            "rows": rows[:500],
            "cars": sorted(cars, key=str.casefold),
            "tracks": sorted(tracks, key=str.casefold),
        })

    async def gauntlet_reference_car_comparison(self, request: web.Request) -> web.Response:
        """Return guild-scoped car comparison data from approved RSL references."""
        _, guild_id, _ = await self.require_guild_member(request)
        raw_cars = str(request.query.get("cars") or "").split(",")
        selected = []
        seen = set()
        for value in raw_cars:
            car = value.strip()
            key = car.casefold()
            if car and key not in seen:
                seen.add(key); selected.append(car)
        selected = selected[:4]
        if len(selected) < 2:
            return web.json_response({"cars": [], "tracks": [], "rows": [], "message": "Select at least two cars."})
        query = {"guild_id": str(guild_id), "status": {"$in": ["approved", "published"]}}
        refs = []
        async for ref in self.bot.db.gauntlet_references.find(query).sort("created_at", -1).limit(2000):
            car = str(ref.get("car") or "").strip()
            if not car or car.casefold() not in seen:
                continue
            track = str(ref.get("course") or ref.get("track") or "").strip()
            if not track:
                continue
            raw = ref.get("time") or ref.get("lap_time")
            try:
                text = str(raw or "").strip().replace(",", ".")
                seconds = (float(text.split(":", 1)[0]) * 60 + float(text.split(":", 1)[1])) if ":" in text else float(text)
            except (TypeError, ValueError):
                continue
            if seconds <= 0:
                continue
            refs.append((track, car, seconds, bool(ref.get("official", False)), str(ref.get("title") or ""), str(ref.get("driver") or ""), str(ref.get("video_url") or "")))
        best = {}
        for track, car, seconds, official, title, driver, video_url in refs:
            key = (track.casefold(), car.casefold())
            row = best.get(key)
            if row is None or seconds < row["time"] or (seconds == row["time"] and official and not row["official"]):
                best[key] = {"track": track, "car": car, "time": seconds, "official": official, "title": title, "driver": driver, "video_url": video_url}
        tracks = sorted({row["track"] for row in best.values()}, key=str.casefold)
        rows = []
        for track in tracks:
            entries = [best[(track.casefold(), car.casefold())] for car in selected if (track.casefold(), car.casefold()) in best]
            if len(entries) >= 2:
                fastest = min(row["time"] for row in entries)
                rows.append({"track": track, "entries": entries, "spread": max(row["time"] for row in entries) - fastest, "fastest_car": min(entries, key=lambda row: row["time"])["car"]})
        return web.json_response({"cars": selected, "tracks": tracks, "rows": rows[:200]})

    async def gauntlet_reference_requests(self, request: web.Request) -> web.Response:
        """Return community feature/data requests for the selected guild."""
        staff_view = str(request.query.get("staff") or "").strip() == "1"
        if staff_view:
            _, guild_id, _guild = await self.require_admin(request)
        else:
            _, guild_id, _guild = await self.require_guild_member(request)
        kind = str(request.query.get("kind") or "").strip().lower()
        query = {"guild_id": str(guild_id)}
        if not staff_view:
            query["status"] = {"$in": ["open", "planned", "in_progress", "completed"]}
        if kind:
            query["kind"] = kind
        rows = []
        async for item in self.bot.db.reference_requests.find(query).sort("votes", -1).sort("created_at", -1).limit(100):
            rows.append({
                "id": str(item.get("_id")), "kind": str(item.get("kind") or "feature"),
                "title": str(item.get("title") or ""), "body": str(item.get("body") or ""),
                "evidence_url": str(item.get("evidence_url") or ""), "status": str(item.get("status") or "open"),
                "priority": str(item.get("priority") or "normal"), "resolution": str(item.get("resolution") or ""),
                "resolved_at": item.get("resolved_at"), "resolved_by": str(item.get("resolved_by") or ""),
                "votes": int(item.get("votes") or 0), "driver": str(item.get("driver") or ""),
                "created_at": item.get("created_at"),
            })
        return web.json_response({"rows": rows})

    async def gauntlet_reference_request_action(self, request: web.Request) -> web.Response:
        """Create or vote on a community feature/data request."""
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        action = str(payload.get("action") or "create").strip().lower()
        if action == "vote":
            from bson import ObjectId
            try:
                rid = ObjectId(str(payload.get("id") or ""))
            except Exception as exc:
                raise web.HTTPBadRequest(text="Invalid request id.") from exc
            row = await self.bot.db.reference_requests.find_one({"_id": rid, "guild_id": str(guild_id)})
            if not row:
                raise web.HTTPNotFound(text="Request not found.")
            key = f"{guild_id}:{rid}:{user.user_id}"
            await self.bot.db.reference_request_votes.update_one(
                {"_id": hashlib.sha256(key.encode()).hexdigest()},
                {"$setOnInsert": {"guild_id": str(guild_id), "request_id": rid, "user_id": str(user.user_id), "created_at": time.time()}},
                upsert=True,
            )
            votes = await self.bot.db.reference_request_votes.count_documents({"guild_id": str(guild_id), "request_id": rid})
            await self.bot.db.reference_requests.update_one({"_id": rid, "guild_id": str(guild_id)}, {"$set": {"votes": int(votes)}})
            return web.json_response({"ok": True, "votes": int(votes)})
        kind = str(payload.get("kind") or "feature").strip().lower()
        title = str(payload.get("title") or "").strip()[:120]
        body = str(payload.get("body") or "").strip()[:1200]
        evidence_url = str(payload.get("evidence_url") or "").strip()[:500]
        priority = str(payload.get("priority") or "normal").strip().lower()
        if priority not in {"low", "normal", "high"}:
            priority = "normal"
        if kind != "feature":
            priority = "normal"
        if kind not in {"feature", "missing_data", "bad_data", "broken_video", "duplicate"} or not title or not body:
            raise web.HTTPBadRequest(text="Valid request type, title and description are required.")
        if evidence_url and not evidence_url.startswith(("https://", "http://")):
            raise web.HTTPBadRequest(text="Evidence URL must use http or https.")
        driver = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        from bson import ObjectId
        fingerprint = hashlib.sha256(
            f"{guild_id}:{kind}:{title.casefold()}:{body.casefold()}".encode()
        ).hexdigest()
        existing = await self.bot.db.reference_requests.find_one(
            {"guild_id": str(guild_id), "fingerprint": fingerprint}
        )
        if existing:
            return web.json_response({"ok": True, "id": str(existing["_id"]), "status": str(existing.get("status") or "open"), "duplicate": True})
        row = {
            "_id": ObjectId(), "guild_id": str(guild_id), "kind": kind, "title": title, "body": body,
            "evidence_url": evidence_url, "priority": priority, "fingerprint": fingerprint,
            "status": "open", "votes": 0,
            "driver": str(driver.get("game_id") or driver.get("username") or user.username),
            "user_id": str(user.user_id), "created_at": time.time(),
        }
        await self.bot.db.reference_requests.insert_one(row)
        await self._audit(str(guild_id), str(user.user_id), "Community reference request submitted")
        return web.json_response({"ok": True, "id": str(row["_id"]), "status": "open"})

    async def admin_reference_request_action(self, request: web.Request) -> web.Response:
        """Update a community request status or staff resolution note."""
        admin_user, guild_id, _guild = await self.require_admin(request)
        payload = await self._json_object(request)
        from bson import ObjectId
        try:
            request_id = ObjectId(str(payload.get("id") or ""))
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid request id.") from exc
        status = str(payload.get("status") or "").strip().lower()
        allowed = {"open", "planned", "in_progress", "completed", "rejected"}
        if status not in allowed:
            raise web.HTTPBadRequest(text="Invalid request status.")
        priority = str(payload.get("priority") or "normal").strip().lower()
        if priority not in {"low", "normal", "high"}:
            raise web.HTTPBadRequest(text="Invalid request priority.")
        resolution = str(payload.get("resolution") or "").strip()[:1200]
        now = time.time()
        result = await self.bot.db.reference_requests.update_one(
            {"_id": request_id, "guild_id": str(guild_id)},
            {"$set": {"status": status, "priority": priority, "resolution": resolution, "resolved_at": now if status in {"completed", "rejected"} else None,
                      "resolved_by": str(admin_user.id) if getattr(admin_user, "id", None) else ""}},
        )
        if result.matched_count != 1:
            raise web.HTTPNotFound(text="Request not found.")
        await self._audit(str(guild_id), str(admin_user.id), f"Community reference request marked {status}")
        return web.json_response({"ok": True, "status": status})
    
    async def gauntlet_reference_intel(self, request: web.Request) -> web.Response:
        """Return community track intel for the selected guild."""
        _, guild_id, _ = await self.require_guild_member(request)
        course = str(request.query.get("course", "")).strip()
        car = str(request.query.get("car", "")).strip()[:100]
        query = {"guild_id": str(guild_id)}
        if course:
            query["course"] = course
        if car:
            query["car"] = {"$regex": "^" + re.escape(car) + "$", "$options": "i"}
        rows = []
        async for item in self.bot.db.reference_intel.find(query).sort("created_at", -1).limit(200):
            rows.append({
                "id": str(item.get("_id")),
                "course": str(item.get("course") or ""),
                "kind": str(item.get("kind") or "tip"),
                "title": str(item.get("title") or ""),
                "body": str(item.get("body") or ""),
                "seconds": int(item.get("seconds") or 0),
                "driver": str(item.get("driver") or ""),
                "user_id": str(item.get("user_id") or ""),
                "helpful": int(item.get("helpful") or 0),
                "car": str(item.get("car") or ""),
                "video_url": str(item.get("video_url") or ""),
                "created_at": item.get("created_at"),
            })
        return web.json_response({"rows": rows})

    async def gauntlet_reference_intel_action(self, request: web.Request) -> web.Response:
        """Create or vote on community track intel."""
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        action = str(payload.get("action") or "create").strip().lower()
        if action == "vote":
            from bson import ObjectId
            try:
                iid = ObjectId(str(payload.get("id") or ""))
            except Exception as exc:
                raise web.HTTPBadRequest(text="Invalid intel id.") from exc
            row = await self.bot.db.reference_intel.find_one({"_id": iid, "guild_id": str(guild_id)})
            if not row:
                raise web.HTTPNotFound(text="Intel not found.")
            key = f"{guild_id}:{iid}:{user.user_id}"
            await self.bot.db.reference_intel_votes.update_one(
                {"_id": hashlib.sha256(key.encode()).hexdigest()},
                {"$setOnInsert": {"guild_id": str(guild_id), "intel_id": iid, "user_id": str(user.user_id), "created_at": time.time()}},
                upsert=True,
            )
            votes = await self.bot.db.reference_intel_votes.count_documents({"guild_id": str(guild_id), "intel_id": iid})
            await self.bot.db.reference_intel.update_one({"_id": iid, "guild_id": str(guild_id)}, {"$set": {"helpful": int(votes)}})
            return web.json_response({"ok": True, "helpful": int(votes)})
        course = str(payload.get("course") or "").strip()
        car = str(payload.get("car") or "").strip()[:100]
        video_url = str(payload.get("video_url") or "").strip()[:500]
        if video_url and not re.match(r"^https?://", video_url, re.I):
            raise web.HTTPBadRequest(text="Evidence URL must use http:// or https://.")
        title = str(payload.get("title") or "").strip()[:120]
        body = str(payload.get("body") or "").strip()[:1000]
        kind = str(payload.get("kind") or "tip").strip().lower()
        try:
            seconds = max(0, min(7200, int(payload.get("seconds") or 0)))
        except (TypeError, ValueError):
            seconds = 0
        if course not in ALU_TRACKS or not title or not body or kind not in {"tip", "shortcut", "hazard", "route"}:
            raise web.HTTPBadRequest(text="Valid course, title, body and intel type are required.")
        fingerprint = hashlib.sha256(f"{guild_id}:{user.user_id}:{course}:{kind}:{title.lower()}:{body.lower()}:{seconds}".encode()).hexdigest()
        existing = await self.bot.db.reference_intel.find_one({"_id": fingerprint, "guild_id": str(guild_id)})
        if existing:
            return web.json_response({"ok": True, "id": fingerprint, "duplicate": True})
        driver = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        await self.bot.db.reference_intel.insert_one({
            "_id": fingerprint, "guild_id": str(guild_id), "course": course, "kind": kind,
            "title": title, "body": body, "car": car, "video_url": video_url, "seconds": seconds, "driver": str(driver.get("game_id") or driver.get("username") or user.username),
            "user_id": str(user.user_id), "helpful": 0, "created_at": time.time(),
        })
        await self._audit(str(guild_id), str(user.user_id), "Community reference intel submitted")
        return web.json_response({"ok": True, "id": fingerprint, "status": "published"})

    async def gauntlet_reference_leaderboard(self, request: web.Request) -> web.Response:
        """Return guild-scoped contributor or video-reference standings."""
        _, guild_id, _ = await self.require_guild_member(request)
        guild = str(guild_id)
        mode = str(request.query.get("mode", "contributors")).lower()

        if mode == "videos":
            def parse_reference_time(value):
                text = str(value or "").strip().replace(",", ".")
                if not text:
                    return None
                try:
                    if ":" in text:
                        parts = text.split(":")
                        if len(parts) == 2:
                            return float(parts[0]) * 60.0 + float(parts[1])
                        return None
                    return float(text)
                except (TypeError, ValueError):
                    return None

            rows = []
            async for row in self.bot.db.gauntlet_references.find({"guild_id": guild}):
                seconds = parse_reference_time(row.get("time") or row.get("lap_time"))
                if seconds is None or seconds <= 0:
                    continue
                uid = str(row.get("created_by") or row.get("submitted_by") or "")
                driver = await self.bot.db.drivers.find_one({"_id": f"{guild}_{uid}"}) if uid else None
                rows.append({
                    "id": str(row.get("_id", "")),
                    "course": str(row.get("course") or row.get("track") or ""),
                    "title": str(row.get("title") or "Reference Video"),
                    "driver": str((driver or {}).get("game_id") or (driver or {}).get("username") or uid or "Reference Driver"),
                    "car": str(row.get("car") or ""),
                    "time": str(row.get("time") or row.get("lap_time") or ""),
                    "seconds": seconds,
                    "video_url": str(row.get("video_url") or row.get("video_reference") or ""),
                })
            rows.sort(key=lambda x: (x["seconds"], x["course"].casefold(), x["title"].casefold()))
            return web.json_response({"mode": "videos", "rows": rows[:50]})

        stats = {}
        async for row in self.bot.db.gauntlet_references.find({"guild_id": guild}):
            uid = str(row.get("created_by") or row.get("submitted_by") or "")
            if not uid:
                continue
            item = stats.setdefault(uid, {"user_id": uid, "references": 0, "tracks": set(), "cars": set()})
            item["references"] += 1
            if row.get("course"):
                item["tracks"].add(str(row["course"]))
            if row.get("car"):
                item["cars"].add(str(row["car"]))
        rows = []
        for item in stats.values():
            driver = await self.bot.db.drivers.find_one({"_id": f"{guild}_{item['user_id']}"}) or {}
            rows.append({"user_id": item["user_id"],
                         "driver": str(driver.get("game_id") or driver.get("username") or item["user_id"]),
                         "references": item["references"], "tracks": len(item["tracks"]), "cars": len(item["cars"])})
        rows.sort(key=lambda x: (-x["references"], -x["tracks"], -x["cars"], x["driver"].casefold()))
        return web.json_response({"mode": "contributors", "rows": rows[:50]})

    async def gauntlet_matches(self, request: web.Request) -> web.Response:
        user,guild_id,_=await self.require_guild_member(request); uid=str(user.user_id); active=[]; recent=[]
        current_season = await get_current_season_number(str(guild_id))
        async for item in self.bot.db.active_challenges.find({"guild_id":str(guild_id),"season_number":int(current_season),"$or":[{"challenger_id":uid},{"opponent_id":uid}],"status":{"$in":["active","processing"]}}).sort("created_at",-1).limit(10):
            oppid=str(item.get("opponent_id") if str(item.get("challenger_id"))==uid else item.get("challenger_id")); opp=await self.bot.db.drivers.find_one({"_id":f"{guild_id}_{oppid}"}) or {}
            viewer = await self.bot.db.drivers.find_one({"_id":f"{guild_id}_{uid}"}) or {}
            fair = fair_match_snapshot(viewer, opp)
            active.append({"id":str(item.get("_id","")),"status":str(item.get("status","active")),"role":"challenger" if str(item.get("challenger_id"))==uid else "defender","opponent_id":oppid,"opponent":str(opp.get("game_id") or opp.get("username") or oppid),"courses":item.get("defense_courses") or [],"created_at":item.get("created_at") or item.get("started_at") or time.time(),"fair_match":fair})
        cursor=self.bot.db.matches.find({"guild_id":str(guild_id),"reverted":{"$ne":True},"$or":[{"challenger_id":uid},{"opponent_id":uid}]}).sort("timestamp",-1).limit(20)
        async for match in cursor:
            challenger=str(match.get("challenger_id","")); opponent=str(match.get("opponent_id","")); other=opponent if challenger==uid else challenger
            won=str(match.get("w_id",""))==uid; lost=str(match.get("l_id",""))==uid
            if not(won or lost): continue
            opp=await self.bot.db.drivers.find_one({"_id":f"{guild_id}_{other}"}) or {}
            courses_beat = int(match.get("courses_beat",0) or 0)
            recent.append({"id":str(match.get("_id","")),"opponent_id":other,"opponent":str(opp.get("game_id") or opp.get("username") or other),"result":"WIN" if won else "LOSS","courses":courses_beat,"score":f"{courses_beat}-{5-courses_beat}","rsl_performance_bonus":int(match.get("rsl_performance_bonus",0) or 0),"timestamp":match.get("timestamp") or 0})
        profile = await self.bot.db.drivers.find_one({"_id":f"{guild_id}_{uid}"}) or {}
        dominance = profile.get("rsl_dominance") or {}
        return web.json_response({"active":active,"recent":recent,"dominance":{"total_matches":int(dominance.get("total_matches",0) or 0),"race_wins":int(dominance.get("race_wins",0) or 0),"race_losses":int(dominance.get("race_losses",0) or 0),"score_buckets":dominance.get("score_buckets") or {}}})

    async def gauntlet_submit_match(self, request: web.Request) -> web.Response:
        """Submit five attack runs for the signed-in driver's active challenge."""
        user,guild_id,_=await self.require_guild_member(request)
        payload = await self._json_object(request)
        from ...core.core import parse_lap_time, process_match_result, claim_active_challenge, release_active_challenge
        uid=str(user.user_id); active=await claim_active_challenge(str(guild_id),uid)
        if not active: raise web.HTTPConflict(text="No active challenge is available to submit.")
        try:
            current_season = await get_current_season_number(str(guild_id))
            if int(active.get("season_number", 0) or 0) != int(current_season):
                await release_active_challenge(active["_id"])
                raise web.HTTPConflict(text="This challenge belongs to an older season. Start a new challenge for the current season.")
            rows=payload.get("courses")
            if not isinstance(rows,list) or len(rows)!=5: raise web.HTTPBadRequest(text="Exactly five course results are required.")
            attack=[]; seen=set(); proof_urls=[]
            for n,row in enumerate(rows,1):
                if not isinstance(row,dict): raise web.HTTPBadRequest(text=f"Course {n} is invalid.")
                car=str(row.get("car","")).strip(); lap=str(row.get("lap_time","")).strip(); proof=str(row.get("proof_url","")).strip()
                try: rank=int(row.get("car_rank",0))
                except (TypeError,ValueError): rank=0
                ms=parse_lap_time(lap)
                if not car or car.casefold() in seen or rank<=0 or ms<=0: raise web.HTTPBadRequest(text=f"Course {n} has an invalid car, car rating, or lap time.")
                if not proof.lower().startswith(("http://","https://")): raise web.HTTPBadRequest(text=f"Course {n} requires an image/video proof URL.")
                seen.add(car.casefold()); proof_urls.append(proof)
                attack.append({"lap_time_str":lap,"ms":ms,"car":car,"car_rank":rank,"proof_url":proof})
            defense=active.get("defense_courses") or []
            if len(defense)!=5: raise web.HTTPConflict(text="The saved defense does not contain exactly five courses.")
            result=await process_match_result(str(guild_id),uid,str(active["opponent_id"]),defense,attack,proof_urls[0],active.get("defender_proof_url"),None,settlement_id=f"{active['_id']}:match")
            if not result: raise web.HTTPConflict(text="The match could not be settled.")
            await self.bot.db.matches.update_one(
                {"_id":result["_id"],"guild_id":str(guild_id)},
                {"$set":{
                    "challenger_proof_urls":proof_urls,
                    "race_proofs":[{"race":i+1,"url":proof_urls[i],"track":defense[i].get("track")} for i in range(5)],
                }},
            )
            bonus_checked = False
            try:
                result["rsl_performance_bonus"] = await apply_rsl_performance_bonus(self.bot.db, result)
                bonus_checked = True
            except Exception:
                log.exception("Failed to apply RSL performance margin bonus for match %s", result.get("_id"))
            await self.bot.db.active_challenges.update_one({"_id":active["_id"],"guild_id":str(guild_id),"challenger_id":uid,"status":"processing"},{"$set":{"status":"completed","completed_at":time.time(),"match_id":result["_id"],"ticket_burned":True,"settlement_closed":True,"rsl_bonus_checked":bonus_checked},"$unset":{"processing_at":""}})
            return web.json_response({"ok":True,"match_id":str(result["_id"]),"result":result.get("outcome_desc","Match submitted."),"courses_beat":int(result.get("courses_beat",0) or 0),"rsl_performance_bonus":int(result.get("rsl_performance_bonus",0) or 0)})
        except Exception:
            # Mirror the Discord recovery path: never release a challenge blindly
            # after settlement processing begins. If a deterministic reservation
            # exists, reconcile it; otherwise the processing lock can safely reopen.
            reservation = await self.bot.db.matches.find_one({
                "_id": f"{active['_id']}:match",
                "guild_id": str(guild_id),
            })
            if reservation:
                await reconcile_processing_challenges(self.bot.db, str(guild_id))
            else:
                await release_active_challenge(active["_id"])
            raise

    async def gauntlet_abandon_match(self, request: web.Request) -> web.Response:
        """Quit the signed-in driver's active Gauntlet challenge through the shared settlement path."""
        user, guild_id, _ = await self.require_guild_member(request)
        uid = str(user.user_id)
        from ...core.core import abandon_active_challenge
        active = await self.bot.db.active_challenges.find_one({
            "_id": f"{guild_id}_{uid}",
            "guild_id": str(guild_id),
            "challenger_id": uid,
            "status": "active",
        })
        if not active:
            raise web.HTTPConflict(text="No active Gauntlet match is available to quit.")
        closed = await abandon_active_challenge(str(guild_id), uid, "quit")
        if not closed:
            raise web.HTTPConflict(text="This match changed state before the quit could be recorded.")
        return web.json_response({
            "ok": True,
            "status": "abandoned",
            "message": "Active Gauntlet match closed as abandoned. The consumed ticket was not restored.",
        })

    async def gauntlet_report_match(self, request: web.Request) -> web.Response:
        """Report a completed Gauntlet result for staff review."""
        user, guild_id, _ = await self.require_guild_member(request)
        payload = await self._json_object(request)
        match_id = str(payload.get("match_id") or "").strip()
        reason = str(payload.get("reason") or "").strip()[:500]
        if not match_id:
            raise web.HTTPBadRequest(text="match_id is required.")
        match = await self.bot.db.matches.find_one({"_id": match_id, "guild_id": str(guild_id)})
        if not match:
            raise web.HTTPNotFound(text="Match record not found.")
        if match.get("reverted"):
            raise web.HTTPConflict(text="This match has already been reverted.")
        await self.bot.db.matches.update_one(
            {"_id": match_id, "guild_id": str(guild_id), "reverted": {"$ne": True}},
            {"$set": {
                "reported": True,
                "reported_by": str(user.user_id),
                "reported_at": time.time(),
                "report_reason": reason,
            }},
        )
        await self._audit(str(guild_id), str(user.user_id), f"Gauntlet match reported: {match_id}")
        return web.json_response({"ok": True, "status": "reported", "match_id": match_id})

    async def gauntlet_leaderboard(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        live_guild_ids = await self._live_guild_ids_for_user(user)
        guild_id = str(request.query.get("guild_id") or (sorted(live_guild_ids)[0] if live_guild_ids else ""))
        if guild_id not in live_guild_ids:
            raise web.HTTPForbidden(text="You are not a member of that server.")
        requested_season = request.query.get("season")
        if requested_season:
            try:
                season_number = int(requested_season)
            except ValueError:
                raise web.HTTPBadRequest(text="Invalid season.")
            archive = await self.bot.db.season_history.find_one({"_id": f"{guild_id}_{season_number}"})
            if not archive:
                raise web.HTTPNotFound(text="Archived season not found.")
            return web.json_response({
                "season": season_number,
                "standings": archive.get("standings", []),
                "player_count": int(archive.get("player_count", len(archive.get("standings", []))) or 0),
                "closed_at": archive.get("closed_at"),
            })
        state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
        season_number = int(state.get("season_number", 1) or 1)
        drivers = {}
        async for driver in self.bot.db.drivers.find({
            "guild_id": guild_id,
            "season_registered": True,
            "season_number": season_number,
        }):
            uid = str(driver.get("user_id") or "")
            if not uid:
                continue
            drivers[uid] = {
                "user_id": uid,
                "name": str(driver.get("game_id") or driver.get("username") or uid),
                "elo": int(driver.get("elo", 1000) or 1000),
                "garage_pi": int(driver.get("garage_pi", 0) or 0),
                "played": 0,
                "wins": 0,
            }

        start_at = float(state.get("starts_at", 0) or 0)
        end_at = float(state.get("ends_at", 0) or 0)
        if start_at and end_at and end_at > start_at:
            cursor = self.bot.db.matches.find({
                "guild_id": guild_id,
                "timestamp": {"$gte": start_at, "$lt": end_at},
                "reverted": {"$ne": True},
            }, {"w_id": 1, "l_id": 1, "challenger_id": 1, "opponent_id": 1})
            async for match in cursor:
                for key in ("w_id", "l_id"):
                    uid = str(match.get(key) or "")
                    if uid in drivers:
                        drivers[uid]["played"] += 1
                        if key == "w_id":
                            drivers[uid]["wins"] += 1

        # Overall activity is rebuilt from authoritative RSL records rather than
        # raw message volume. This keeps the public leaderboard aligned with the
        # same cross-mode score used by the seasonal Top Active role.
        activity_rows = await collect_overall_activity_stats(
            self.bot.db,
            guild_id=guild_id,
            season_number=season_number,
        )
        activity_map = {str(item["user_id"]): item for item in activity_rows}
        for uid, row in drivers.items():
            activity = activity_map.get(uid, {})
            row["overall_activity_score"] = int(activity.get("overall_activity_score", 0) or 0)
            row["activity_breakdown"] = {
                key: int(activity.get(key, 0) or 0)
                for key in ("gauntlet_matches", "tournament_matches", "rsl_events", "media_posts", "defenses", "challenges", "approved_activity")
            }

        rows = list(drivers.values())

        def division_for_pi(pi):
            from ...core.core import get_division_for_pi
            return get_division_for_pi(pi).get("name", "Unranked")

        for row in rows:
            row["division"] = division_for_pi(row["garage_pi"])

        rows.sort(key=lambda x: (-x["elo"], x["name"].casefold()))
        divisions = {}
        for row in rows:
            divisions.setdefault(row["division"], []).append(row)

        archives = []
        async for archive in self.bot.db.season_history.find({"guild_id": guild_id}).sort("season_number", -1).limit(20):
            archives.append({
                "season": int(archive.get("season_number", 0) or 0),
                "player_count": int(archive.get("player_count", len(archive.get("standings", []))) or 0),
                "closed_at": archive.get("closed_at"),
            })

        return web.json_response({
            "season": season_number,
            "active": bool(state.get("season_active", False)),
            "starts_at": start_at,
            "ends_at": end_at,
            "divisions": {key: value for key, value in divisions.items()},
            "all": rows,
            "top_overall": rows[:5],
            "most_active": sorted(rows, key=lambda x: (-x["overall_activity_score"], -x["wins"], -x["elo"], x["name"].casefold()))[:5],
            "most_wins": sorted(rows, key=lambda x: (-x["wins"], -x["played"], -x["elo"], x["name"].casefold()))[:5],
            "past_seasons": archives,
        })

    async def leaderboard(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_member(request)
        try:
            limit = max(1, min(100, int(request.query.get("limit", "50"))))
        except ValueError:
            raise web.HTTPBadRequest(text="limit must be an integer.")
        rows = await self.players.list_players(guild_id, limit=limit)
        for player in rows:
            uid = str(player.get("user_id", ""))
            prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{uid}"}) or {}
            connection = prefs.get("asphalt_connection") or {}
            player["game_name"] = prefs.get("game_name", "") or connection.get("game_name", "")
            player["asphalt_verified"] = connection.get("status") == "verified"
        return web.json_response({"players": rows})

    async def rsl_records(self, request: web.Request) -> web.Response:
        """Return public RSL records from authoritative current drivers and matches."""
        _, guild_id, _ = await self.require_guild_member(request)
        guild_id = str(guild_id)
        drivers = await self.bot.db.drivers.find({
            "guild_id": guild_id,
            "season_registered": True,
        }).to_list(length=5000)

        def name_for(row):
            return str(
                row.get("rsl_display_name")
                or row.get("game_id")
                or row.get("global_name")
                or row.get("username")
                or row.get("user_id")
                or "RSL Driver"
            )

        def num(row, key):
            try:
                return int(row.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0

        ranked = sorted(
            drivers,
            key=lambda row: (
                -num(row, "elo"),
                -num(row, "career_wins"),
                name_for(row).casefold(),
            ),
        )
        records = {
            "highest_current_elo": None,
            "most_current_wins": None,
            "longest_current_streak": None,
            "most_season_race_wins": None,
        }
        for key, field in (
            ("highest_current_elo", "elo"),
            ("most_current_wins", "career_wins"),
            ("longest_current_streak", "streak"),
            ("most_season_race_wins", "season_races_won"),
        ):
            if ranked:
                winner = max(ranked, key=lambda row: (num(row, field), -ranked.index(row)))
                records[key] = {
                    "user_id": str(winner.get("user_id", "")),
                    "name": name_for(winner),
                    "value": num(winner, field),
                }

        division_champions = []
        for division_number in range(1, 7):
            members = []
            for row in ranked:
                try:
                    division = get_division_for_pi(num(row, "garage_pi"))
                    division_name = str(division.get("name", ""))
                except Exception:
                    division_name = ""
                if division_name.lower().startswith(f"division {division_number}"):
                    members.append(row)
            if members:
                champion = members[0]
                division_champions.append({
                    "division": division_number,
                    "name": name_for(champion),
                    "user_id": str(champion.get("user_id", "")),
                    "elo": num(champion, "elo"),
                })

        current_season = 0
        if ranked:
            current_season = max(num(row, "season_number") for row in ranked)

        total_matches = await self.bot.db.matches.count_documents({"guild_id": guild_id})
        completed_tournaments = await self.bot.db.tournaments.count_documents({"guild_id": guild_id, "status": {"$in": ["completed", "complete"]}})
        clubs_count = await self.bot.db.clubs.count_documents({"guild_id": guild_id})
        total_races = 0
        async for match in self.bot.db.matches.find({"guild_id": guild_id}, {"races": 1, "races_won": 1}):
            if isinstance(match.get("races"), list):
                total_races += len(match.get("races") or [])
            elif isinstance(match.get("races_won"), dict):
                total_races += sum(int(v or 0) for v in match.get("races_won", {}).values())
        return web.json_response({
            "total_matches": int(total_matches),
            "completed_tournaments": int(completed_tournaments),
            "clubs_count": int(clubs_count),
            "total_races": int(total_races),
            "current_season": current_season,
            "records": records,
            "overall_champion": (
                {"user_id": str(ranked[0].get("user_id", "")), "name": name_for(ranked[0]), "elo": num(ranked[0], "elo")}
                if ranked else None
            ),
            "division_champions": division_champions,
            "driver_count": len(ranked),
        })

    async def competition_snapshot(self, request: web.Request) -> web.Response:
        """Return the signed-in driver's live competitive snapshot for the selected guild."""
        user, guild_id, _ = await self.require_guild_member(request)
        player = await self.players.get_player(guild_id, str(user.user_id))
        if player is None:
            return web.json_response({"registered": False, "guild_id": guild_id})
        elo = int(player.get("elo", 1000) or 1000)
        season = await get_current_season_number(str(guild_id))
        player_season = int(player.get("season_number", 0) or 0)
        season_active = bool(player.get("season_registered")) and player_season == season
        if season_active:
            higher = await self.bot.db.drivers.count_documents({
                "guild_id": str(guild_id),
                "season_registered": True,
                "season_number": season,
                "elo": {"$gt": elo},
            })
            rank = higher + 1
        else:
            rank = None
        played = int(player.get("career_played", 0) or 0)
        wins = int(player.get("career_wins", 0) or 0)
        prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        connection = prefs.get("asphalt_connection") or {}
        return web.json_response({"registered": season_active, "profile_exists": True, "rank": rank, "elo": elo, "garage_pi": int(player.get("garage_pi", 0) or 0), "top_five_car_ranks": [int(x) for x in (player.get("top_five_car_ranks") or [])[:5]], "career_wins": wins, "career_losses": max(0, played - wins), "streak": int(player.get("streak", 0) or 0), "defense_locked": bool(player.get("defense_locked", False)), "season_number": season, "player_season_number": player_season, "asphalt_verified": connection.get("status") == "verified"})

    async def competition_recent_matches(self, request: web.Request) -> web.Response:
        """Return the signed-in driver's recent verified Gauntlet match results."""
        user, guild_id, _ = await self.require_guild_member(request)
        cursor = self.bot.db.matches.find({
            "guild_id": str(guild_id),
            "reverted": {"$ne": True},
            "$or": [{"challenger_id": str(user.user_id)}, {"opponent_id": str(user.user_id)}],
        }).sort("timestamp", -1).limit(8)
        rows = []
        async for match in cursor:
            challenger_id = str(match.get("challenger_id", ""))
            opponent_id = str(match.get("opponent_id", ""))
            opponent = opponent_id if challenger_id == str(user.user_id) else challenger_id
            opponent_profile = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{opponent}"}) or {}
            opponent_name = str(opponent_profile.get("game_id") or opponent_profile.get("username") or opponent)
            won = str(match.get("w_id", "")) == str(user.user_id)
            lost = str(match.get("l_id", "")) == str(user.user_id)
            if not won and not lost:
                continue
            timestamp = match.get("timestamp")
            try:
                date_value = int(timestamp)
            except (TypeError, ValueError):
                try:
                    date_value = int(datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).timestamp())
                except Exception:
                    date_value = int(time.time())
            rows.append({
                "match_id": str(match.get("_id", "")),
                "opponent_id": opponent,
                "opponent": opponent_name,
                "result": "WIN" if won else "LOSS",
                "courses": int(match.get("courses_beat", 0) or 0),
                "date": date_value,
            })
        return web.json_response({"matches": rows})

    async def rsl_records_page(self, request: web.Request) -> web.Response:
        return await self._page_response("rsl-records.html", request)
