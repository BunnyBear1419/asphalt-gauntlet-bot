"""RSL web trust route family."""
from .._web_context import *

class TrustRoutesMixin:
    async def privacy_export(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        uid, gid = str(user.user_id), str(guild_id)
        data = {
            "profile": await self.bot.db.drivers.find_one({"_id": f"{gid}_{uid}"}),
            "web_preferences": await self.bot.db.web_preferences.find_one({"_id": f"{gid}_{uid}"}),
            "notification_preferences": await self.bot.db.notification_preferences.find_one({"_id": uid}),
            "reminders": await self.bot.db.custom_reminders.find({"user_id": uid}).limit(100).to_list(length=100),
            "economy": await self.bot.db.rsl_economy_transactions.find({"guild_id": gid, "user_id": uid}).sort("created_at", -1).limit(200).to_list(length=200),
            "xp_history": await self.bot.db.rsl_xp_events.find({"guild_id": gid, "user_id": uid}).sort("created_at", -1).limit(200).to_list(length=200),
        }
        return web.json_response({"metadata": privacy_export_metadata(uid, gid), "data": redact_document(data)})

    async def privacy_request(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        request_type = str(payload.get("type") or "account_data").strip().lower()
        if request_type not in {"account_data", "delete_account", "disconnect_identity"}:
            raise web.HTTPBadRequest(text="Unsupported privacy request.")
        request_id = await record_system_event(
            self.bot.db, str(guild_id), str(user.user_id), "PRIVACY_REQUEST",
            target_type="user", target_id=str(user.user_id),
            details={"request_type": request_type, "support_channel": "https://discord.gg/q46RQxu2fm"},
        )
        return web.json_response({
            "ok": True, "request_id": request_id,
            "message": "Request recorded. RSL staff will handle privacy/account requests through the official Discord ticket workflow.",
            "support_url": "https://discord.gg/q46RQxu2fm",
        }, status=202)

    async def evidence_timeline(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        uid, gid = str(user.user_id), str(guild_id)
        rows = []
        for collection in ("tournament_media", "match_evidence", "evidence_reviews"):
            try:
                docs = await self.bot.db[collection].find({"guild_id": gid, "user_id": uid}).sort("created_at", -1).limit(100).to_list(length=100)
            except Exception:
                docs = []
            for doc in docs:
                row = redact_document(doc)
                row["source_collection"] = collection
                rows.append(row)
        rows.sort(key=lambda x: float(x.get("created_at", x.get("timestamp", 0)) or 0), reverse=True)
        return web.json_response({"rows": rows[:200], "guild_id": gid})

    async def transparency_snapshot(self, request: web.Request) -> web.Response:
        return web.json_response({
            "competition": {
                "divisions": 6,
                "gauntlet_courses_per_challenge": 5,
                "ticket_cycle": {"free": 5, "paid": 5, "carryover": False},
                "opponent_rotation_hours": 4,
                "scoring": "race wins determine challenge performance",
            },
            "support": {"channel": "discord", "url": "https://discord.gg/q46RQxu2fm"},
            "records": {"corrections_are_audited": True, "history_is_retained": True},
        })
