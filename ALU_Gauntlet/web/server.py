"""Small aiohttp control-center server shared with the Discord bot."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from .auth import DiscordOAuth, SESSION_COOKIE
from .players import PlayerService
from .defenses import DefenseService

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "static"


class WebControlCenter:
    """Staff-only web control center with Discord OAuth2 authentication."""

    def __init__(self, bot: Any, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.bot = bot
        self.host = host
        self.port = port
        self.auth = DiscordOAuth(bot)
        self.players = PlayerService(bot)
        self.defenses = DefenseService(bot)
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._configure_routes()

    def _configure_routes(self) -> None:
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/players", self.players_page)
        self.app.router.add_get("/defenses", self.defenses_page)
        self.app.router.add_get("/login", self.login)
        self.app.router.add_get("/auth/callback", self.callback)
        self.app.router.add_get("/logout", self.logout)
        self.app.router.add_get("/api/me", self.me)
        self.app.router.add_get("/api/status", self.status)
        self.app.router.add_get("/api/guilds", self.guilds)
        self.app.router.add_get("/api/players", self.player_list)
        self.app.router.add_get("/api/players/{user_id}", self.player_detail)
        self.app.router.add_get("/api/defenses", self.defense_list)
        self.app.router.add_get("/api/defenses/{user_id}", self.defense_detail)
        self.app.router.add_static("/static/", WEB_DIR, show_index=False)

    async def require_staff(self, request: web.Request) -> Any:
        if not self.auth.configured:
            raise web.HTTPServiceUnavailable(text="Web authentication is not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET.")
        user = await self.auth.get_session(request)
        if user is None:
            raise web.HTTPFound("/login")
        if not user.staff:
            raise web.HTTPForbidden(text="Staff access is required.")
        return user

    async def require_guild_access(self, request: web.Request) -> Any:
        user = await self.require_staff(request)
        guild_id = request.query.get("guild_id", "").strip()
        if not guild_id:
            raise web.HTTPBadRequest(text="guild_id is required.")
        if guild_id not in user.admin_guild_ids and user.user_id not in self.auth.allowed_staff_ids:
            raise web.HTTPForbidden(text="You are not an administrator of this Discord server.")
        guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == guild_id), None)
        if guild is None:
            raise web.HTTPNotFound(text="The bot is not connected to this Discord server.")
        return user, guild_id, guild

    async def index(self, request: web.Request) -> web.StreamResponse:
        await self.require_staff(request)
        return web.FileResponse(WEB_DIR / "index.html")

    async def players_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_staff(request)
        return web.FileResponse(WEB_DIR / "players.html")

    async def defenses_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_staff(request)
        return web.FileResponse(WEB_DIR / "defenses.html")

    async def login(self, request: web.Request) -> web.StreamResponse:
        if not self.auth.configured:
            return web.Response(status=503, text="Web authentication is not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET.", content_type="text/plain")
        user = await self.auth.get_session(request)
        if user and user.staff:
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
            error = request.query.get("error", "Authorization was cancelled.")
            raise web.HTTPUnauthorized(text=error)
        tokens = await self.auth.exchange_code(code)
        access_token = tokens.get("access_token")
        if not access_token:
            raise web.HTTPBadGateway(text="Discord did not return an access token.")
        user = await self.auth.build_user(access_token)
        if not user.staff:
            log.warning("Rejected non-staff web login for Discord user %s", user.user_id)
            raise web.HTTPForbidden(text="Your Discord account does not have staff access.")
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
        user = await self.require_staff(request)
        return web.json_response({"id": user.user_id, "username": user.username, "global_name": user.global_name, "staff": user.staff})

    async def status(self, request: web.Request) -> web.Response:
        await self.require_staff(request)
        ready = bool(getattr(self.bot, "is_ready", lambda: False)())
        guilds = list(getattr(self.bot, "guilds", []) or [])
        latency = getattr(self.bot, "latency", None)
        return web.json_response({"bot": {"online": ready, "latency_ms": round(latency * 1000, 1) if latency is not None else None, "guild_count": len(guilds)}, "control_center": {"phase": 1, "mutations_enabled": False, "simulator_enabled": False}})

    async def guilds(self, request: web.Request) -> web.Response:
        user = await self.require_staff(request)
        bot_guilds = {str(getattr(g, "id", "")): g for g in getattr(self.bot, "guilds", [])}
        allowed = set(user.admin_guild_ids)
        if user.user_id in self.auth.allowed_staff_ids:
            allowed = set(bot_guilds)
        result = [{"id": guild_id, "name": str(getattr(bot_guilds[guild_id], "name", guild_id))} for guild_id in sorted(allowed & bot_guilds.keys())]
        result.sort(key=lambda item: item["name"].casefold())
        return web.json_response({"guilds": result})

    async def player_list(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_access(request)
        search = request.query.get("search", "")
        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            raise web.HTTPBadRequest(text="limit must be an integer.")
        players = await self.players.list_players(guild_id, search=search, limit=limit)
        return web.json_response({"players": players})

    async def player_detail(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_access(request)
        player = await self.players.get_player(guild_id, request.match_info["user_id"])
        if player is None:
            raise web.HTTPNotFound(text="Player not found.")
        return web.json_response({"player": player})

    async def defense_list(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_access(request)
        status = request.query.get("status", "all").strip().lower()
        if status not in {"all", "pending", "locked", "none"}:
            raise web.HTTPBadRequest(text="status must be all, pending, locked, or none.")
        defenses = await self.defenses.list_defenses(guild_id, status=status)
        return web.json_response({"defenses": defenses})

    async def defense_detail(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_access(request)
        defense = await self.defenses.get_defense(guild_id, request.match_info["user_id"])
        if defense is None:
            raise web.HTTPNotFound(text="Defense record not found.")
        return web.json_response({"defense": defense})

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
