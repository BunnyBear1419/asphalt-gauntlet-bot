"""A secure, guild-aware web control center shared with the Discord bot."""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from .auth import DiscordOAuth, SESSION_COOKIE
from .players import PlayerService
from ..core.core import ALU_TRACKS, has_5_course_defense, submit_registration_application

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
            # Never expose aiohttp's generic "Server got itself in trouble"
            # page. Log the full traceback server-side and return a controlled
            # response that identifies the failing route.
            log.exception("Unhandled web exception on %s %s", request.method, request.path_qs)
            if request.path.startswith("/api/"):
                return web.json_response(
                    {"ok": False, "error": "The ALU Gauntlet web service hit an unexpected error.", "path": request.path},
                    status=503,
                )
            return web.Response(
                text=(
                    "ALU Gauntlet web service temporarily unavailable. "
                    f"Route: {request.path}"
                ),
                status=503,
                content_type="text/plain",
            )

    async def _page_response(self, filename: str) -> web.Response:
        path = WEB_DIR / filename
        try:
            body = path.read_text(encoding="utf-8")
        except Exception as exc:
            log.exception("Unable to read web page %s", path)
            raise web.HTTPServiceUnavailable(
                text=f"Web page '{filename}' is temporarily unavailable."
            ) from exc
        return web.Response(text=body, content_type="text/html")

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
        self.app.router.add_get("/api/player/defense", self.player_defense)
        self.app.router.add_post("/api/player/defense", self.player_defense_action)
        self.app.router.add_put("/api/player/preferences", self.player_preferences)
        self.app.router.add_post("/api/player/register", self.player_register)
        self.app.router.add_get("/api/setup/options", self.setup_options)
        self.app.router.add_get("/api/setup/settings", self.setup_settings)
        self.app.router.add_put("/api/setup/settings", self.save_setup_settings)
        self.app.router.add_get("/api/season", self.season)
        self.app.router.add_put("/api/season", self.save_season)
        self.app.router.add_get("/api/players", self.player_list)
        self.app.router.add_get("/api/leaderboard", self.leaderboard)
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
        # The homepage is the most important production route. If a stale or
        # malformed web session ever causes an unexpected authentication error,
        # recover to the login page instead of exposing aiohttp's generic 500.
        try:
            await self.require_user(request)
        except web.HTTPException:
            raise
        except Exception:
            log.exception("Unexpected web authentication failure on /")
            response = web.HTTPFound("/login")
            response.del_cookie(SESSION_COOKIE, path="/")
            return response
        try:
            return await self._page_response("index.html")
        except Exception:
            log.exception("Unable to serve the web dashboard")
            raise web.HTTPServiceUnavailable(text="The ALU Gauntlet web dashboard is temporarily unavailable.")

    async def players_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_admin(request)
        return await self._page_response("players.html")

    async def setup_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_admin(request)
        return await self._page_response("setup.html")

    async def player_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("player.html")

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
        page_files = {
            name: (WEB_DIR / name).is_file()
            for name in ("index.html", "player.html", "players.html", "setup.html", "app.css", "app.js")
        }
        web_files_ok = all(page_files.values())
        return web.json_response({
            "ok": ready and db_ok and web_files_ok,
            "bot_ready": ready,
            "db_ok": db_ok,
            "web_files_ok": web_files_ok,
            "web_files": page_files,
        })

    async def login(self, request: web.Request) -> web.StreamResponse:
        if not self.auth.configured:
            return web.Response(status=503, text="Web authentication is not configured.", content_type="text/plain")
        user = await self.auth.get_session(request)
        if user:
            raise web.HTTPFound("/")
        state = await self.auth.create_state()
        return web.Response(
            text=f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign In • ALU Gauntlet</title><link rel="stylesheet" href="/static/app.css"></head><body class="alu-dashboard"><main style="min-height:100vh;display:grid;place-items:center;padding:32px"><section class="glass-panel" style="max-width:620px;width:100%;padding:42px;text-align:center"><div class="bottom-logo">ASPHALT <b>LEGENDS</b> <strong>UNITE</strong></div><h1>Sign In to ALU Gauntlet</h1><p class="server-sub">Use your Discord account to access your player profile, registration, matches and staff controls. Your secure web session will be remembered for up to 30 days and refreshed while you use the site.</p><a class="qa qa-purple" href="{self.auth.login_url(state)}">Continue with Discord →</a></section></main></body></html>""",
            content_type="text/html",
        )

    async def callback(self, request: web.Request) -> web.StreamResponse:
        if not self.auth.configured:
            raise web.HTTPServiceUnavailable(text="Web authentication is not configured.")
        state = request.query.get("state", "")
        code = request.query.get("code", "")
        if not state or not await self.auth.consume_state(state):
            raise web.HTTPBadRequest(text="Invalid or expired OAuth state.")
        if not code:
            raise web.HTTPUnauthorized(text=request.query.get("error", "Authorization was cancelled."))
        try:
            tokens = await self.auth.exchange_code(code)
            if not isinstance(tokens, dict):
                raise web.HTTPBadGateway(text="Discord returned an invalid OAuth token response.")
            access_token = tokens.get("access_token")
            if not access_token:
                raise web.HTTPBadGateway(text="Discord did not return an access token.")
            user = await self.auth.build_user(access_token)
            session = await self.auth.create_session(user)
        except web.HTTPException:
            raise
        except Exception as exc:
            # Do not return HTTP 502 from the application: some reverse proxies
            # replace 502 responses with their own generic error page. Return a
            # normal application response so the actual failure remains visible.
            log.exception("Discord OAuth callback failed")
            return web.Response(
                status=503,
                text="Discord sign-in could not be completed. Please try again. Check the server logs for the OAuth failure.",
                content_type="text/plain",
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        response = web.HTTPFound("/")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        self.auth.set_session_cookie(response, session)
        return response

    async def logout(self, request: web.Request) -> web.StreamResponse:
        try:
            await self.auth.destroy_session(request)
        except Exception:
            log.exception("Unable to remove web session during logout")
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
        preferences = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        return web.json_response({
            "player": player,
            "user": {"id": user.user_id, "username": user.username, "global_name": user.global_name},
            "preferences": {key: preferences.get(key) for key in ("timezone", "web_notifications", "dm_notifications")},
        })

    async def player_defense(self, request: web.Request) -> web.Response:
        """Return the player's current/pending five-course defense state."""
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
        _, guild_id, _ = await self.require_guild_member(request)
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

    async def leaderboard(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_member(request)
        try:
            limit = max(1, min(25, int(request.query.get("limit", "10"))))
        except ValueError:
            raise web.HTTPBadRequest(text="limit must be an integer.")
        rows = await self.players.list_players(guild_id, limit=limit)
        return web.json_response({"players": rows})

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
