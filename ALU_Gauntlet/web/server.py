"""A secure, guild-aware web control center shared with the Discord bot."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from .auth import DiscordOAuth, SESSION_COOKIE
from .players import PlayerService

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
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._configure_routes()

    def _configure_routes(self) -> None:
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/players", self.players_page)
        self.app.router.add_get("/setup", self.setup_page)
        self.app.router.add_get("/player", self.player_page)
        self.app.router.add_get("/login", self.login)
        self.app.router.add_get("/auth/callback", self.callback)
        self.app.router.add_get("/logout", self.logout)
        self.app.router.add_get("/healthz", self.healthz)
        self.app.router.add_get("/api/me", self.me)
        self.app.router.add_get("/api/status", self.status)
        self.app.router.add_get("/api/guilds", self.guilds)
        self.app.router.add_get("/api/player/me", self.player_me)
        self.app.router.add_put("/api/player/preferences", self.player_preferences)
        self.app.router.add_get("/api/setup/options", self.setup_options)
        self.app.router.add_get("/api/setup/settings", self.setup_settings)
        self.app.router.add_put("/api/setup/settings", self.save_setup_settings)
        self.app.router.add_get("/api/season", self.season)
        self.app.router.add_put("/api/season", self.save_season)
        self.app.router.add_get("/api/players", self.player_list)
        self.app.router.add_get("/api/players/{user_id}", self.player_detail)
        self.app.router.add_static("/static/", WEB_DIR, show_index=False)

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
        if guild_id not in user.admin_guild_ids and user.user_id not in self.auth.allowed_staff_ids:
            raise web.HTTPForbidden(text="Administrator access is required for this server.")
        return user, guild_id, guild

    async def require_staff(self, request: web.Request) -> Any:
        user = await self.require_user(request)
        if not user.staff:
            raise web.HTTPForbidden(text="Staff access is required.")
        return user

    async def index(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return web.FileResponse(WEB_DIR / "index.html")

    async def players_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_admin(request)
        return web.FileResponse(WEB_DIR / "players.html")

    async def setup_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_admin(request)
        return web.FileResponse(WEB_DIR / "setup.html")

    async def player_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return web.FileResponse(WEB_DIR / "player.html")

    async def healthz(self, request: web.Request) -> web.Response:
        ready = bool(getattr(self.bot, "is_ready", lambda: False)())
        db = getattr(self.bot, "db", None)
        db_ok = False
        if db is not None:
            try:
                await db.command("ping")
                db_ok = True
            except Exception:
                db_ok = False
        return web.json_response({"ok": ready and db_ok, "bot_ready": ready, "db_ok": db_ok})

    async def login(self, request: web.Request) -> web.StreamResponse:
        if not self.auth.configured:
            return web.Response(status=503, text="Web authentication is not configured.", content_type="text/plain")
        user = await self.auth.get_session(request)
        if user:
            raise web.HTTPFound("/")
        state = await self.auth.create_state()
        raise web.HTTPFound(self.auth.login_url(state))

    async def callback(self, request: web.Request) -> web.StreamResponse:
        if not self.auth.configured:
            raise web.HTTPServiceUnavailable(text="Web authentication is not configured.")
        state = request.query.get("state", "")
        code = request.query.get("code", "")
        if not state or not await self.auth.consume_state(state):
            raise web.HTTPBadRequest(text="Invalid or expired OAuth state.")
        if not code:
            raise web.HTTPUnauthorized(text=request.query.get("error", "Authorization was cancelled."))
        tokens = await self.auth.exchange_code(code)
        access_token = tokens.get("access_token")
        if not access_token:
            raise web.HTTPBadGateway(text="Discord did not return an access token.")
        user = await self.auth.build_user(access_token)
        session = await self.auth.create_session(user)
        response = web.HTTPFound("/")
        self.auth.set_session_cookie(response, session)
        return response

    async def logout(self, request: web.Request) -> web.StreamResponse:
        await self.auth.destroy_session(request)
        response = web.HTTPFound("/login")
        response.del_cookie(SESSION_COOKIE, path="/")
        return response

    async def me(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        return web.json_response({"id": user.user_id, "username": user.username, "global_name": user.global_name, "staff": user.staff})

    async def status(self, request: web.Request) -> web.Response:
        await self.require_user(request)
        ready = bool(getattr(self.bot, "is_ready", lambda: False)())
        guilds = list(getattr(self.bot, "guilds", []) or [])
        latency = getattr(self.bot, "latency", None)
        return web.json_response({"bot": {"online": ready, "latency_ms": round(latency * 1000, 1) if latency is not None else None, "guild_count": len(guilds)}})

    async def guilds(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        bot_guilds = {str(getattr(g, "id", "")): g for g in getattr(self.bot, "guilds", [])}
        allowed = set(user.guild_ids) & set(bot_guilds)
        result = [{"id": gid, "name": str(getattr(bot_guilds[gid], "name", gid)), "admin": gid in user.admin_guild_ids or user.user_id in self.auth.allowed_staff_ids} for gid in sorted(allowed)]
        result.sort(key=lambda item: item["name"].casefold())
        return web.json_response({"guilds": result})

    async def player_me(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        player = await self.players.get_player(guild_id, user.user_id)
        return web.json_response({"player": player, "user": {"id": user.user_id, "username": user.username, "global_name": user.global_name}})

    async def player_preferences(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        allowed = {"web_notifications", "dm_notifications", "timezone"}
        updates = {key: payload[key] for key in allowed if key in payload}
        if "web_notifications" in updates:
            updates["web_notifications"] = bool(updates["web_notifications"])
        if "dm_notifications" in updates:
            updates["dm_notifications"] = bool(updates["dm_notifications"])
        if "timezone" in updates and updates["timezone"] not in {value for _, value in TIMEZONE_LABELS}:
            raise web.HTTPBadRequest(text="Invalid timezone.")
        if updates:
            await self.bot.db.web_preferences.update_one({"_id": f"{guild_id}_{user.user_id}"}, {"$set": {**updates, "guild_id": guild_id, "user_id": user.user_id}}, upsert=True)
        return web.json_response({"ok": True, "preferences": updates})

    async def setup_options(self, request: web.Request) -> web.Response:
        _, _, guild = await self.require_admin(request)
        channels = [{"id": str(c.id), "name": c.name, "type": str(getattr(c, "type", "text"))} for c in guild.text_channels]
        roles = [{"id": str(role.id), "name": role.name} for role in guild.roles if not role.is_default() and not role.managed]
        return web.json_response({"channels": channels, "roles": roles, "timezones": [{"label": label, "value": value} for label, value in TIMEZONE_LABELS]})

    async def setup_settings(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        return web.json_response({"settings": {key: settings.get(key) for key, _ in SETUP_CHANNELS + SETUP_ROLES} | {"timezone": settings.get("timezone", "UTC")}})

    async def save_setup_settings(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        allowed = {key for key, _ in SETUP_CHANNELS + SETUP_ROLES} | {"timezone"}
        clean = {key: str(payload[key]).strip() for key in allowed if payload.get(key)}
        if clean.get("timezone") not in {None, *(value for _, value in TIMEZONE_LABELS)}:
            raise web.HTTPBadRequest(text="Invalid timezone.")
        if not clean:
            raise web.HTTPBadRequest(text="Nothing to save.")
        guild = next(g for g in self.bot.guilds if str(g.id) == guild_id)
        for key in SETUP_CHANNELS:
            value = clean.get(key[0])
            if value:
                try:
                    valid = guild.get_channel(int(value))
                except (TypeError, ValueError):
                    valid = None
                if valid is None:
                    raise web.HTTPBadRequest(text=f"Invalid channel for {key[1]}.")
        for key in SETUP_ROLES:
            value = clean.get(key[0])
            if value:
                try:
                    valid = guild.get_role(int(value))
                except (TypeError, ValueError):
                    valid = None
                if valid is None:
                    raise web.HTTPBadRequest(text=f"Invalid role for {key[1]}.")
        await self.bot.db.settings.update_one({"_id": guild_id}, {"$set": clean}, upsert=True)
        await self._audit(guild_id, user.user_id, "Web setup updated")
        return web.json_response({"ok": True, "settings": clean})

    async def season(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
        return web.json_response({"season": state})

    async def save_season(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        if "automatic_season_end" in payload:
            value = bool(payload["automatic_season_end"])
            await self.bot.db.settings.update_one({"_id": guild_id}, {"$set": {"automatic_season_end": value}}, upsert=True)
            await self._audit(guild_id, user.user_id, f"Web season automation {'enabled' if value else 'disabled'}")
        return web.json_response({"ok": True})

    async def _audit(self, guild_id: str, user_id: str, action: str) -> None:
        await self.bot.db.system_events.insert_one({"guild_id": guild_id, "source": "web", "user_id": user_id, "action": action})

    async def player_list(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        try:
            limit = max(1, min(100, int(request.query.get("limit", "50"))))
        except ValueError:
            raise web.HTTPBadRequest(text="limit must be an integer.")
        players = await self.players.list_players(guild_id, search=request.query.get("search", ""), limit=limit)
        return web.json_response({"players": players})

    async def player_detail(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        player = await self.players.get_player(guild_id, request.match_info["user_id"])
        if player is None:
            raise web.HTTPNotFound(text="Player not found.")
        return web.json_response({"player": player})

    async def start(self) -> None:
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
