"""Discord OAuth2 authentication for the web control center."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientSession, web

DISCORD_API = "https://discord.com/api/v10"
ADMINISTRATOR = 1 << 3
SESSION_COOKIE = "alu_web_session"
SESSION_TTL = 30 * 24 * 60 * 60
STATE_TTL = 10 * 60
PRODUCTION_PUBLIC_URL = "https://asph.discloud.app"


@dataclass(slots=True)
class WebUser:
    user_id: str
    username: str
    global_name: str | None
    avatar: str | None
    staff: bool
    admin_guild_ids: frozenset[str]
    guild_ids: frozenset[str]


class DiscordOAuth:
    """Discord OAuth with persistent Mongo-backed web sessions."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.client_id = os.getenv("DISCORD_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
        self.public_url = os.getenv("WEB_PUBLIC_URL", PRODUCTION_PUBLIC_URL).rstrip("/")
        self.allowed_staff_ids = {value.strip() for value in os.getenv("WEB_STAFF_USER_IDS", "").split(",") if value.strip()}
        # MongoDB is the durable session store; the in-memory map is retained only\n        # as a fast cache for the current process.\n        self.sessions: dict[str, tuple[float, WebUser]] = {}
        self.states: dict[str, float] = {}
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/callback"

    def login_url(self, state: str) -> str:
        from urllib.parse import urlencode
        params = urlencode({"client_id": self.client_id, "redirect_uri": self.redirect_uri, "response_type": "code", "scope": "identify guilds", "state": state})
        return f"https://discord.com/oauth2/authorize?{params}"

    async def create_state(self) -> str:
        async with self._lock:
            now = time.time()
            self.states = {key: expiry for key, expiry in self.states.items() if expiry > now}
            state = secrets.token_urlsafe(32)
            self.states[state] = now + STATE_TTL
            return state

    async def consume_state(self, state: str) -> bool:
        async with self._lock:
            expiry = self.states.pop(state, None)
            return expiry is not None and expiry > time.time()

    async def exchange_code(self, code: str) -> dict[str, Any]:
        payload = {"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri}
        try:
            async with ClientSession() as session:
                async with session.post(f"{DISCORD_API}/oauth2/token", data=payload, timeout=15) as response:
                    if response.status != 200:
                        try:
                            error_payload = await response.json(content_type=None)
                        except Exception:
                            error_payload = {}
                        error_code = str(error_payload.get("error", "")).strip() if isinstance(error_payload, dict) else ""
                        error_desc = str(error_payload.get("error_description", "")).strip() if isinstance(error_payload, dict) else ""
                        detail = f" {error_code}: {error_desc}".strip() if error_code or error_desc else ""
                        log_message = f"Discord OAuth token exchange failed: HTTP {response.status}{detail}"
                        # Keep the detailed Discord response in server logs; never expose
                        # client secrets or authorization codes to the browser.
                        print(log_message)
                        raise web.HTTPServiceUnavailable(
                            text=f"Discord OAuth token exchange failed (HTTP {response.status}).{detail}"
                        )
                    return await response.json()
        except (ClientError, asyncio.TimeoutError) as exc:
            print(f"Discord OAuth token exchange network failure: {type(exc).__name__}: {exc}")
            raise web.HTTPServiceUnavailable(
                text="Discord OAuth token exchange could not reach Discord. Check the Discloud outbound connection."
            ) from exc

    async def discord_get(self, path: str, access_token: str) -> Any:
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with ClientSession() as session:
                async with session.get(f"{DISCORD_API}{path}", headers=headers, timeout=15) as response:
                    if response.status != 200:
                        raise web.HTTPServiceUnavailable(text=f"Discord OAuth API request failed (HTTP {response.status}).")
                    return await response.json()
        except (ClientError, asyncio.TimeoutError) as exc:
            print(f"Discord OAuth API network failure for {path}: {type(exc).__name__}: {exc}")
            raise web.HTTPServiceUnavailable(
                text=f"Discord OAuth API request could not reach Discord ({path})."
            ) from exc

    async def build_user(self, access_token: str) -> WebUser:
        profile = await self.discord_get("/users/@me", access_token)
        if not isinstance(profile, dict) or not profile.get("id"):
            raise web.HTTPBadGateway(text="Discord returned an invalid account profile.")
        guilds = await self.discord_get("/users/@me/guilds", access_token)
        if not isinstance(guilds, list):
            # Discord should return a list here, but treat an unexpected payload
            # as an empty guild list instead of crashing the OAuth callback.
            guilds = []
        user_id = str(profile["id"])
        admin_guild_ids: set[str] = set()
        guild_ids: set[str] = {str(guild.get("id")) for guild in guilds if isinstance(guild, dict) and guild.get("id")}
        for guild in guilds:
            if not isinstance(guild, dict) or not guild.get("id"):
                continue
            try:
                gid = str(guild["id"])
                if int(guild.get("permissions", 0)) & ADMINISTRATOR:
                    admin_guild_ids.add(gid)
                    continue
                # Match the Discord bot's configured staff role when the bot can
                # resolve the member. This keeps web permissions aligned with Discord.
                discord_guild = self.bot.get_guild(int(gid))
                member = discord_guild.get_member(int(user_id)) if discord_guild else None
                if member is None and discord_guild:
                    try:
                        member = await discord_guild.fetch_member(int(user_id))
                    except Exception:
                        member = None
                if member is not None and getattr(self.bot, "db", None) is not None:
                    settings = await self.bot.db.settings.find_one({"_id": gid}) or {}
                    role_id = str(settings.get("admin_role_id", "")).strip()
                    if role_id and any(str(role.id) == role_id for role in getattr(member, "roles", [])):
                        admin_guild_ids.add(gid)
            except Exception:
                # A single unavailable Discord/Mongo guild lookup must not abort
                # the entire OAuth login for the user.
                continue
        staff = user_id in self.allowed_staff_ids or bool(admin_guild_ids)
        return WebUser(user_id=user_id, username=str(profile.get("username", "Unknown")), global_name=profile.get("global_name"), avatar=profile.get("avatar"), staff=staff, admin_guild_ids=frozenset(admin_guild_ids), guild_ids=frozenset(guild_ids))

    @staticmethod
    def _session_key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _serialize_user(user: WebUser) -> dict[str, Any]:
        return {
            "user_id": user.user_id,
            "username": user.username,
            "global_name": user.global_name,
            "avatar": user.avatar,
            "staff": user.staff,
            "admin_guild_ids": list(user.admin_guild_ids),
            "guild_ids": list(user.guild_ids),
        }

    @staticmethod
    def _deserialize_user(data: dict[str, Any]) -> WebUser:
        return WebUser(
            user_id=str(data.get("user_id", "")),
            username=str(data.get("username", "Unknown")),
            global_name=data.get("global_name"),
            avatar=data.get("avatar"),
            staff=bool(data.get("staff")),
            admin_guild_ids=frozenset(str(x) for x in data.get("admin_guild_ids", [])),
            guild_ids=frozenset(str(x) for x in data.get("guild_ids", [])),
        )

    async def create_session(self, user: WebUser) -> str:
        token = secrets.token_urlsafe(32)
        expiry = time.time() + SESSION_TTL
        # Defensive lazy initialization keeps authentication recoverable if a
        # long-lived web process was started from an older module instance.
        if not hasattr(self, "sessions"):
            self.sessions = {}
        async with self._lock:
            self.sessions[token] = (expiry, user)
        db = getattr(self.bot, "db", None)
        if db is not None:
            try:
                await db.web_sessions.update_one(
                    {"_id": self._session_key(token)},
                    {"$set": {"expires_at": expiry, "user": self._serialize_user(user), "created_at": time.time(), "last_seen": time.time()}},
                    upsert=True,
                )
            except Exception:
                # Authentication must remain available even if the optional
                # durable session store is temporarily unavailable.
                pass
        return token

    async def get_session(self, request: web.Request) -> WebUser | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        now = time.time()
        # Recover safely if a long-lived process retained an older OAuth instance
        # created before the in-memory session cache was initialized.
        if not hasattr(self, "sessions"):
            self.sessions = {}
        async with self._lock:
            entry = self.sessions.get(token)
            if entry:
                expiry, user = entry
                if expiry > now:
                    return user
                self.sessions.pop(token, None)
        db = getattr(self.bot, "db", None)
        if db is None:
            return None
        try:
            record = await db.web_sessions.find_one({"_id": self._session_key(token)})
            if not record or float(record.get("expires_at", 0)) <= now:
                if record:
                    await db.web_sessions.delete_one({"_id": self._session_key(token)})
                return None
            user = self._deserialize_user(record.get("user") or {})
            new_expiry = now + SESSION_TTL
            await db.web_sessions.update_one({"_id": self._session_key(token)}, {"$set": {"expires_at": new_expiry, "last_seen": now}})
        except Exception:
            # A broken/temporarily unavailable durable session must not turn
            # every authenticated page request into HTTP 500.
            return None
        async with self._lock:
            self.sessions[token] = (new_expiry, user)
        return user

    async def destroy_session(self, request: web.Request) -> None:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            async with self._lock:
                self.sessions.pop(token, None)
            db = getattr(self.bot, "db", None)
            if db is not None:
                try:
                    await db.web_sessions.delete_one({"_id": self._session_key(token)})
                except Exception:
                    # Logout must still clear the browser cookie if Mongo is
                    # temporarily unavailable.
                    pass

    def set_session_cookie(self, response: web.StreamResponse, token: str) -> None:
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, httponly=True, secure=self.public_url.startswith("https://"), samesite="Lax", path="/")
