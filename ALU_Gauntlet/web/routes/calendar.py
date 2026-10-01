"""RSL web calendar route family."""
from .._web_context import *

class CalendarRoutesMixin:
    async def notification_preferences(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        record = await self.bot.db.notification_preferences.find_one({"_id": str(user.user_id)}) or {}
        return web.json_response({
            "gauntlet_notifications": bool(record.get("gauntlet_notifications", False)),
            "tournament_notifications": bool(record.get("tournament_notifications", False)),
            "gauntlet_lead_days": float(record.get("gauntlet_lead_days", 1) or 1),
            "tournament_lead_days": float(record.get("tournament_lead_days", 1) or 1),
            "event_lead_days": {str(k): float(v) for k, v in (record.get("event_lead_days") or {}).items()},
            "subscribed_event_ids": [str(x) for x in (record.get("subscribed_event_ids") or [])],
            "muted_event_ids": [str(x) for x in (record.get("muted_event_ids") or [])],
            "digest_frequency": str(record.get("digest_frequency", "off") or "off"),
            "digest_hour": int(record.get("digest_hour", 9) or 9),
        })

    async def _reminder_payload(self, user, payload, existing=None):
        """Validate a private calendar reminder and normalize its time to UTC."""
        existing = existing or {}
        title = str(payload.get("title", existing.get("title", ""))).strip()[:120]
        if not title:
            raise web.HTTPBadRequest(text="Reminder title is required.")
        note = str(payload.get("note", existing.get("note", ""))).strip()[:500]
        remind_at = str(payload.get("remind_at", existing.get("local_time", ""))).strip()
        if not remind_at:
            raise web.HTTPBadRequest(text="Reminder date and time are required.")
        try:
            local_dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise web.HTTPBadRequest(text="Reminder date/time must be a valid ISO date and time.") from exc
        guild_id = str(payload.get("guild_id", existing.get("guild_id", ""))).strip()
        guild_prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user.user_id}"}) if guild_id else None
        timezone_name = str(payload.get("timezone", (guild_prefs or {}).get("timezone", "UTC"))).strip()
        if timezone_name not in {value for _, value in TIMEZONE_LABELS}:
            raise web.HTTPBadRequest(text="Invalid reminder timezone.")
        tz = ZoneInfo(timezone_name)
        if local_dt.tzinfo is None:
            local_dt = local_dt.replace(tzinfo=tz)
        else:
            local_dt = local_dt.astimezone(tz)
        timestamp = local_dt.astimezone(timezone.utc).timestamp()
        if timestamp <= time.time() + 5:
            raise web.HTTPBadRequest(text="Reminder time must be in the future.")
        lead_days = payload.get("lead_days", existing.get("lead_days", 0))
        try:
            lead_days = float(lead_days)
        except (TypeError, ValueError) as exc:
            raise web.HTTPBadRequest(text="Reminder lead time must be a number of days.") from exc
        if not 0 <= lead_days <= 365:
            raise web.HTTPBadRequest(text="Reminder lead time must be between 0 and 365 days.")
        return {"user_id": str(user.user_id), "guild_id": guild_id, "title": title, "note": note,
                "local_time": local_dt.isoformat(), "timestamp": timestamp, "timezone": timezone_name,
                "lead_days": lead_days, "enabled": bool(payload.get("enabled", existing.get("enabled", True))),
                "updated_at": time.time()}

    async def list_reminders(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        rows = []
        async for reminder in self.bot.db.custom_reminders.find({"user_id": str(user.user_id)}).sort("timestamp", 1):
            reminder["id"] = str(reminder.pop("_id"))
            rows.append(reminder)
        return web.json_response({"reminders": rows})

    async def create_reminder(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        try:
            payload = await self._json_object(request)
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid JSON body.") from exc
        doc = await self._reminder_payload(user, payload)
        doc["created_at"] = time.time()
        result = await self.bot.db.custom_reminders.insert_one(doc)
        rid = str(result.inserted_id)
        return web.json_response({"ok": True, "message": "Personal reminder created.", "id": rid, "reminder": {**doc, "id": rid}})

    async def update_reminder(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        from bson import ObjectId
        rid = str(request.match_info.get("reminder_id", "")).strip()
        try:
            oid = ObjectId(rid)
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid reminder ID.") from exc
        existing = await self.bot.db.custom_reminders.find_one({"_id": oid, "user_id": str(user.user_id)})
        if not existing:
            raise web.HTTPNotFound(text="Reminder not found.")
        try:
            payload = await self._json_object(request)
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid JSON body.") from exc
        doc = await self._reminder_payload(user, payload, existing)
        await self.bot.db.custom_reminders.update_one({"_id": oid, "user_id": str(user.user_id)}, {"$set": doc})
        return web.json_response({"ok": True, "message": "Personal reminder updated.", "id": rid, "reminder": {**doc, "id": rid}})

    async def delete_reminder(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        from bson import ObjectId
        rid = str(request.match_info.get("reminder_id", "")).strip()
        try:
            oid = ObjectId(rid)
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid reminder ID.") from exc
        deleted = await self.bot.db.custom_reminders.delete_one({"_id": oid, "user_id": str(user.user_id)})
        if not deleted.deleted_count:
            raise web.HTTPNotFound(text="Reminder not found.")
        return web.json_response({"ok": True, "message": "Personal reminder deleted."})

    async def calendar_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("calendar.html", request)

    async def calendar(self, request: web.Request) -> web.Response:
        """Return live Gauntlet season and tournament dates for the calendar UI."""
        user = await self.require_user(request)
        guild_ids = [str(x) for x in user.guild_ids]
        events = []
        seasons = []
        for guild_id in guild_ids:
            guild = self.bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
            guild_name = getattr(guild, "name", guild_id) or guild_id
            state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
            season_number = int(state.get("season_number", 1) or 1)
            start_at = float(state.get("starts_at", 0) or 0)
            end_at = float(state.get("ends_at", 0) or 0)
            if start_at:
                seasons.append({
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "season": season_number,
                    "starts_at": start_at,
                    "ends_at": end_at,
                    "active": bool(state.get("season_active", False)),
                })
                events.append({
                    "id": f"season-start-{guild_id}-{season_number}",
                    "type": "gauntlet",
                    "kind": "start",
                    "title": f"Gauntlet Season {season_number} Starts",
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "start": start_at,
                    "end": start_at,
                    "season": season_number,
                    "status": "active" if state.get("season_active") else "scheduled",
                })
            if end_at:
                events.append({
                    "id": f"season-end-{guild_id}-{season_number}",
                    "type": "gauntlet",
                    "kind": "end",
                    "title": f"Gauntlet Season {season_number} Ends",
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "start": end_at,
                    "end": end_at,
                    "season": season_number,
                    "status": "active" if state.get("season_active") else "scheduled",
                })
            async for item in self.bot.db.tournaments.find({"guild_id": guild_id}).sort("start_time", 1):
                tid = str(item.get("_id"))
                start_raw = item.get("start_time")
                end_raw = item.get("end_time") or item.get("completed_at")
                registration_raw = item.get("registration_deadline")
                def iso_ts(value):
                    if not value:
                        return None
                    try:
                        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
                    except Exception:
                        return None
                start_ts = iso_ts(start_raw)
                end_ts = iso_ts(end_raw)
                reg_ts = iso_ts(registration_raw)
                base = {
                    "id": tid,
                    "type": "tournament",
                    "title": str(item.get("name", "Tournament")),
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "season": None,
                    "status": str(item.get("status", "registration_open")),
                }
                if start_ts:
                    events.append({**base, "kind": "start", "start": start_ts, "end": start_ts})
                if end_ts:
                    events.append({**base, "id": tid + "-end", "kind": "end", "start": end_ts, "end": end_ts})
                if reg_ts:
                    events.append({**base, "id": tid + "-registration", "kind": "registration", "title": str(item.get("name", "Tournament")) + " Registration Closes", "start": reg_ts, "end": reg_ts})
        async for reminder in self.bot.db.custom_reminders.find({"user_id": str(user.user_id), "enabled": True}).sort("timestamp", 1):
            rid = str(reminder.get("_id")); ts = float(reminder.get("timestamp", 0) or 0)
            if ts <= 0: continue
            events.append({"id": f"personal-{rid}", "type": "personal", "kind": "personal",
                           "title": str(reminder.get("title") or "Personal Reminder"),
                           "note": str(reminder.get("note") or ""), "guild_name": "My Reminder",
                           "start": ts, "end": ts, "status": "personal",
                           "lead_days": float(reminder.get("lead_days", 0) or 0),
                           "timezone": str(reminder.get("timezone") or "UTC"), "reminder_id": rid})

        events.sort(key=lambda x: (float(x.get("start") or 0), str(x.get("title", ""))))
        return web.json_response({"events": events, "seasons": seasons, "server_time": time.time()})

    async def notification_inbox(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        rows = await self.bot.db.notification_deliveries.find(
            {"user_id": str(user.user_id)},
            {"_id": 0, "event_id": 1, "lead_days": 1, "created_at": 1, "sent_at": 1, "status": 1},
        ).sort("created_at", -1).limit(100).to_list(length=100)
        return web.json_response({"rows": rows, "guild_id": str(guild_id)})
