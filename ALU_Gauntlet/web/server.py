"""Small aiohttp control-center server shared with the Discord bot."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from .auth import DiscordOAuth, SESSION_COOKIE
from .players import PlayerService
from .defenses import DefenseService
from .matches import MatchService

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
        self.matches = MatchService(bot)
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._configure_routes()

    def _configure_routes(self) -> None:
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/players", self.players_page)
        self.app.router.add_get("/defenses", self.defenses_page)
        self.app.router.add_get("/matches", self.matches_page)
        self.app.router.add_get("/seasons", self.seasons_page)
        self.app.router.add_get("/analytics", self.analytics_page)
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
        self.app.router.add_get("/api/matches", self.match_list)
        self.app.router.add_get("/api/matches/{match_id}", self.match_detail)
        self.app.router.add_get("/api/seasons", self.season_list)
        self.app.router.add_get("/api/seasons/{season_number}", self.season_detail)
        self.app.router.add_get("/api/analytics", self.analytics)
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

    async def matches_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_staff(request)
        return web.FileResponse(WEB_DIR / "matches.html")

    async def seasons_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_staff(request)
        return web.FileResponse(WEB_DIR / "seasons.html")

    async def analytics_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_staff(request)
        return web.FileResponse(WEB_DIR / "analytics.html")

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

    async def match_list(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_access(request)
        try:
            limit = int(request.query.get("limit", "100"))
        except ValueError:
            raise web.HTTPBadRequest(text="limit must be an integer.")
        matches = await self.matches.list_matches(guild_id, limit=limit)
        return web.json_response({"matches": matches})

    async def match_detail(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_access(request)
        match = await self.matches.get_match(guild_id, request.match_info["match_id"])
        if match is None:
            raise web.HTTPNotFound(text="Match not found.")
        return web.json_response({"match": match})

    async def season_list(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_access(request)
        state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
        config = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        current = self._public_season_state(guild_id, state, config)
        cursor = self.bot.db.season_history.find({"guild_id": guild_id}).sort("season_number", -1).limit(25)
        history = await cursor.to_list(length=25)
        return web.json_response({"current": current, "history": [self._public_archive(row) for row in history]})

    async def season_detail(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_access(request)
        try:
            season_number = int(request.match_info["season_number"])
        except ValueError:
            raise web.HTTPBadRequest(text="season_number must be an integer.")
        archive = await self.bot.db.season_history.find_one({"_id": f"{guild_id}_{season_number}", "guild_id": guild_id})
        if archive is None:
            raise web.HTTPNotFound(text="Season archive not found.")
        return web.json_response({"season": self._public_archive(archive, include_standings=True)})

    async def analytics(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_access(request)
        players = await self.bot.db.drivers.count_documents({"guild_id": guild_id})
        registered = await self.bot.db.drivers.count_documents({"guild_id": guild_id, "season_registered": True})
        locked = await self.bot.db.drivers.count_documents({"guild_id": guild_id, "defense": {"$exists": True}})
        matches = await self.bot.db.matches.count_documents({"guild_id": guild_id})
        completed = await self.bot.db.matches.count_documents({"guild_id": guild_id, "status": "completed"})
        history_cursor = self.bot.db.season_history.find({"guild_id": guild_id}).sort("season_number", -1).limit(25)
        history = await history_cursor.to_list(length=25)
        season_stats = []
        for row in history:
            standings = row.get("standings", [])
            elos = [int(item.get("elo", 1000) or 1000) for item in standings]
            season_stats.append({"season_number": int(row.get("season_number", 0) or 0), "player_count": int(row.get("player_count", len(standings)) or 0), "average_elo": round(sum(elos) / len(elos), 1) if elos else None, "closed_at": row.get("closed_at")})
        return web.json_response({"players": players, "registered": registered, "defenses": locked, "matches": matches, "completed_matches": completed, "seasons": season_stats})

    @staticmethod
    def _public_season_state(guild_id: str, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        return {
            "guild_id": guild_id,
            "season_number": int(state.get("season_number", 1) or 1),
            "season_active": bool(state.get("season_active", False)),
            "awaiting_staff_start": bool(state.get("awaiting_staff_start", False)),
            "starts_at": state.get("starts_at"),
            "ends_at": state.get("ends_at"),
            "started_at": state.get("started_at"),
            "automatic_rollover": bool(config.get("automatic_season_end", False)),
        }

    @staticmethod
    def _public_archive(row: dict[str, Any], include_standings: bool = False) -> dict[str, Any]:
        result = {
            "season_number": int(row.get("season_number", 0) or 0),
            "player_count": int(row.get("player_count", len(row.get("standings", []))) or 0),
            "closed_at": row.get("closed_at"),
        }
        if include_standings:
            result["standings"] = [
                {"rank": item.get("rank"), "user_id": str(item.get("user_id", "")), "elo": int(item.get("elo", 1000) or 1000), "division": str(item.get("division", "Unranked"))}
                for item in row.get("standings", [])[:100]
            ]
        return result

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
