"""A secure, guild-aware web control center shared with the Discord bot."""
from __future__ import annotations

import hashlib
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
import mimetypes
from typing import Any

from aiohttp import web
import discord

from .auth import DiscordOAuth, SESSION_COOKIE
from .players import PlayerService
from ..core.core import ALU_TRACKS, has_5_course_defense, submit_registration_application, get_current_season_number

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "static"

TIMEZONE_LABELS = (
    ("UTC", "UTC"), ("Eastern Time", "America/New_York"), ("Central Time", "America/Chicago"),
    ("Mountain Time", "America/Denver"), ("Pacific Time", "America/Los_Angeles"),
    ("Alaska Time", "America/Anchorage"), ("Hawaii Time", "Pacific/Honolulu"),
    ("UK / Ireland", "Europe/London"), ("Central Europe", "Europe/Berlin"),
    ("Eastern Europe", "Europe/Bucharest"), ("India", "Asia/Kolkata"),
    ("China / Singapore", "Asia/Shanghai"), ("Japan", "Asia/Tokyo"),
    ("Korea", "Asia/Seoul"), ("Australian Eastern", "Australia/Sydney"),
    ("New Zealand", "Pacific/Auckland"),
)

SETUP_CHANNELS = (
    ("registration_channel_id", "Main / registration channel"),
    ("review_channel_id", "Staff review channel"),
    ("log_channel_id", "Log channel"),
    ("announcement_channel_id", "Announcement channel"),
    ("match_results_channel_id", "Match-results channel"),
)
SETUP_ROLES = (("admin_role_id", "Staff / admin role"), ("player_role_id", "Player role"))


class WebControlCenter:
    """Guild-aware player/staff web UI backed by the same MongoDB as Discord."""

    def __init__(self, bot: Any, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.bot = bot
        self.host = host
        self.port = port
        self.auth = DiscordOAuth(bot)
        self.players = PlayerService(bot)
        self.app = web.Application(middlewares=[self._error_middleware])
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._configure_routes()

    @web.middleware
    async def _error_middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception:
            # Never expose aiohttp's generic "Server got itself in trouble"\n            # page. Log the full traceback server-side and return a controlled\n            # response that identifies the failing route.\n            log.exception("Unhandled web exception on %s %s", request.method, request.path_qs)\n            if request.path.startswith("/api/"):\n                return web.json_response(\n                    {"ok": False, "error": "The Racing Syndicate League web service hit an unexpected error.", "path": request.path},\n                    status=503,\n                )\n            return web.Response(\n                text=(\n                    "Racing Syndicate League web service temporarily unavailable. "\n                    f"Route: {request.path}"\n                ),\n                status=503,\n                content_type="text/plain",\n            )\n\n    async def _page_response(self, filename: str) -> web.Response:\n        path = WEB_DIR / filename\n        try:\n            body = path.read_text(encoding="utf-8")\n        except Exception as exc:\n            log.exception("Unable to read web page %s", path)\n            raise web.HTTPServiceUnavailable(\n                text=f"Web page '{filename}' is temporarily unavailable."\n            ) from exc\n        return web.Response(text=body, content_type="text/html")\n\n    def _configure_routes(self) -> None:\n        self.app.router.add_get("/", self.index)\n        self.app.router.add_get("/players", self.players_page)\n        self.app.router.add_get("/setup", self.setup_page)\n        self.app.router.add_get("/player", self.player_page)\n        self.app.router.add_get("/tournaments", self.tournaments_page)\n        self.app.router.add_get("/clubs", self.clubs_page)\n        self.app.router.add_get("/login", self.login)\n        self.app.router.add_get("/auth/callback", self.callback)\n        self.app.router.add_get("/logout", self.logout)\n        self.app.router.add_get("/healthz", self.healthz)\n        self.app.router.add_get("/api/me", self.me)\n        self.app.router.add_get("/api/status", self.status)\n        self.app.router.add_get("/api/guilds", self.guilds)\n        self.app.router.add_get("/api/player/me", self.player_me)\n        self.app.router.add_get("/api/tournaments", self.tournaments)\n        self.app.router.add_get("/api/tournaments/{tournament_id}", self.tournament_detail)\n        self.app.router.add_get("/api/clubs", self.clubs)\n        self.app.router.add_post("/api/clubs", self.create_club)\n        self.app.router.add_post("/api/clubs/update", self.update_club)\n        self.app.router.add_post("/api/clubs/join", self.join_club)\n        self.app.router.add_post("/api/clubs/member", self.manage_club_member)\n        self.app.router.add_post("/api/tournaments", self.create_tournament)\n        self.app.router.add_post("/api/tournaments/register", self.register_tournament)\n        self.app.router.add_post("/api/tournaments/checkin", self.tournament_checkin)\n        self.app.router.add_post("/api/tournaments/clubs/lineup", self.tournament_club_lineup)\n        self.app.router.add_post("/api/tournaments/result", self.tournament_match_result)\n        self.app.router.add_post("/api/tournaments/result/verify", self.tournament_verify_result)\n        self.app.router.add_post("/api/tournaments/start", self.tournament_start)\n        self.app.router.add_get("/api/player/defense", self.player_defense)\n        self.app.router.add_post("/api/player/defense", self.player_defense_action)\n        self.app.router.add_put("/api/player/preferences", self.player_preferences)\n        self.app.router.add_put("/api/player/profile", self.player_profile)\n        self.app.router.add_put("/api/player/asphalt", self.player_asphalt)\n        self.app.router.add_post("/api/player/register", self.player_register)\n        self.app.router.add_get("/api/setup/options", self.setup_options)\n        self.app.router.add_get("/api/setup/settings", self.setup_settings)\n        self.app.router.add_put("/api/setup/settings", self.save_setup_settings)\n        self.app.router.add_get("/api/season", self.season)\n        self.app.router.add_put("/api/season", self.save_season)\n        self.app.router.add_get("/api/players", self.player_list)\n        self.app.router.add_get("/api/leaderboard", self.leaderboard)\n        self.app.router.add_get("/api/competition/snapshot", self.competition_snapshot)\n        self.app.router.add_get("/api/competition/recent-matches", self.competition_recent_matches)\n        self.app.router.add_get("/api/players/{user_id}", self.player_detail)\n        # Serve every checked-in dashboard image through one predictable route.\n        # The previous allow-list only covered the newer SVGs, so older JPG/WEBP\n        # artwork could exist in the repository but still return a 404 in production.\n        self.app.router.add_get("/assets/{filename}", self.asset)\n        self.app.router.add_static("/static/", WEB_DIR, show_index=False)\n\n    async def clubs_page(self, request: web.Request) -> web.StreamResponse:\n        await self.require_user(request)\n        return await self._page_response("clubs.html")\n\n    async def clubs(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        guild_ids = {str(x) for x in user.guild_ids}\n        rows = []\n        async for club in self.bot.db.clubs.find({"guild_id": {"$in": list(guild_ids)}}).sort("name_ci", 1):\n            club["id"] = str(club.pop("_id"))\n            members = []\n            async for member in self.bot.db.club_members.find({"club_id": club["id"]}).sort("joined_at", 1):\n                member.pop("_id", None)\n                prefs = await self.bot.db.web_preferences.find_one({"_id": f"{club['guild_id']}_{member.get('user_id', '')}"}) or {}\n                connection = prefs.get("asphalt_connection") or {}\n                member["asphalt_verified"] = connection.get("status") == "verified"\n                member["asphalt_game_name"] = connection.get("game_name", "")\n                member["asphalt_game_id"] = connection.get("game_id", "")\n                members.append(member)\n            club["members"] = members\n            club["member_count"] = len(members)\n            club["mine"] = any(str(m.get("user_id")) == str(user.user_id) for m in members)\n            club["leader"] = str(club.get("leader_id")) == str(user.user_id)\n            club["tournament_count"] = await self.bot.db.tournament_club_registrations.count_documents({"club_id": club["id"]})\n            club["tournament_pending_count"] = await self.bot.db.tournament_club_registrations.count_documents({"club_id": club["id"], "status": "pending"})\n            club["tournament_accepted_count"] = await self.bot.db.tournament_club_registrations.count_documents({"club_id": club["id"], "status": {"$in": ["accepted", "checked_in"]}})\n\n            # Build the club's tournament W/L from verified, completed team matches.
            # Byes are intentionally excluded so they do not inflate a club's record.\n            wins = 0\n            losses = 0\n            recent_results = []\n            club_names = {}\n            async for other_club in self.bot.db.clubs.find({"guild_id": club["guild_id"]}, {"name": 1}):\n                club_names[str(other_club.get("_id"))] = str(other_club.get("name") or other_club.get("_id"))\n            async for tournament in self.bot.db.tournaments.find({\n                "guild_id": club["guild_id"],\n                "team_size": {"$gt": 1},\n            }, {"bracket": 1}):\n                bracket = tournament.get("bracket") or {}\n                groups = bracket.get("rounds") or bracket.get("winners") or []\n                for group in groups:\n                    for match in group.get("matches", []):\n                        slots = [str(x) for x in (match.get("player_slots") or []) if x]\n                        if len(slots) != 2 or club["id"] not in slots:\n                            continue\n                        if match.get("status") != "completed" or match.get("result_status") != "verified":\n                            continue\n                        winner = str(match.get("winner_id", ""))\n                        if winner == club["id"]:\n                            wins += 1\n                            result = "WIN"\n                        elif winner in slots:\n                            losses += 1\n                            result = "LOSS"\n                        else:\n                            continue\n                        opponent_id = next((slot for slot in slots if slot != club["id"]), "")\n                        opponent_name = opponent_id\n                        opponent_name = club_names.get(opponent_id, opponent_id)\n                        recent_results.append({\n                            "result": result,\n                            "opponent": opponent_name,\n                            "tournament_name": str(tournament.get("name") or "Team Tournament"),\n                            "date_label": str(match.get("completed_at") or match.get("updated_at") or tournament.get("updated_at") or "")[:10],\n                        })\n            recent_results.sort(key=lambda x: x.get("date_label", ""), reverse=True)\n            club["recent_tournament_results"] = recent_results[:5]\n            club["tournament_wins"] = wins\n            club["tournament_losses"] = losses\n            club["tournament_record"] = f"{wins}-{losses}"\n            rows.append(club)\n        return web.json_response({"clubs": rows})\n\n    async def create_club(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        payload = await request.json()\n        guild_id = str(payload.get("guild_id", "")).strip()\n        if guild_id not in {str(x) for x in user.guild_ids}:\n            raise web.HTTPForbidden(text="You are not a member of that server.")\n        name = str(payload.get("name", "")).strip()\n        if not name or len(name) > 40:\n            raise web.HTTPBadRequest(text="Club name must be 1-40 characters.")\n        if await self.bot.db.clubs.find_one({"guild_id": guild_id, "name_ci": name.casefold()}):\n            raise web.HTTPConflict(text="That club name is already taken.")\n        if await self.bot.db.club_members.find_one({"guild_id": guild_id, "user_id": str(user.user_id)}):\n            raise web.HTTPConflict(text="You are already in a club in this server.")\n        now = datetime.now(timezone.utc).isoformat()\n        discord_link = str(payload.get("discord", "")).strip()\n        if discord_link and not discord_link.lower().startswith(("http://", "https://")):\n            raise web.HTTPBadRequest(text="Discord link must begin with http:// or https://.")\n        raw_links = payload.get("links", [])\n        if not isinstance(raw_links, list):\n            raise web.HTTPBadRequest(text="Club links must be a list.")\n        clean_links = []\n        for link in raw_links[:5]:\n            value = str(link or "").strip()\n            if not value:\n                continue\n            if not value.lower().startswith(("http://", "https://")):\n                raise web.HTTPBadRequest(text="Club links must begin with http:// or https://.")\n            if len(value) > 300:\n                raise web.HTTPBadRequest(text="Club links must be 300 characters or fewer.")\n            clean_links.append(value)\n        doc = {"guild_id": guild_id, "name": name, "name_ci": name.casefold(), "about": str(payload.get("about", payload.get("about_us", ""))).strip()[:500], "discord": discord_link[:300], "links": clean_links, "image": "", "leader_id": str(user.user_id), "member_count": 1, "created_at": now, "updated_at": now}\n        try:\n            result = await self.bot.db.clubs.insert_one(doc)\n        except Exception as exc:\n            if exc.__class__.__name__ == "DuplicateKeyError":\n                raise web.HTTPConflict(text="That club name is already taken.")\n            raise\n        try:\n            await self.bot.db.club_members.insert_one({"club_id": str(result.inserted_id), "guild_id": guild_id, "user_id": str(user.user_id), "username": str(user.global_name or user.username or user.user_id), "role": "leader", "joined_at": now})\n        except Exception:\n            # Compensate if the membership write fails so a club can never be left orphaned.\n            await self.bot.db.clubs.delete_one({"_id": result.inserted_id})\n            raise\n        return web.json_response({"ok": True, "club_id": str(result.inserted_id), "message": "Club created."})\n\n    async def update_club(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        payload = await request.json()\n        from bson import ObjectId\n        try:\n            oid = ObjectId(str(payload.get("club_id", "")))\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid club ID.")\n        club = await self.bot.db.clubs.find_one({"_id": oid})\n        if not club or str(club.get("guild_id")) not in {str(x) for x in user.guild_ids}:\n            raise web.HTTPNotFound(text="Club not found.")\n        if str(club.get("leader_id")) != str(user.user_id):\n            raise web.HTTPForbidden(text="Only the club leader can edit the club.")\n        updates = {}\n        if "name" in payload:\n            name = str(payload.get("name", "")).strip()\n            if not name or len(name) > 40:\n                raise web.HTTPBadRequest(text="Club name must be 1-40 characters.")\n            duplicate = await self.bot.db.clubs.find_one({"_id": {"$ne": oid}, "guild_id": club["guild_id"], "name_ci": name.casefold()})\n            if duplicate:\n                raise web.HTTPConflict(text="That club name is already taken.")\n            updates.update(name=name, name_ci=name.casefold())\n        if "about" in payload or "about_us" in payload:\n            updates["about"] = str(payload.get("about", payload.get("about_us", ""))).strip()[:500]\n        if "discord" in payload:\n            discord_link = str(payload.get("discord", "")).strip()\n            if discord_link and not discord_link.lower().startswith(("http://", "https://")):\n                raise web.HTTPBadRequest(text="Discord link must begin with http:// or https://.")\n            updates["discord"] = discord_link[:300]\n        if "links" in payload:\n            links = payload.get("links", [])\n            if not isinstance(links, list):\n                raise web.HTTPBadRequest(text="Club links must be a list.")\n            clean_links = []\n            for link in links[:5]:\n                value = str(link or "").strip()\n                if not value:\n                    continue\n                if not value.lower().startswith(("http://", "https://")):\n                    raise web.HTTPBadRequest(text="Club links must begin with http:// or https://.")\n                if len(value) > 300:\n                    raise web.HTTPBadRequest(text="Club links must be 300 characters or fewer.")\n                clean_links.append(value)\n            updates["links"] = clean_links\n        if "image" in payload:\n            image = str(payload.get("image", "")).strip()\n            if image and not image.startswith("data:image/"):\n                raise web.HTTPBadRequest(text="Club image must be an uploaded image.")\n            if len(image) > 3_000_000:\n                raise web.HTTPBadRequest(text="Club image is too large.")\n            updates["image"] = image\n        if updates:\n            updates["updated_at"] = datetime.now(timezone.utc).isoformat()\n            await self.bot.db.clubs.update_one({"_id": oid}, {"$set": updates})\n        return web.json_response({"ok": True, "message": "Club profile updated."})\n\n    async def join_club(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        payload = await request.json()\n        from bson import ObjectId\n        try:\n            oid = ObjectId(str(payload.get("club_id", "")))\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid club ID.")\n        club = await self.bot.db.clubs.find_one({"_id": oid})\n        if not club or str(club.get("guild_id")) not in {str(x) for x in user.guild_ids}:\n            raise web.HTTPNotFound(text="Club not found.")\n        member_filter = {"guild_id": club["guild_id"], "user_id": str(user.user_id)}\n        if await self.bot.db.club_members.find_one(member_filter):\n            raise web.HTTPConflict(text="You are already in a club in this server.")\n        # Reserve a membership slot atomically. The unique membership index then\n        # protects the user-level race, while member_count protects the 20-member cap.\n        reservation = await self.bot.db.clubs.update_one(\n            {"_id": oid, "$or": [{"member_count": {"$lt": 20}}, {"member_count": {"$exists": False}}]},\n            {"$inc": {"member_count": 1}},\n        )\n        if not reservation.modified_count:\n            raise web.HTTPConflict(text="That club is full.")\n        now = datetime.now(timezone.utc).isoformat()\n        try:\n            await self.bot.db.club_members.insert_one({"club_id": str(oid), "guild_id": club["guild_id"], "user_id": str(user.user_id), "username": str(user.global_name or user.username or user.user_id), "role": "member", "joined_at": now})\n        except Exception as exc:\n            await self.bot.db.clubs.update_one({"_id": oid, "member_count": {"$gt": 0}}, {"$inc": {"member_count": -1}})\n            if exc.__class__.__name__ == "DuplicateKeyError":\n                raise web.HTTPConflict(text="You are already in a club in this server.")\n            raise\n        return web.json_response({"ok": True, "message": "You joined the club."})\n\n    async def manage_club_member(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        payload = await request.json()\n        from bson import ObjectId\n        try:\n            oid = ObjectId(str(payload.get("club_id", "")))\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid club ID.")\n        club = await self.bot.db.clubs.find_one({"_id": oid})\n        if not club or str(club.get("leader_id")) != str(user.user_id):\n            raise web.HTTPForbidden(text="Only the club leader can manage members.")\n        target = str(payload.get("user_id", "")).strip()\n        if target == str(user.user_id):\n            raise web.HTTPBadRequest(text="The club leader cannot manage their own membership.")\n        member = await self.bot.db.club_members.find_one({"club_id": str(oid), "user_id": target})\n        if not member:\n            raise web.HTTPNotFound(text="Club member not found.")\n        action = str(payload.get("action", "")).casefold()\n        if action == "promote":\n            value = "officer"\n        elif action == "demote":\n            value = "member"\n        elif action == "kick":\n            removed = await self.bot.db.club_members.delete_one({"_id": member["_id"]})\n            if removed.deleted_count:\n                await self.bot.db.clubs.update_one({"_id": oid, "member_count": {"$gt": 0}}, {"$inc": {"member_count": -1}})\n            return web.json_response({"ok": True, "message": "Member removed from the club."})\n        else:\n            raise web.HTTPBadRequest(text="Unsupported member action.")\n        await self.bot.db.club_members.update_one({"_id": member["_id"]}, {"$set": {"role": value}})\n        return web.json_response({"ok": True, "message": "Member role updated."})\n\n    async def tournaments_page(self, request: web.Request) -> web.StreamResponse:\n        await self.require_user(request)\n        return await self._page_response("tournaments.html")\n\n    async def tournaments(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        guild_ids = set(str(x) for x in user.guild_ids)\n        rows = []\n        async for item in self.bot.db.tournaments.find({"guild_id": {"$in": list(guild_ids)}}).sort("start_time", 1):\n            item["id"] = str(item.get("_id"))\n            item.pop("_id", None)\n            if int(item.get("team_size", 1)) > 1:\n                count = await self.bot.db.tournament_club_registrations.count_documents(\n                    {"tournament_id": item["id"], "status": {"$in": ["pending", "accepted", "checked_in"]}}\n                )\n            else:\n                count = await self.bot.db.tournament_registrations.count_documents(\n                    {"tournament_id": item["id"], "status": {"$in": ["pending", "accepted", "checked_in"]}}\n                )\n            item["registration_count"] = count\n            item["format_label"] = {"single_elimination": "Single Elimination", "round_robin": "Round Robin"}.get(\n                item.get("format"), str(item.get("format", "Tournament")).replace("_", " ").title()\n            )\n            item["eligibility_label"] = "Gauntlet registered only" if item.get("gauntlet_only") else "Open to players"\n            if item.get("start_time"):\n                try:\n                    item["start_time_label"] = datetime.fromisoformat(item["start_time"]).astimezone().strftime("%b %d, %Y • %I:%M %p")\n                except Exception:\n                    item["start_time_label"] = "TBD"\n            else:\n                item["start_time_label"] = "TBD"\n            rows.append(item)\n        return web.json_response({"tournaments": rows})\n\n    async def tournament_detail(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        from bson import ObjectId\n        tournament_id = request.match_info.get("tournament_id", "")\n        try:\n            oid = ObjectId(tournament_id)\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid tournament ID.")\n        item = await self.bot.db.tournaments.find_one({"_id": oid})\n        if not item or str(item.get("guild_id")) not in set(str(x) for x in user.guild_ids):\n            raise web.HTTPNotFound(text="Tournament not found.")\n        item["id"] = tournament_id\n        item.pop("_id", None)\n        registrations = []\n        async for row in self.bot.db.tournament_registrations.find(\n            {"tournament_id": tournament_id, "status": {"$in": ["pending", "accepted", "checked_in"]}}\n        ).sort("registered_at", 1):\n            row.pop("_id", None)\n            registrations.append(row)\n        for row in registrations:\n            prefs = await self.bot.db.web_preferences.find_one({"_id": f"{item['guild_id']}_{row.get('user_id', '')}"}) or {}\n            connection = prefs.get("asphalt_connection") or {}\n            row["asphalt_verified"] = connection.get("status") == "verified"\n            row["asphalt_game_name"] = connection.get("game_name", "")\n            row["asphalt_game_id"] = connection.get("game_id", "")\n        item["registrations"] = registrations\n        if int(item.get("team_size", 1)) > 1:\n            clubs = []\n            async for reg in self.bot.db.tournament_club_registrations.find({"tournament_id": tournament_id}).sort("registered_at", 1):\n                club = await self.bot.db.clubs.find_one({"_id": ObjectId(reg["club_id"])})\n                if not club:\n                    continue\n                members = []\n                async for member in self.bot.db.club_members.find({"club_id": reg["club_id"]}).sort("joined_at", 1):\n                    member.pop("_id", None)\n                    prefs = await self.bot.db.web_preferences.find_one({"_id": f"{reg.get('guild_id', item.get('guild_id', ''))}_{member.get('user_id', '')}"}) or {}\n                    connection = prefs.get("asphalt_connection") or {}\n                    member["asphalt_verified"] = connection.get("status") == "verified"\n                    member["asphalt_game_name"] = connection.get("game_name", "")\n                    member["asphalt_game_id"] = connection.get("game_id", "")\n                    members.append(member)\n                clubs.append({"id": reg["club_id"], "name": club.get("name", "Club"), "image": club.get("image", ""), "about": club.get("about", ""), "status": reg.get("status", "pending"), "lineup": reg.get("lineup", []), "members": members, "registered_by": reg.get("registered_by"), "leader_id": club.get("leader_id")})\n            item["clubs"] = clubs\n            item["teams"] = []\n        else:\n            item["clubs"] = []\n            item["teams"] = []\n        return web.json_response(item)\n\n    async def create_tournament(self, request: web.Request) -> web.Response:\n        user, guild_id, _ = await self.require_admin(request)\n        try:\n            payload = await request.json()\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid JSON body.")\n        name = str(payload.get("name", "")).strip()\n        if not name:\n            raise web.HTTPBadRequest(text="Tournament name is required.")\n        max_players = int(payload.get("max_players", 32))\n        if max_players < 2 or max_players > 256:\n            raise web.HTTPBadRequest(text="Maximum players must be between 2 and 256.")\n        fmt = str(payload.get("format", "single_elimination")).strip().casefold()\n        team_size = int(payload.get("team_size", 1))\n        if team_size not in {1, 2, 3, 4}:\n            raise web.HTTPBadRequest(text="Team size must be 1v1, 2v2, 3v3, or 4v4.")\n        if fmt not in {"single_elimination", "double_elimination", "round_robin"}:\n            raise web.HTTPBadRequest(text="Unsupported tournament format.")\n        from ALU_Gauntlet.core.tournament import generate_tournament_bracket\n        bracket = generate_tournament_bracket(fmt, max_players)\n        now = datetime.now(timezone.utc).isoformat()\n        registration_deadline = str(payload.get("registration_deadline", "")).strip() or None\n        start_time = str(payload.get("start_time", "")).strip() or None\n        tournament = {\n            "guild_id": guild_id,\n            "name": name,\n            "description": str(payload.get("description", "")).strip()[:500],\n            "format": fmt,\n            "max_players": max_players,\n            "team_size": team_size,\n            "bracket": bracket,\n            "bracket_version": 1,\n            "gauntlet_only": bool(payload.get("gauntlet_only", False)),\n            "registration_deadline": registration_deadline,\n            "start_time": start_time,\n            "status": "registration_open",\n            "created_by": str(user.user_id),\n            "created_at": now,\n            "updated_at": now,\n        }\n        result = await self.bot.db.tournaments.insert_one(tournament)\n        return web.json_response({"ok": True, "tournament_id": str(result.inserted_id)})\n\n    async def register_tournament(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        try:\n            payload = await request.json()\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid JSON body.")\n        tournament_id = str(payload.get("tournament_id", "")).strip()\n        if not tournament_id:\n            raise web.HTTPBadRequest(text="tournament_id is required.")\n        from bson import ObjectId\n        try:\n            oid = ObjectId(tournament_id)\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid tournament ID.")\n        tournament = await self.bot.db.tournaments.find_one({"_id": oid})\n        if not tournament or str(tournament.get("guild_id")) not in set(str(x) for x in user.guild_ids):\n            raise web.HTTPNotFound(text="Tournament not found.")\n        if tournament.get("status") not in {"registration_open", "open"}:\n            raise web.HTTPConflict(text="Tournament registration is closed.")\n        team_size = int(tournament.get("team_size", 1))\n        if team_size > 1:\n            club_id = str(payload.get("club_id", "")).strip()\n            from bson import ObjectId\n            try:\n                club_oid = ObjectId(club_id)\n            except Exception:\n                raise web.HTTPBadRequest(text="A valid club_id is required for team tournaments.")\n            club = await self.bot.db.clubs.find_one({"_id": club_oid, "guild_id": str(tournament["guild_id"])})\n            if not club:\n                raise web.HTTPNotFound(text="Club not found in this server.")\n            membership = await self.bot.db.club_members.find_one({"club_id": club_id, "user_id": str(user.user_id)})\n            if not membership:\n                raise web.HTTPForbidden(text="You must be a member of the club to register it.")\n            if str(club.get("leader_id")) != str(user.user_id):\n                raise web.HTTPForbidden(text="Only the club leader can enter a club in a tournament.")\n            count = await self.bot.db.tournament_club_registrations.count_documents(\n                {"tournament_id": tournament_id, "status": {"$in": ["pending", "accepted", "checked_in"]}}\n            )\n            if count >= int(tournament.get("max_players", 32)):\n                raise web.HTTPConflict(text="This tournament is full.")\n            existing = await self.bot.db.tournament_club_registrations.find_one(\n                {"tournament_id": tournament_id, "club_id": club_id, "status": {"$in": ["pending", "accepted", "checked_in"]}}\n            )\n            if existing:\n                raise web.HTTPConflict(text="This club is already registered for the tournament.")\n            try:\n                await self.bot.db.tournament_club_registrations.insert_one({\n                    "tournament_id": tournament_id, "guild_id": str(tournament["guild_id"]),\n                    "club_id": club_id, "club_name": club.get("name", "Club"),\n                    "team_size": team_size, "status": "pending",\n                    "registered_by": str(user.user_id),\n                    "registered_at": datetime.now(timezone.utc).isoformat(),\n                })\n            except Exception as exc:\n                if exc.__class__.__name__ == "DuplicateKeyError":\n                    raise web.HTTPConflict(text="This club is already registered for the tournament.")\n                raise\n            return web.json_response({"ok": True, "message": "Club registration submitted for staff review."})\n        count = await self.bot.db.tournament_registrations.count_documents(\n            {"tournament_id": tournament_id, "status": {"$in": ["pending", "accepted"]}}\n        )\n        if count >= int(tournament.get("max_players", 32)):\n            raise web.HTTPConflict(text="This tournament is full.")\n        if tournament.get("gauntlet_only"):\n            profile = await self.bot.db.drivers.find_one({"_id": f'{tournament["guild_id"]}_{user.user_id}'})\n            current_season = await get_current_season_number(str(tournament["guild_id"]))\n            if not profile or not profile.get("season_registered") or int(profile.get("season_number", 0) or 0) != int(current_season):\n                raise web.HTTPForbidden(text="This tournament is limited to drivers registered for the current Gauntlet season.")\n        existing = await self.bot.db.tournament_registrations.find_one(\n            {"tournament_id": tournament_id, "user_id": str(user.user_id), "status": {"$in": ["pending", "accepted"]}}\n        )\n        if existing:\n            raise web.HTTPConflict(text="You are already registered for this tournament.")\n        try:\n            await self.bot.db.tournament_registrations.insert_one({\n                "tournament_id": tournament_id,\n            "guild_id": str(tournament["guild_id"]),\n            "user_id": str(user.user_id),\n            "username": str(user.global_name or user.username or user.user_id),\n            "status": "pending",\n            "registered_at": datetime.now(timezone.utc).isoformat(),\n        })\n        except Exception as exc:\n            if exc.__class__.__name__ == "DuplicateKeyError":\n                raise web.HTTPConflict(text="You are already registered for this tournament.")\n            raise\n        return web.json_response({"ok": True, "message": "Tournament registration submitted for staff review."})\n\n    async def tournament_club_lineup(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        from bson import ObjectId\n        payload = await request.json()\n        tournament_id = str(payload.get("tournament_id", "")).strip()\n        club_id = str(payload.get("club_id", "")).strip()\n        try:\n            ObjectId(tournament_id)\n            ObjectId(club_id)\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid tournament or club ID.")\n        tournament = await self.bot.db.tournaments.find_one({"_id": ObjectId(tournament_id)})\n        club = await self.bot.db.clubs.find_one({"_id": ObjectId(club_id)})\n        if not tournament or not club or str(tournament.get("guild_id")) not in {str(x) for x in user.guild_ids} or str(club.get("guild_id")) != str(tournament.get("guild_id")):\n            raise web.HTTPNotFound(text="Tournament or club not found.")\n        if str(club.get("leader_id")) != str(user.user_id):\n            raise web.HTTPForbidden(text="Only the club leader can set the tournament lineup.")\n        reg = await self.bot.db.tournament_club_registrations.find_one({"tournament_id": tournament_id, "club_id": club_id})\n        if not reg:\n            raise web.HTTPNotFound(text="This club is not registered for the tournament.")\n        size = int(tournament.get("team_size", 1))\n        lineup = [str(x).strip() for x in (payload.get("lineup") or []) if str(x).strip()]\n        if len(lineup) != size or len(set(lineup)) != size:\n            raise web.HTTPBadRequest(text="Select exactly " + str(size) + " unique drivers for the lineup.")\n        member_rows = await self.bot.db.club_members.find({"club_id": club_id}).to_list(length=20)\n        members = {str(x["user_id"]) for x in member_rows}\n        if not set(lineup).issubset(members):\n            raise web.HTTPBadRequest(text="Every lineup driver must be a current club member.")\n        await self.bot.db.tournament_club_registrations.update_one({"_id": reg["_id"]}, {"$set": {"lineup": lineup, "updated_at": datetime.now(timezone.utc).isoformat()}})\n        return web.json_response({"ok": True, "message": str(size) + "v" + str(size) + " tournament lineup saved.", "lineup": lineup})\n\n    async def tournament_match_result(self, request: web.Request) -> web.Response:\n        """Submit a participant result for staff verification."""\n        user = await self.require_user(request)\n        from bson import ObjectId\n        payload = await request.json()\n        try:\n            oid = ObjectId(str(payload.get("tournament_id", "")))\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid tournament ID.")\n        t = await self.bot.db.tournaments.find_one({"_id": oid})\n        if not t or str(t.get("guild_id")) not in set(str(x) for x in user.guild_ids):\n            raise web.HTTPNotFound(text="Tournament not found.")\n        if t.get("status") != "live":\n            raise web.HTTPConflict(text="Tournament is not live.")\n        match_id = str(payload.get("match_id", "")).strip()\n        winner_id = str(payload.get("winner_id", "")).strip()\n        proof_url = str(payload.get("proof_url", "")).strip()\n        notes = str(payload.get("notes", "")).strip()[:500]\n        bracket = t.get("bracket") or {}\n        matches = [m for group in (bracket.get("rounds") or bracket.get("winners") or []) for m in group.get("matches", [])]\n        match = next((m for m in matches if str(m.get("id")) == match_id), None)\n        if not match:\n            raise web.HTTPNotFound(text="Match not found.")\n        slots = [str(x) for x in (match.get("player_slots") or []) if x]\n        if winner_id not in slots:\n            raise web.HTTPBadRequest(text="Winner must be one of the entrants in this match.")\n        team_size = int(t.get("team_size", 1))\n        participant_ok = False\n        if team_size > 1:\n            reg = await self.bot.db.tournament_club_registrations.find_one(\n                {"tournament_id": str(oid), "club_id": {"$in": slots}, "lineup": str(user.user_id), "status": {"$in": ["accepted", "checked_in"]}}\n            )\n            participant_ok = bool(reg)\n        else:\n            participant_ok = str(user.user_id) in slots\n        if not participant_ok and not user.staff:\n            raise web.HTTPForbidden(text="Only a participant in this match can submit its result.")\n        if match.get("result_status") == "pending":\n            raise web.HTTPConflict(text="This match already has a result waiting for staff verification.")\n        if match.get("status") == "completed":\n            raise web.HTTPConflict(text="This match is already completed.")\n        if proof_url and not proof_url.lower().startswith(("http://", "https://")):\n            raise web.HTTPBadRequest(text="Proof must be a valid URL.")\n        if not await self._claim_tournament_action(str(oid), match_id, "submit"):\n            raise web.HTTPConflict(text="Another result submission is already being processed for this match.")\n        try:\n            match.update({"result_status":"pending","submitted_by":str(user.user_id),"submitted_at":datetime.now(timezone.utc).isoformat(),"winner_id":winner_id,"proof_url":proof_url,"result_notes":notes})\n            await self.bot.db.tournaments.update_one({"_id": oid},{"$set":{"bracket":bracket,"updated_at":datetime.now(timezone.utc).isoformat()}})\n        finally:\n            await self._release_tournament_action(str(oid), match_id)\n        cfg = await self.bot.db.settings.find_one({"_id": str(t.get("guild_id"))}) or {}\n        channel_id = cfg.get("match_results_channel_id")\n        channel = self.bot.get_channel(int(channel_id)) if channel_id else None\n        if channel is not None:\n            try:\n                await channel.send("🏁 **Tournament Result Pending Verification**\n**"+str(t.get("name","Tournament"))+"** • "+match_id+"\nWinner: <@"+winner_id+">\nSubmitted by: <@"+str(user.user_id)+">"+(("\nProof: "+proof_url) if proof_url else "")+"\nStaff: use the Tournament Center to verify this result.")\n            except Exception:\n                log.exception("Unable to post tournament result notice")\n        return web.json_response({"ok": True, "message": "Result submitted for staff verification."})\n\n    async def tournament_verify_result(self, request: web.Request) -> web.Response:\n        """Staff verification endpoint that advances a single-elimination bracket atomically."""\n        user, guild_id, _ = await self.require_admin(request)\n        from bson import ObjectId\n        payload = await request.json()\n        try:\n            oid = ObjectId(str(payload.get("tournament_id", "")))\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid tournament ID.")\n        t = await self.bot.db.tournaments.find_one({"_id": oid, "guild_id": guild_id})\n        if not t:\n            raise web.HTTPNotFound(text="Tournament not found.")\n        bracket = t.get("bracket") or {}\n        match_id = str(payload.get("match_id", "")).strip()\n        action = str(payload.get("action", "approve")).strip().casefold()\n        groups = bracket.get("rounds") or bracket.get("winners") or []\n        match = next((m for group in groups for m in group.get("matches", []) if str(m.get("id")) == match_id), None)\n        if not match:\n            raise web.HTTPNotFound(text="Match not found.")\n        if match.get("result_status") != "pending":\n            raise web.HTTPConflict(text="This match does not have a pending result.")\n        if not await self._claim_tournament_action(str(oid), "__bracket__", "verify"):\n            raise web.HTTPConflict(text="Another staff action is already processing this match.")\n        try:\n            if action == "reject":\n                for key in ("result_status", "winner_id", "submitted_by", "submitted_at", "proof_url", "result_notes"):\n                    match.pop(key, None)\n                match["status"] = "ready"\n                message = "Result rejected. The match is ready for another submission."\n            else:\n                winner_id = str(match.get("winner_id", ""))\n                slots = [str(x) for x in (match.get("player_slots") or []) if x]\n                if winner_id not in slots:\n                    raise web.HTTPConflict(text="Pending result has no valid winner.")\n                match["result_status"] = "verified"\n                match["verified_by"] = str(user.user_id)\n                match["verified_at"] = datetime.now(timezone.utc).isoformat()\n                match["status"] = "completed"\n                target = match.get("winner_to")\n                if target:\n                    for group in groups:\n                        for nxt in group.get("matches", []):\n                            if nxt.get("id") == target:\n                                ns = nxt.setdefault("player_slots", [None, None])\n                                if winner_id not in ns:\n                                    ns[0 if ns[0] is None else 1] = winner_id\n                                if all(ns):\n                                    nxt["status"] = "ready"\n                                break\n                elif str(match.get("bracket", "winners")) == "winners" and (match.get("round") or 0) == len(groups):\n                    t["status"] = "completed"\n                    t["champion_id"] = winner_id\n                    t["completed_at"] = datetime.now(timezone.utc).isoformat()\n                message = "Result verified and winner advanced."\n            await self.bot.db.tournaments.update_one(\n                {"_id": oid},\n                {"$set": {\n                    "bracket": bracket,\n                    "status": t.get("status", "live"),\n                    "champion_id": t.get("champion_id"),\n                    "updated_at": datetime.now(timezone.utc).isoformat(),\n                }},\n            )\n        finally:\n            await self._release_tournament_action(str(oid), "__bracket__")\n\n        cfg = await self.bot.db.settings.find_one({"_id": guild_id}) or {}\n        channel_id = cfg.get("match_results_channel_id")\n        channel = self.bot.get_channel(int(channel_id)) if channel_id else None\n        if channel is not None:\n            try:\n                await channel.send(\n                    "🏆 **Tournament Result " + ("Approved" if action != "reject" else "Rejected") +\n                    "** • " + str(t.get("name", "Tournament")) + " • " + match_id\n                )\n            except Exception:\n                log.exception("Unable to post tournament verification notice")\n        return web.json_response({\n            "ok": True,\n            "message": message,\n            "bracket": bracket,\n            "champion_id": t.get("champion_id"),\n        })\n\n    async def tournament_checkin(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        from bson import ObjectId\n        try:\n            oid = ObjectId(str((await request.json()).get("tournament_id", "")))\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid tournament ID.")\n        t = await self.bot.db.tournaments.find_one({"_id": oid})\n        if not t or str(t.get("guild_id")) not in set(str(x) for x in user.guild_ids):\n            raise web.HTTPNotFound(text="Tournament not found.")\n        if t.get("status") not in {"registration_open", "open", "live"}:\n            raise web.HTTPConflict(text="Check-in is closed.")\n        tid = str(oid)\n        if int(t.get("team_size", 1)) > 1:\n            checkin_payload = await request.json()\n            requested_club_id = str(checkin_payload.get("club_id", "")).strip()\n            reg_query = {"tournament_id": tid, "status": {"$in": ["pending", "accepted", "checked_in"]}}\n            if requested_club_id:\n                if not ObjectId.is_valid(requested_club_id):\n                    raise web.HTTPBadRequest(text="Invalid club ID.")\n                reg_query["club_id"] = requested_club_id\n            else:\n                # The frontend can omit club_id; resolve the caller's own club safely.
                owned_clubs = [str(x["_id"]) async for x in self.bot.db.clubs.find({"guild_id": str(t["guild_id"]), "leader_id": str(user.user_id)}, {"_id": 1})]
                if not owned_clubs:
                    raise web.HTTPForbidden(text="Only a club leader can check in a team.")
                reg_query["club_id"] = {"$in": owned_clubs}
            reg = await self.bot.db.tournament_club_registrations.find_one(reg_query)
            if not reg:
                raise web.HTTPConflict(text="Your club must be registered before checking in.")
            club = await self.bot.db.clubs.find_one({"_id": ObjectId(reg["club_id"])}) if ObjectId.is_valid(str(reg["club_id"])) else None
            if not club or str(club.get("leader_id")) != str(user.user_id):
                raise web.HTTPForbidden(text="Only the club leader can check in the club.")
            lineup = reg.get("lineup") or []
            if len(lineup) != int(t.get("team_size", 1)):
                raise web.HTTPConflict(text="Save a complete tournament lineup before checking in.")
            await self.bot.db.tournament_club_registrations.update_one(
                {"_id": reg["_id"]},
                {"$set": {"status": "checked_in", "checked_in_at": datetime.now(timezone.utc).isoformat()}},
            )
        else:
            result = await self.bot.db.tournament_registrations.update_one(
                {"tournament_id": tid, "user_id": str(user.user_id), "status": {"$in": ["pending", "accepted"]}},
                {"$set": {"status": "checked_in", "checked_in_at": datetime.now(timezone.utc).isoformat()}},
            )
            if not result.modified_count:
                raise web.HTTPConflict(text="You must be registered before checking in.")
        return web.json_response({"ok": True, "message": "You are checked in."})

    async def tournament_start(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        from bson import ObjectId
        from ALU_Gauntlet.core.tournament import generate_tournament_bracket
        try:
            oid = ObjectId(str((await request.json()).get("tournament_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid tournament ID.")
        t = await self.bot.db.tournaments.find_one({"_id": oid, "guild_id": guild_id})
        if not t:
            raise web.HTTPNotFound(text="Tournament not found.")
        if t.get("status") not in {"registration_open", "open"}:
            raise web.HTTPConflict(text="Only a tournament still in registration can be started.")
        players = []
        if int(t.get("team_size", 1)) > 1:
            async for row in self.bot.db.tournament_club_registrations.find(
                {"tournament_id": str(oid), "status": {"$in": ["accepted", "checked_in"]}}
            ).sort("registered_at", 1):
                lineup = row.get("lineup") or []
                if len(lineup) != int(t.get("team_size", 1)):
                    raise web.HTTPConflict(text="Every registered club must save a complete tournament lineup before the tournament starts.")
                players.append(str(row["club_id"]))
        else:
            async for row in self.bot.db.tournament_registrations.find(
                {"tournament_id": str(oid), "status": {"$in": ["accepted", "checked_in"]}}
            ).sort("registered_at", 1):
                players.append(str(row["user_id"]))
        if len(players) < 2:
            raise web.HTTPConflict(text="At least 2 accepted entrants are required to start.")
        if t.get("format") in {"single_elimination", "double_elimination"} and len(players) > int(t.get("max_players", 32)):
            raise web.HTTPConflict(text="Too many entrants for this tournament.")
        bracket = generate_tournament_bracket(t["format"], int(t["max_players"]))
        if t["format"] == "single_elimination":
            slots = players + [None] * (int(t["max_players"]) - len(players))
            matches = bracket["rounds"][0]["matches"]
            for i, match in enumerate(matches):
                match["player_slots"] = [slots[i * 2], slots[i * 2 + 1]]
                match["status"] = "ready" if all(match["player_slots"]) else "bye" if any(match["player_slots"]) else "waiting"
            # Resolve byes immediately so a tournament with fewer entrants than
            # the configured bracket size can still advance normally.
            changed = True
            while changed:
                changed = False
                for group in bracket.get("rounds", []):
                    for match in group.get("matches", []):
                        slots_now = [x for x in (match.get("player_slots") or []) if x]
                        if match.get("status") == "bye" and len(slots_now) == 1:
                            winner = str(slots_now[0])
                            match["winner_id"] = winner
                            match["status"] = "completed"
                            match["result_status"] = "verified"
                            target = match.get("winner_to")
                            if target:
                                for next_group in bracket.get("rounds", []):
                                    for nxt in next_group.get("matches", []):
                                        if nxt.get("id") == target:
                                            next_slots = nxt.setdefault("player_slots", [None, None])
                                            if winner not in next_slots:
                                                next_slots[0 if next_slots[0] is None else 1] = winner
                                            if all(next_slots):
                                                nxt["status"] = "ready"
                                            elif any(next_slots):
                                                nxt["status"] = "bye"
                                            changed = True
                                            break
                        elif match.get("status") == "bye" and not slots_now:
                            match["status"] = "waiting"
        started_at = datetime.now(timezone.utc).isoformat()
        transition = await self.bot.db.tournaments.update_one(
            {"_id": oid, "status": {"$in": ["registration_open", "open"]}},
            {"$set": {"status": "live", "started_at": started_at, "bracket": bracket, "started_by": str(user.user_id), "updated_at": started_at}},
        )
        if not transition.modified_count:
            raise web.HTTPConflict(text="Tournament start was already completed by another staff action.")
        return web.json_response({"ok": True, "message": "Tournament started.", "bracket": bracket})

    async def asset(self, request: web.Request) -> web.Response:
        """Serve dashboard artwork with the correct image MIME type."""
        filename = request.match_info.get("filename", "")
        if not filename or "/" in filename or "\\" in filename:
            raise web.HTTPNotFound(text="Asset not found.")
        path = WEB_DIR / "assets" / filename
        if not path.is_file() or path.suffix.lower() not in {".svg", ".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            raise web.HTTPNotFound(text="Asset not found.")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if not content_type.startswith("image/"):
            raise web.HTTPNotFound(text="Asset not found.")
        return web.FileResponse(
            path,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "no-store, max-age=0",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def require_user(self, request: web.Request) -> Any:
        if not self.auth.configured:
            raise web.HTTPServiceUnavailable(text="Web authentication is not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET.")
        user = await self.auth.get_session(request)
        if user is None:
            raise web.HTTPFound("/login")
        return user

    async def require_guild_member(self, request: web.Request) -> tuple[Any, str, Any]:
        user = await self.require_user(request)
        guild_id = request.query.get("guild_id", "").strip()
        if not guild_id:
            raise web.HTTPBadRequest(text="guild_id is required.")
        if guild_id not in user.guild_ids:
            raise web.HTTPForbidden(text="You are not a member of this Discord server.")
        guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == guild_id), None)
        if guild is None:
            raise web.HTTPNotFound(text="The bot is not connected to this Discord server.")
        return user, guild_id, guild

    async def require_admin(self, request: web.Request) -> tuple[Any, str, Any]:
        user, guild_id, guild = await self.require_guild_member(request)

        # Re-check permissions against the live Discord member instead of
        # trusting a cached OAuth session for up to 30 days. This prevents a
        # removed admin role/permission from retaining web staff access.
        if user.user_id in self.auth.allowed_staff_ids:
            return user, guild_id, guild

        member = guild.get_member(int(user.user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user.user_id))
            except Exception:
                member = None

        live_admin = bool(
            member
            and (
                member.guild_permissions.administrator
                or member.guild_permissions.manage_guild
            )
        )
        if not live_admin and member is not None:
            settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
            admin_role_id = str(settings.get("admin_role_id", "")).strip()
            live_admin = bool(
                admin_role_id
                and any(str(role.id) == admin_role_id for role in getattr(member, "roles", []))
            )

        if not live_admin:
            raise web.HTTPForbidden(text="Administrator access is required for this server.")
        return user, guild_id, guild

    async def require_staff(self, request: web.Request) -> Any:
        user = await self.require_user(request)
        if not user.staff:
            raise web.HTTPForbidden(text="Staff access is required.")
        return user

    async def index(self, request: web.Request) -> web.StreamResponse:
        # The homepage is the most important production route. If a stale or
        # malformed web session ever causes an unexpected authentication error,
        # recover to the login page instead of exposing aiohttp's generic 500.\n        try:\n            await self.require_user(request)\n        except web.HTTPException:\n            raise\n        except Exception:\n            log.exception("Unexpected web authentication failure on /")\n            response = web.HTTPFound("/login")\n            response.del_cookie(SESSION_COOKIE, path="/")\n            return response\n        try:\n            return await self._page_response("index.html")\n        except Exception:\n            log.exception("Unable to serve the web dashboard")\n            raise web.HTTPServiceUnavailable(text="The Racing Syndicate League web dashboard is temporarily unavailable.")\n\n    async def players_page(self, request: web.Request) -> web.StreamResponse:\n        await self.require_admin(request)\n        return await self._page_response("players.html")\n\n    async def setup_page(self, request: web.Request) -> web.StreamResponse:\n        await self.require_admin(request)\n        return await self._page_response("setup.html")\n\n    async def player_page(self, request: web.Request) -> web.StreamResponse:\n        await self.require_user(request)\n        return await self._page_response("player.html")\n\n    async def healthz(self, request: web.Request) -> web.Response:\n        ready = bool(getattr(self.bot, "is_ready", lambda: False)())\n        db = getattr(self.bot, "db", None)\n        db_ok = False\n        if db is not None:\n            try:\n                await db.command("ping")\n                db_ok = True\n            except Exception:\n                db_ok = False\n        page_files = {\n            name: (WEB_DIR / name).is_file()\n            for name in ("index.html", "player.html", "players.html", "setup.html", "app.css", "app.js")\n        }\n        web_files_ok = all(page_files.values())\n        return web.json_response({\n            "ok": ready and db_ok and web_files_ok,\n            "bot_ready": ready,\n            "db_ok": db_ok,\n            "web_files_ok": web_files_ok,\n            "web_files": page_files,\n        })\n\n    async def login(self, request: web.Request) -> web.StreamResponse:\n        if not self.auth.configured:\n            return web.Response(status=503, text="Web authentication is not configured.", content_type="text/plain")\n        user = await self.auth.get_session(request)\n        if user:\n            raise web.HTTPFound("/")\n        state = await self.auth.create_state()\n        return web.Response(\n            text=f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign In • Racing Syndicate League</title><link rel="stylesheet" href="/static/app.css?v=20260918-2"></head><body class="alu-dashboard"><main style="min-height:100vh;display:grid;place-items:center;padding:32px"><section class="glass-panel" style="max-width:620px;width:100%;padding:42px;text-align:center"><div class="bottom-logo">RACING <b>SYNDICATE</b> <strong>LEAGUE</strong></div><h1>Sign In to Racing Syndicate League</h1><p class="server-sub">Use your Discord account to access your player profile, registration, matches and staff controls. Your secure web session will be remembered for up to 30 days and refreshed while you use the site.</p><a class="qa qa-purple" href="{self.auth.login_url(state)}">Continue with Discord →</a></section></main></body></html>""",\n            content_type="text/html",\n        )\n\n    async def callback(self, request: web.Request) -> web.StreamResponse:\n        if not self.auth.configured:\n            raise web.HTTPServiceUnavailable(text="Web authentication is not configured.")\n        state = request.query.get("state", "")\n        code = request.query.get("code", "")\n        if not state or not await self.auth.consume_state(state):\n            raise web.HTTPBadRequest(text="Invalid or expired OAuth state.")\n        if not code:\n            raise web.HTTPUnauthorized(text=request.query.get("error", "Authorization was cancelled."))\n        stage = "token exchange"\n        try:\n            tokens = await self.auth.exchange_code(code)\n            if not isinstance(tokens, dict):\n                raise web.HTTPServiceUnavailable(text="Discord returned an invalid OAuth token response.")\n            access_token = tokens.get("access_token")\n            if not access_token:\n                raise web.HTTPServiceUnavailable(text="Discord did not return an access token.")\n            stage = "Discord account lookup"\n            user = await self.auth.build_user(access_token)\n            stage = "web session creation"\n            session = await self.auth.create_session(user)\n        except web.HTTPException:\n            raise\n        except Exception as exc:\n            log.exception("Discord OAuth callback failed during %s", stage)\n            return web.Response(\n                status=503,\n                text=f"Discord sign-in failed during {stage}. {type(exc).__name__}: {exc}",\n                content_type="text/plain",\n                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},\n            )\n        response = web.HTTPFound("/")\n        response.headers["Cache-Control"] = "no-store"\n        response.headers["Pragma"] = "no-cache"\n        self.auth.set_session_cookie(response, session)\n        return response\n\n    async def logout(self, request: web.Request) -> web.StreamResponse:\n        try:\n            await self.auth.destroy_session(request)\n        except Exception:\n            log.exception("Unable to remove web session during logout")\n        response = web.HTTPFound("/login")\n        response.del_cookie(SESSION_COOKIE, path="/")\n        return response\n\n    async def me(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        return web.json_response({"id": user.user_id, "username": user.username, "global_name": user.global_name, "staff": user.staff})\n\n    async def status(self, request: web.Request) -> web.Response:\n        await self.require_user(request)\n        ready = bool(getattr(self.bot, "is_ready", lambda: False)())\n        guilds = list(getattr(self.bot, "guilds", []) or [])\n        latency = getattr(self.bot, "latency", None)\n        return web.json_response({"bot": {"online": ready, "latency_ms": round(latency * 1000, 1) if latency is not None else None, "guild_count": len(guilds)}})\n\n    async def guilds(self, request: web.Request) -> web.Response:\n        user = await self.require_user(request)\n        bot_guilds = {str(getattr(g, "id", "")): g for g in getattr(self.bot, "guilds", [])}\n        allowed = set(user.guild_ids) & set(bot_guilds)\n        result = [{"id": gid, "name": str(getattr(bot_guilds[gid], "name", gid)), "admin": gid in user.admin_guild_ids or user.user_id in self.auth.allowed_staff_ids} for gid in sorted(allowed)]\n        result.sort(key=lambda item: item["name"].casefold())\n        return web.json_response({"guilds": result})\n\n    async def player_me(self, request: web.Request) -> web.Response:\n        user, guild_id, _ = await self.require_guild_member(request)\n        player = await self.players.get_player(guild_id, user.user_id)\n        preferences = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}\n        return web.json_response({\n            "player": player,\n            "user": {"id": user.user_id, "username": user.username, "global_name": user.global_name},\n            "preferences": {key: preferences.get(key) for key in ("timezone", "web_notifications", "dm_notifications", "game_name", "about", "location", "platform", "driver_type", "links", "asphalt_connection")},\n        })\n\n    async def player_defense(self, request: web.Request) -> web.Response:\n        """Return the player's current/pending five-course defense state."""
        user, guild_id, _ = await self.require_guild_member(request)
        profile = await self.players.get_player(guild_id, user.user_id) or {}
        locked = profile.get("defense_locked") or {}
        pending = profile.get("defense_review_payload") or {}
        tracks = profile.get("pending_tracks") or profile.get("season_defense_tracks") or []
        courses = locked.get("courses") or []
        return web.json_response({
            "locked": courses,
            "pending": pending.get("courses") or [],
            "pending_review": bool(profile.get("defense_review_pending")),
            "pending_is_change": bool(profile.get("pending_is_change") or pending.get("is_change")),
            "tracks": tracks,
            "cooldown_remaining": max(0, int(86400 - (time.time() - float(profile.get("last_defense_change", 0))))) if profile.get("last_defense_change") else 0,
        })

    async def player_defense_action(self, request: web.Request) -> web.Response:
        """Generate or stage a five-course defense using the same driver records as Discord."""
        user, guild_id, _ = await self.require_guild_member(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        action = str(payload.get("action", "generate")).strip().casefold()
        driver_id = f"{guild_id}_{user.user_id}"
        profile = await self.bot.db.drivers.find_one({"_id": driver_id})
        if not profile:
            raise web.HTTPConflict(text="Register your driver for the current season before setting a defense.")
        if profile.get("defense_review_pending"):
            raise web.HTTPConflict(text="Your defense submission is already pending staff review.")
        if action == "submit":
            courses_in = payload.get("courses")
            if not isinstance(courses_in, list) or len(courses_in) != 5:
                raise web.HTTPBadRequest(text="Exactly five defense course results are required.")
            pending_tracks = profile.get("pending_tracks") or profile.get("season_defense_tracks") or []
            if len(pending_tracks) != 5:
                raise web.HTTPConflict(text="Generate your five defense courses first.")
            if bool(payload.get("is_change")) != bool(profile.get("pending_is_change")):
                raise web.HTTPBadRequest(text="Defense submission state is out of date. Refresh and try again.")
            from ..core.core import parse_lap_time
            parsed, seen = [], set()
            for i, item in enumerate(courses_in):
                if not isinstance(item, dict):
                    raise web.HTTPBadRequest(text=f"Course {i + 1} is invalid.")
                car = str(item.get("car", "")).strip()
                lap_time = str(item.get("lap_time", "")).strip()
                proof_url = str(item.get("proof_url", "")).strip()
                try:
                    car_rank = int(item.get("car_rank"))
                except (TypeError, ValueError):
                    raise web.HTTPBadRequest(text=f"Course {i + 1}: car performance must be a whole number.")
                ms = parse_lap_time(lap_time)
                if ms <= 0:
                    raise web.HTTPBadRequest(text=f"Course {i + 1}: lap time must use MM:SS.MS format.")
                if not car or car.casefold() in seen:
                    raise web.HTTPBadRequest(text="All five cars are required and must be different.")
                if car_rank <= 0:
                    raise web.HTTPBadRequest(text=f"Course {i + 1}: car performance must be positive.")
                if not proof_url.lower().startswith(("http://", "https://")):
                    raise web.HTTPBadRequest(text=f"Course {i + 1}: proof must be a valid image URL.")
                seen.add(car.casefold())
                parsed.append({"track": str(pending_tracks[i]), "car": car, "car_rank": car_rank, "lap_time": lap_time, "ms": ms, "proof_url": proof_url})
            cfg = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
            channel_id = cfg.get("review_channel_id")
            channel = self.bot.get_channel(int(channel_id)) if channel_id else None
            if channel is None:
                raise web.HTTPServiceUnavailable(text="Staff review channel is not configured.")
            submitted_at = time.time()
            submission_id = hashlib.sha256(f"{guild_id}:{user.user_id}:{submitted_at}".encode()).hexdigest()[:24]
            is_change = bool(profile.get("pending_is_change"))
            payload_doc = {"courses": parsed, "proof_url": parsed[0]["proof_url"], "is_change": is_change, "submitted_at": submitted_at, "submission_id": submission_id}
            claim = await self.bot.db.drivers.update_one({"_id": driver_id, "defense_review_pending": {"$ne": True}}, {"$set": {"defense_review_pending": True, "defense_review_payload": payload_doc}})
            if getattr(claim, "modified_count", 0) != 1:
                raise web.HTTPConflict(text="Your defense submission is already pending staff review.")
            embeds = [discord.Embed(title="🛡️ Gauntlet Defense Change Request" if is_change else "🛡️ New Gauntlet Defense Placement Verification", description="A web submission is awaiting staff verification.", color=3447003)]
            embeds[0].add_field(name="Driver", value=f"<@{user.user_id}>", inline=False)
            embeds[0].set_footer(text=f"ALU Defense Submission: {submission_id}")
            for i, course in enumerate(parsed, 1):
                emb = discord.Embed(title=f"🏁 Course {i}: {course['track']}", description=f"🚗 **Car:** {course['car']}
📈 **Car Performance:** {course['car_rank']}
⏱️ **Lap Time:** {course['lap_time']}", color=3447003)
                emb.set_image(url=course["proof_url"])
                embeds.append(emb)
            try:
                from ..cogs.defense import DefenseView
                review_view = DefenseView(
                    str(user.user_id),
                    str(guild_id),
                    parsed,
                    parsed[0]["proof_url"],
                    is_change=is_change,
                )
                message = await channel.send(embeds=embeds, view=review_view)
            except Exception:
                await self.bot.db.drivers.update_one({"_id": driver_id, "defense_review_payload.submission_id": submission_id}, {"$unset": {"defense_review_pending": "", "defense_review_payload": ""}})
                raise web.HTTPServiceUnavailable(text="Staff review message could not be delivered; your submission was rolled back.")
            await self.bot.db.drivers.update_one({"_id": driver_id, "defense_review_payload.submission_id": submission_id}, {"$set": {"defense_review_payload.review_channel_id": int(channel.id), "defense_review_payload.review_message_id": int(message.id), "defense_review_payload.delivery_status": "delivered"}})
            return web.json_response({"ok": True, "message": "Defense submitted for staff review.", "submission_id": submission_id})

        existing = profile.get("defense_locked") or {}
        if action == "change":
            if not has_5_course_defense(profile):
                raise web.HTTPConflict(text="You do not have a valid five-course defense yet. Create your first defense instead.")
            last_change = profile.get("last_defense_change")
            if last_change and time.time() - float(last_change) < 86400:
                remaining = int(86400 - (time.time() - float(last_change)))
                raise web.HTTPConflict(text=f"Defense changes are on cooldown for another {remaining // 3600}h {(remaining % 3600) // 60}m.")
            tracks = [c.get("track") for c in existing.get("courses", []) if c.get("track")]
            if len(tracks) != 5:
                tracks = profile.get("season_defense_tracks") or []
        else:
            tracks = profile.get("season_defense_tracks") or []
        if len(tracks) != 5:
            tracks = random.sample(ALU_TRACKS, 5)
        await self.bot.db.drivers.update_one(
            {"_id": driver_id},
            {"$set": {"season_defense_tracks": tracks, "pending_tracks": tracks, "pending_is_change": action == "change"}}
        )
        return web.json_response({"ok": True, "action": action, "tracks": tracks, "message": "Five defense courses generated. Enter your results and proof, then submit for staff review."})

    async def player_register(self, request: web.Request) -> web.Response:
        """Submit a web registration through the same canonical Discord workflow."""
        user, guild_id, guild = await self.require_guild_member(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        game_id = str(payload.get("game_id", "")).strip()
        proof_url = str(payload.get("proof_url", "")).strip()
        control_raw = str(payload.get("control", "")).strip().casefold()
        if not game_id or len(game_id) > 100:
            raise web.HTTPBadRequest(text="Game ID is required and must be 100 characters or fewer.")
        try:
            garage_pi = int(payload.get("garage_pi"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Garage PI must be a positive whole number.")
        if garage_pi <= 0:
            raise web.HTTPBadRequest(text="Garage PI must be a positive whole number.")
        if not proof_url.lower().startswith(("http://", "https://")):
            raise web.HTTPBadRequest(text="Proof must be a direct image URL beginning with http:// or https://.")
        if "touch" in control_raw:
            control_value, control_name = "touchdrive", "TouchDrive Auto Pilot"
        elif "manual" in control_raw or "tilt" in control_raw or "tap" in control_raw:
            control_value, control_name = "manual", "Manual Tilt / Tap Controls"
        else:
            raise web.HTTPBadRequest(text="Controls must be TouchDrive or Manual.")

        cfg = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        registration_channel_id = cfg.get("registration_channel_id")
        if not registration_channel_id:
            raise web.HTTPServiceUnavailable(text="Registration is not configured for this server.")

        class _WebUser:
            def __init__(self, user):
                self.id = int(user.user_id)
                self.mention = f"<@{self.id}>"

        class _WebResponse:
            def __init__(self, owner):
                self.owner = owner
                self.done = False
            def is_done(self):
                return self.done
            async def send_message(self, content=None, **kwargs):
                self.done = True
                self.owner.message = str(content or "")

        class _WebFollowup:
            def __init__(self, owner):
                self.owner = owner
            async def send(self, content=None, **kwargs):
                self.owner.message = str(content or "")

        class _WebInteraction:
            def __init__(self):
                self.guild_id = int(guild_id)
                self.channel_id = int(registration_channel_id)
                self.user = _WebUser(user)
                self.message = ""
                self.response = _WebResponse(self)
                self.followup = _WebFollowup(self)

        class _ControlType:
            name = control_name
            value = control_value

        class _Proof:
            content_type = "image/*"
            url = proof_url

        interaction = _WebInteraction()
        await submit_registration_application(interaction, game_id, garage_pi, _Proof(), _ControlType())
        if interaction.message.startswith(("❌", "⚠️", "⏳")):
            if interaction.message.startswith("⏳"):
                raise web.HTTPConflict(text=interaction.message)
            if interaction.message.startswith("⚠️"):
                raise web.HTTPConflict(text=interaction.message)
            raise web.HTTPBadRequest(text=interaction.message)
        return web.json_response({"ok": True, "message": interaction.message})

    async def player_profile(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        game_name = str(payload.get("game_name", "")).strip()[:100]
        about = str(payload.get("about", "")).strip()[:500]
        location = str(payload.get("location", "")).strip()[:100]
        platform = str(payload.get("platform", "")).strip()[:40]
        driver_type = str(payload.get("driver_type", "")).strip()[:30]
        allowed_platforms = {"Android", "Nintendo", "macOS", "Steam", "Epic Games", "Windows", "Apple iOS", "Xbox", "Playstation"}
        allowed_driver_types = {"Manual Driver", "Touch Driver"}
        if platform and platform not in allowed_platforms:
            raise web.HTTPBadRequest(text="Invalid platform.")
        if driver_type and driver_type not in allowed_driver_types:
            raise web.HTTPBadRequest(text="Invalid driver type.")
        timezone = str(payload.get("timezone", "UTC")).strip()
        if timezone not in {value for _, value in TIMEZONE_LABELS}:
            raise web.HTTPBadRequest(text="Invalid timezone.")
        links = payload.get("links", [])
        if not isinstance(links, list):
            raise web.HTTPBadRequest(text="Links must be a list.")
        clean_links = []
        for link in links[:5]:
            value = str(link or "").strip()
            if not value:
                continue
            if not value.lower().startswith(("http://", "https://")):
                raise web.HTTPBadRequest(text="Profile links must begin with http:// or https://.")
            if len(value) > 300:
                raise web.HTTPBadRequest(text="Profile links must be 300 characters or fewer.")
            clean_links.append(value)
        preference_id = f"{guild_id}_{user.user_id}"
        await self.bot.db.web_preferences.update_one(
            {"_id": preference_id},
            {"$set": {"guild_id": guild_id, "user_id": user.user_id, "game_name": game_name, "about": about, "location": location, "platform": platform, "driver_type": driver_type, "timezone": timezone, "links": clean_links}},
            upsert=True,
        )
        await self.bot.db.drivers.update_one(
            {"_id": preference_id},
            {"$set": {"game_name": game_name, "updated_at": time.time()}},
        )
        return web.json_response({"ok": True, "message": "Profile updated.", "profile": {"discord_name": user.global_name or user.username or "Driver", "game_name": game_name, "game_id": (await self.players.get_player(guild_id, user.user_id) or {}).get("game_id", ""), "about": about, "location": location, "timezone": timezone, "links": clean_links}})

    async def player_asphalt(self, request: web.Request) -> web.Response:
        """Link a player's Asphalt Legends identity to their Discord/web account."""\n        user, guild_id, _ = await self.require_guild_member(request)\n        try:\n            payload = await request.json()\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid JSON body.")\n        game_id = str(payload.get("game_id", "")).strip()[:100]\n        game_name = str(payload.get("game_name", "")).strip()[:100]\n        if not game_id or not game_name:\n            raise web.HTTPBadRequest(text="Asphalt Game Name and Game ID are required.")\n        existing = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}\n        connection = existing.get("asphalt_connection") or {}\n        if connection.get("status") == "verified" and connection.get("game_id") != game_id:\n            raise web.HTTPConflict(text="Your Asphalt account is already verified. Ask staff to change the linked account.")\n        duplicate = await self.bot.db.web_preferences.find_one({"guild_id": guild_id, "asphalt_connection.game_id": game_id, "_id": {"$ne": f"{guild_id}_{user.user_id}"}})\n        if duplicate and (duplicate.get("asphalt_connection") or {}).get("status") == "verified":\n            raise web.HTTPConflict(text="That Asphalt Game ID is already linked to another Discord account.")\n        now = datetime.now(timezone.utc).isoformat()\n        connection = {"game_id": game_id, "game_name": game_name, "status": "pending", "submitted_at": connection.get("submitted_at") or now, "updated_at": now, "verified_at": connection.get("verified_at"), "verified_by": connection.get("verified_by")}\n        key = f"{guild_id}_{user.user_id}"\n        previous_prefs = existing\n        try:\n            await self.bot.db.web_preferences.update_one({"_id": key}, {"$set": {"guild_id": guild_id, "user_id": user.user_id, "asphalt_connection": connection}}, upsert=True)\n            await self.bot.db.drivers.update_one({"_id": key}, {"$set": {\n                "guild_id": guild_id,\n                "user_id": user.user_id,\n                "asphalt_verified": False,\n                "asphalt_game_id": None,\n                "asphalt_game_name": None,\n                "asphalt_verified_by": None,\n                "asphalt_verified_at": None,\n            }}, upsert=True)\n        except Exception:\n            try:\n                if previous_prefs:\n                    await self.bot.db.web_preferences.replace_one({"_id": key}, previous_prefs, upsert=True)\n                else:\n                    await self.bot.db.web_preferences.delete_one({"_id": key})\n            except Exception:\n                log.exception("Failed to compensate partial Asphalt submission for %s", key)\n            raise\n        cfg = await self.bot.db.settings.find_one({"_id": guild_id}) or {}\n        channel = self.bot.get_channel(int(cfg["review_channel_id"])) if cfg.get("review_channel_id") else None\n        if channel:\n            await channel.send(f"🏎️ Asphalt Account Link Pending Verification\nDiscord: <@{user.user_id}>\nGame Name: **{game_name}**\nGame ID: **{game_id}**\n\nStaff can verify with /asphalt verify.")\n        return web.json_response({"ok": True, "message": "Asphalt account submitted for staff verification.", "connection": connection})\n\n    async def player_preferences(self, request: web.Request) -> web.Response:\n        user, guild_id, _ = await self.require_guild_member(request)\n        try:\n            payload = await request.json()\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid JSON body.")\n        allowed = {"web_notifications", "dm_notifications", "timezone"}\n        updates = {key: payload[key] for key in allowed if key in payload}\n        if "web_notifications" in updates:\n            updates["web_notifications"] = bool(updates["web_notifications"])\n        if "dm_notifications" in updates:\n            updates["dm_notifications"] = bool(updates["dm_notifications"])\n        if "timezone" in updates and updates["timezone"] not in {value for _, value in TIMEZONE_LABELS}:\n            raise web.HTTPBadRequest(text="Invalid timezone.")\n        if updates:\n            await self.bot.db.web_preferences.update_one({"_id": f"{guild_id}_{user.user_id}"}, {"$set": {**updates, "guild_id": guild_id, "user_id": user.user_id}}, upsert=True)\n        return web.json_response({"ok": True, "preferences": updates})\n\n    async def setup_options(self, request: web.Request) -> web.Response:\n        _, _, guild = await self.require_admin(request)\n        channels = [{"id": str(c.id), "name": c.name, "type": str(getattr(c, "type", "text"))} for c in guild.text_channels]\n        roles = [{"id": str(role.id), "name": role.name} for role in guild.roles if not role.is_default() and not role.managed]\n        return web.json_response({"channels": channels, "roles": roles, "timezones": [{"label": label, "value": value} for label, value in TIMEZONE_LABELS]})\n\n    async def setup_settings(self, request: web.Request) -> web.Response:\n        _, guild_id, _ = await self.require_admin(request)\n        settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}\n        return web.json_response({"settings": {key: settings.get(key) for key, _ in SETUP_CHANNELS + SETUP_ROLES} | {"timezone": settings.get("timezone", "UTC")}})\n\n    async def save_setup_settings(self, request: web.Request) -> web.Response:\n        user, guild_id, _ = await self.require_admin(request)\n        try:\n            payload = await request.json()\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid JSON body.")\n        allowed = {key for key, _ in SETUP_CHANNELS + SETUP_ROLES} | {"timezone"}\n        clean = {key: str(payload[key]).strip() for key in allowed if payload.get(key)}\n        if clean.get("timezone") not in {None, *(value for _, value in TIMEZONE_LABELS)}:\n            raise web.HTTPBadRequest(text="Invalid timezone.")\n        if not clean:\n            raise web.HTTPBadRequest(text="Nothing to save.")\n        guild = next(g for g in self.bot.guilds if str(g.id) == guild_id)\n        for key in SETUP_CHANNELS:\n            value = clean.get(key[0])\n            if value:\n                try:\n                    valid = guild.get_channel(int(value))\n                except (TypeError, ValueError):\n                    valid = None\n                if valid is None:\n                    raise web.HTTPBadRequest(text=f"Invalid channel for {key[1]}.")\n        for key in SETUP_ROLES:\n            value = clean.get(key[0])\n            if value:\n                try:\n                    valid = guild.get_role(int(value))\n                except (TypeError, ValueError):\n                    valid = None\n                if valid is None:\n                    raise web.HTTPBadRequest(text=f"Invalid role for {key[1]}.")\n        await self.bot.db.settings.update_one({"_id": guild_id}, {"$set": clean}, upsert=True)\n        await self._audit(guild_id, user.user_id, "Web setup updated")\n        return web.json_response({"ok": True, "settings": clean})\n\n    async def season(self, request: web.Request) -> web.Response:\n        _, guild_id, _ = await self.require_guild_member(request)\n        state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}\n        return web.json_response({"season": state})\n\n    async def save_season(self, request: web.Request) -> web.Response:\n        user, guild_id, _ = await self.require_admin(request)\n        try:\n            payload = await request.json()\n        except Exception:\n            raise web.HTTPBadRequest(text="Invalid JSON body.")\n        if "automatic_season_end" in payload:\n            value = bool(payload["automatic_season_end"])\n            await self.bot.db.settings.update_one({"_id": guild_id}, {"$set": {"automatic_season_end": value}}, upsert=True)\n            await self._audit(guild_id, user.user_id, f"Web season automation {'enabled' if value else 'disabled'}")\n        return web.json_response({"ok": True})\n\n    async def _audit(self, guild_id: str, user_id: str, action: str) -> None:\n        await self.bot.db.system_events.insert_one({"guild_id": guild_id, "source": "web", "user_id": user_id, "action": action})\n\n    async def leaderboard(self, request: web.Request) -> web.Response:\n        _, guild_id, _ = await self.require_guild_member(request)\n        try:\n            limit = max(1, min(100, int(request.query.get("limit", "50"))))\n        except ValueError:\n            raise web.HTTPBadRequest(text="limit must be an integer.")\n        rows = await self.players.list_players(guild_id, limit=limit)\n        for player in rows:\n            uid = str(player.get("user_id", ""))\n            prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{uid}"}) or {}\n            connection = prefs.get("asphalt_connection") or {}\n            player["game_name"] = prefs.get("game_name", "") or connection.get("game_name", "")\n            player["asphalt_verified"] = connection.get("status") == "verified"\n        return web.json_response({"players": rows})\n\n    async def competition_snapshot(self, request: web.Request) -> web.Response:\n        """Return the signed-in driver's live competitive snapshot for the selected guild."""
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
        return web.json_response({"registered": season_active, "profile_exists": True, "rank": rank, "elo": elo, "garage_pi": int(player.get("garage_pi", 0) or 0), "career_wins": wins, "career_losses": max(0, played - wins), "streak": int(player.get("streak", 0) or 0), "defense_locked": bool(player.get("defense_locked", False)), "season_number": season, "player_season_number": player_season, "asphalt_verified": connection.get("status") == "verified"})

    async def competition_recent_matches(self, request: web.Request) -> web.Response:
        """Return the signed-in driver's recent verified Gauntlet match results."""\n        user, guild_id, _ = await self.require_guild_member(request)\n        cursor = self.bot.db.matches.find({\n            "guild_id": str(guild_id),\n            "reverted": {"$ne": True},\n            "$or": [{"challenger_id": str(user.user_id)}, {"opponent_id": str(user.user_id)}],\n        }).sort("timestamp", -1).limit(8)\n        rows = []\n        async for match in cursor:\n            challenger_id = str(match.get("challenger_id", ""))\n            opponent_id = str(match.get("opponent_id", ""))\n            opponent = opponent_id if challenger_id == str(user.user_id) else challenger_id\n            opponent_profile = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{opponent}"}) or {}\n            opponent_name = str(opponent_profile.get("game_id") or opponent_profile.get("username") or opponent)\n            won = str(match.get("w_id", "")) == str(user.user_id)\n            lost = str(match.get("l_id", "")) == str(user.user_id)\n            if not won and not lost:\n                continue\n            timestamp = match.get("timestamp")\n            try:\n                date_value = int(timestamp)\n            except (TypeError, ValueError):\n                try:\n                    date_value = int(datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).timestamp())\n                except Exception:\n                    date_value = int(time.time())\n            rows.append({\n                "match_id": str(match.get("_id", "")),\n                "opponent_id": opponent,\n                "opponent": opponent_name,\n                "result": "WIN" if won else "LOSS",\n                "courses": int(match.get("courses_beat", 0) or 0),\n                "date": date_value,\n            })\n        return web.json_response({"matches": rows})\n\n    async def player_list(self, request: web.Request) -> web.Response:\n        _, guild_id, _ = await self.require_admin(request)\n        try:\n            limit = max(1, min(100, int(request.query.get("limit", "50"))))\n        except ValueError:\n            raise web.HTTPBadRequest(text="limit must be an integer.")\n        players = await self.players.list_players(guild_id, search=request.query.get("search", ""), limit=limit)\n        for player in players:\n            uid = str(player.get("user_id", ""))\n            prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{uid}"}) or {}\n            connection = prefs.get("asphalt_connection") or {}\n            player["asphalt_connection"] = {\n                "game_id": connection.get("game_id", ""),\n                "game_name": connection.get("game_name", ""),\n                "status": connection.get("status", "not_linked"),\n            }\n            player["asphalt_verified"] = connection.get("status") == "verified"\n        return web.json_response({"players": players})\n\n    async def player_detail(self, request: web.Request) -> web.Response:\n        """Return a guild member's public profile for the player directory."""
        _, guild_id, _ = await self.require_guild_member(request)
        player = await self.players.get_player(guild_id, request.match_info["user_id"])
        if player is None:
            raise web.HTTPNotFound(text="Player not found.")
        prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{request.match_info['user_id']}"}) or {}
        connection = prefs.get("asphalt_connection") or {}
        timezone_value = prefs.get("timezone", "UTC")
        timezone_label = next((label for label, value in TIMEZONE_LABELS if value == timezone_value), timezone_value)
        player.update({
            "discord_name": player.get("username") or player.get("global_name") or "Driver",
            "game_name": prefs.get("game_name", ""),
            "about": prefs.get("about", ""),
            "location": prefs.get("location", ""),
            "platform": prefs.get("platform", ""),
            "driver_type": prefs.get("driver_type", ""),
            "timezone": timezone_value,
            "timezone_label": timezone_label,
            "links": (prefs.get("links") or [])[:5],
            "asphalt_connection": {"game_id": connection.get("game_id", ""), "game_name": connection.get("game_name", ""), "status": connection.get("status", "not_linked")},
            "asphalt_verified": connection.get("status") == "verified",
        })
        return web.json_response({"player": player})

    async def _claim_tournament_action(self, tournament_id: str, match_id: str, action: str) -> bool:
        """Acquire a short-lived atomic lock so one match cannot be processed twice concurrently."""
        now = datetime.now(timezone.utc)
        expires = now.timestamp() + 60
        doc = {
            "tournament_id": str(tournament_id),
            "match_id": str(match_id),
            "action": str(action),
            "claimed_at": now,
            "expires_at": datetime.fromtimestamp(expires, tz=timezone.utc),
        }
        try:
            await self.bot.db.tournament_action_locks.insert_one(doc)
            return True
        except Exception as exc:
            if exc.__class__.__name__ != "DuplicateKeyError":
                raise
            # Recover a stale lock atomically. A live lock always wins.
            replaced = await self.bot.db.tournament_action_locks.find_one_and_replace(
                {
                    "tournament_id": str(tournament_id),
                    "match_id": str(match_id),
                    "expires_at": {"$lt": now},
                },
                doc,
            )
            return replaced is not None

    async def _release_tournament_action(self, tournament_id: str, match_id: str) -> None:
        await self.bot.db.tournament_action_locks.delete_one(
            {"tournament_id": str(tournament_id), "match_id": str(match_id)}
        )

    async def _ensure_integrity_indexes(self) -> None:
        """Create production integrity indexes and fail startup if they cannot be enforced."""
        # Backfill the normalized club-name field before creating its unique index.
        # Legacy clubs may predate name_ci; missing data is repaired, but true
        # duplicate names are intentionally left for the unique index to reject.
        async for club in self.bot.db.clubs.find({}, {"_id": 1, "name": 1, "name_ci": 1}):
            name = str(club.get("name") or "").strip()
            if not name:
                raise RuntimeError(f"Club {club.get('_id')} has no valid name; database repair is required")
            normalized = name.casefold()
            if club.get("name_ci") != normalized:
                await self.bot.db.clubs.update_one(
                    {"_id": club["_id"]},
                    {"$set": {"name_ci": normalized}},
                )

        indexes = (
            (self.bot.db.club_members, [("guild_id", 1), ("user_id", 1)], "uniq_club_member_per_guild", True),
            (self.bot.db.clubs, [("guild_id", 1), ("name_ci", 1)], "uniq_club_name_per_guild", True),
            (self.bot.db.tournament_registrations, [("tournament_id", 1), ("user_id", 1)], "uniq_tournament_player", True),
            (self.bot.db.tournament_club_registrations, [("tournament_id", 1), ("club_id", 1)], "uniq_tournament_club", True),
            (self.bot.db.tournament_action_locks, [("tournament_id", 1), ("match_id", 1)], "uniq_tournament_action_lock", True),
            (self.bot.db.tournament_action_locks, [("expires_at", 1)], "ttl_tournament_action_lock", False),
            (self.bot.db.web_preferences, [("guild_id", 1), ("asphalt_connection.game_id", 1)], "uniq_verified_asphalt_game_id_per_guild", True),
        )
        for collection, keys, name, unique in indexes:
            try:
                kwargs = {"name": name}
                if unique:
                    kwargs["unique"] = True
                if name == "ttl_tournament_action_lock":
                    kwargs["expireAfterSeconds"] = 0
                if name == "uniq_verified_asphalt_game_id_per_guild":
                    kwargs["partialFilterExpression"] = {"asphalt_connection.status": "verified", "asphalt_connection.game_id": {"$type": "string"}}
                await collection.create_index(keys, **kwargs)
            except Exception as exc:
                # A duplicate-key error means existing bad data prevents the invariant.
                # Do not start a production server that silently lacks its safety rails.
                log.exception("Unable to enforce integrity index %s", name)
                raise RuntimeError(f"Database integrity index {name} could not be enforced") from exc

        # Repair the cached club member counters once at startup so legacy clubs cannot
        # bypass the atomic 20-member reservation because member_count was never stored.
        async for club in self.bot.db.clubs.find({}, {"_id": 1}):
            club_id = str(club["_id"])
            count = await self.bot.db.club_members.count_documents({"club_id": club_id})
            await self.bot.db.clubs.update_one({"_id": club["_id"]}, {"$set": {"member_count": count}})

    async def start(self) -> None:
        await self._ensure_integrity_indexes()
        if self.runner is not None:
            return
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        log.info("Gauntlet web control center listening on http://%s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self.runner is None:
            return
        await self.runner.cleanup()
        self.runner = None
        self.site = None
