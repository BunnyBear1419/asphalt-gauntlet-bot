"""RSL web auth route family."""
import hmac
from .._web_context import *

class AuthRoutesMixin:
    async def asset_icon(self, request):
        filename = request.match_info["filename"]
        if "/" in filename or not filename.endswith(".png"):
            raise web.HTTPNotFound()
        path = WEB_DIR / "assets" / "icons" / filename
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def asset(self, request: web.Request) -> web.Response:
        """Serve dashboard artwork with the correct image MIME type."""
        filename = request.match_info.get("filename", "")
        if not filename or "/" in filename or "\\" in filename:
            raise web.HTTPNotFound(text="Asset not found.")
        path = WEB_DIR / "assets" / filename
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
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

    async def _live_member_for_user(self, guild: Any, user_id: str) -> Any | None:
        """Resolve a user's live membership from the bot-connected Discord guild."""
        try:
            member = guild.get_member(int(user_id))
        except Exception:
            member = None
        if member is not None:
            return member
        try:
            return await guild.fetch_member(int(user_id))
        except Exception:
            log.exception(
                "Unable to resolve live member %s in guild %s",
                user_id,
                getattr(guild, "id", "unknown"),
            )
            return None

    async def _connected_guilds_for_user(self, user: Any) -> dict[str, Any]:
        """Return bot-connected guilds where the signed-in Discord user is actually a member.

        OAuth guild membership is a login-time snapshot and can remain stale for the
        lifetime of a 30-day web session. Live bot membership is the authoritative source
        for RSL web access because the bot can only operate in guilds it is connected to.
        """
        connected: dict[str, Any] = {}
        for guild in list(getattr(self.bot, "guilds", []) or []):
            gid = str(getattr(guild, "id", ""))
            if not gid:
                continue
            if await self._live_member_for_user(guild, str(user.user_id)) is not None:
                connected[gid] = guild
        return connected

    async def require_guild_member(self, request: web.Request) -> tuple[Any, str, Any]:
        """Resolve the active Discord server using live bot membership.

        Explicit guild_id always wins. Otherwise reuse the account's selected guild
        cookie, then the user's live admin guilds, then the first live membership.
        This avoids stale OAuth guild snapshots breaking registration and account pages.
        """
        user = await self.require_user(request)
        connected = await self._connected_guilds_for_user(user)
        candidates = [
            request.query.get("guild_id", "").strip(),
            request.cookies.get("rsl_guild_id", "").strip(),
            *[str(x) for x in getattr(user, "admin_guild_ids", [])],
            *connected.keys(),
        ]
        guild_id = next((gid for gid in candidates if gid and gid in connected), None)
        if not guild_id:
            raise web.HTTPBadRequest(text="No connected Discord server is available for this account.")
        return user, guild_id, connected[guild_id]

    async def _is_live_tournament_staff(self, user: Any, guild_id: str, guild: Any) -> bool:
        """Check administrator or configured tournament-admin role access."""
        if user.user_id in self.auth.allowed_staff_ids:
            return True
        try:
            member = guild.get_member(int(user.user_id))
        except Exception:
            member = None
        if member is None:
            try:
                member = await guild.fetch_member(int(user.user_id))
            except Exception:
                log.exception(
                    "Unable to resolve tournament staff member %s in guild %s",
                    user.user_id,
                    guild_id,
                )
                member = None
        if member is None:
            return False
        permissions = getattr(member, "guild_permissions", None)
        if permissions and (permissions.administrator or permissions.manage_guild):
            return True
        settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        tournament_role_id = str(settings.get("tournament_admin_role_id", "")).strip()
        return bool(
            tournament_role_id
            and any(str(role.id) == tournament_role_id for role in getattr(member, "roles", []))
        )

    async def require_tournament_admin(self, request: web.Request) -> tuple[Any, str, Any]:
        user, guild_id, guild = await self.require_guild_member(request)
        if not await self._is_live_tournament_staff(user, guild_id, guild):
            raise web.HTTPForbidden(text="Tournament administrator access is required for this server.")
        return user, guild_id, guild

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
            for name in ("index.html", "player.html", "players.html", "app.css", "app.js")
        }
        web_files_ok = all(page_files.values())
        return web.json_response({
            "ok": ready and db_ok and web_files_ok,
            "bot_ready": ready,
            "db_ok": db_ok,
            "web_files_ok": web_files_ok,
            "web_files": page_files,
            "release_sha": current_release_revision(),
        })

    async def login(self, request: web.Request) -> web.StreamResponse:
        if not self.auth.configured:
            return web.Response(status=503, text="Web authentication is not configured.", content_type="text/plain")
        user = await self.auth.get_session(request)
        if user:
            raise web.HTTPFound("/")
        state = await self.auth.create_state()
        response = web.Response(
            text=f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign In • Racing Syndicate League</title><link rel="stylesheet" href="/static/app.css?v=20261002-rsl-theme2"></head><body class="alu-dashboard"><main style="min-height:100vh;display:grid;place-items:center;padding:32px"><section class="glass-panel" style="max-width:620px;width:100%;padding:42px;text-align:center"><div class="bottom-logo">RACING <b>SYNDICATE</b> <strong>LEAGUE</strong></div><h1>Sign In to Racing Syndicate League</h1><p class="server-sub">Use your Discord account to access your player profile, registration, matches and staff controls. Your secure web session will be remembered for up to 30 days and refreshed while you use the site.</p><a class="qa qa-purple" href="{self.auth.login_url(state)}">Continue with Discord →</a></section></main></body></html>""",
            content_type="text/html",
        )
        response.set_cookie("rsl_oauth_state", state, max_age=600, httponly=True, secure=self.auth.public_url.startswith("https://"), samesite="Lax", path="/")
        return response

    async def callback(self, request: web.Request) -> web.StreamResponse:
        if not self.auth.configured:
            raise web.HTTPServiceUnavailable(text="Web authentication is not configured.")
        state = request.query.get("state", "").strip()
        code = request.query.get("code", "")
        cookie_state = str(request.cookies.get("rsl_oauth_state") or "").strip()
        if not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
            raise web.HTTPBadRequest(text="Invalid OAuth state.")
        if not await self.auth.consume_state(state):
            raise web.HTTPBadRequest(text="Invalid or expired OAuth state.")
        if not code:
            raise web.HTTPUnauthorized(text=request.query.get("error", "Authorization was cancelled."))
        stage = "token exchange"
        try:
            tokens = await self.auth.exchange_code(code)
            if not isinstance(tokens, dict):
                raise web.HTTPServiceUnavailable(text="Discord returned an invalid OAuth token response.")
            access_token = tokens.get("access_token")
            if not access_token:
                raise web.HTTPServiceUnavailable(text="Discord did not return an access token.")
            stage = "Discord account lookup"
            user = await self.auth.build_user(access_token)
            stage = "web session creation"
            session = await self.auth.create_session(user)
        except web.HTTPException:
            raise
        except Exception as exc:
            log.exception("Discord OAuth callback failed during %s", stage)
            # Keep provider/network/database details server-side. Returning the
            # exception text can disclose internal implementation or upstream
            # response details to an unauthenticated browser.
            return web.Response(
                status=503,
                text="Discord sign-in failed. Please try again in a moment.",
                content_type="text/plain",
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        response = web.HTTPFound("/")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        self.auth.set_session_cookie(response, session)
        response.del_cookie("rsl_oauth_state", path="/")
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
        admin = bool(user.user_id in self.auth.allowed_staff_ids)
        if not admin:
            try:
                for gid in [str(x) for x in getattr(user, "guild_ids", [])]:
                    guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == gid), None)
                    if guild is None:
                        continue
                    member = guild.get_member(int(user.user_id))
                    if member and (member.guild_permissions.administrator or member.guild_permissions.manage_guild):
                        admin = True
                        break
                    if member:
                        settings = await self.bot.db.settings.find_one({"_id": gid}) or {}
                        role_id = str(settings.get("admin_role_id", "")).strip()
                        if role_id and any(str(role.id) == role_id for role in getattr(member, "roles", [])):
                            admin = True
                            break
            except Exception:
                log.exception("Unable to determine web admin status for %s", user.user_id)
        return web.json_response({
            "id": user.user_id,
            "username": user.username,
            "global_name": user.global_name or user.username,
            "avatar": user.avatar,
            "staff": user.staff,
            "admin": admin,
        })

    async def get_language(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        record = await self.bot.db.web_user_preferences.find_one({"_id": str(user.user_id)}) or {}
        language = normalize_language(record.get("language"))
        return web.json_response({"language": language})

    async def set_language(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        try:
            payload = await self._json_object(request)
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid language request.") from exc
        language = str(payload.get("language", "en")).strip()
        allowed = set(RSL_LANGUAGES)
        if language not in allowed:
            raise web.HTTPBadRequest(text="Unsupported language.")
        await self.bot.db.web_user_preferences.update_one(
            {"_id": str(user.user_id)},
            {"$set": {"language": language, "updated_at": time.time()}},
            upsert=True,
        )
        return web.json_response({"ok": True, "language": language})

    async def get_theme(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        record = await self.bot.db.web_user_preferences.find_one({"_id": str(user.user_id)}) or {}
        raw_theme = str(record.get("theme", "")).strip().lower()
        has_saved_theme = raw_theme in THEMES
        theme = raw_theme if has_saved_theme else "dark"
        return web.json_response({"theme": theme, "saved": has_saved_theme})

    async def set_theme(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        try:
            payload = await self._json_object(request)
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid theme request.") from exc
        theme = str(payload.get("theme", "dark")).strip().lower()
        if theme not in THEMES:
            raise web.HTTPBadRequest(text="Unsupported theme.")
        await self.bot.db.web_user_preferences.update_one(
            {"_id": str(user.user_id)},
            {"$set": {"theme": theme, "updated_at": time.time()}},
            upsert=True,
        )
        return web.json_response({"ok": True, "theme": theme})

    async def guilds(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        live_guilds = await self._connected_guilds_for_user(user)
        result = [{
            "id": gid,
            "name": str(getattr(guild, "name", gid)),
            "member": True,
            "admin": gid in user.admin_guild_ids or user.user_id in self.auth.allowed_staff_ids or await self._is_live_guild_staff(user, gid, guild),
        } for gid, guild in live_guilds.items()]
        result.sort(key=lambda item: item["name"].casefold())
        return web.json_response({"guilds": result})
