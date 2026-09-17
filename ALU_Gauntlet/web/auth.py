"""Discord OAuth2 authentication for the web control center."""
from __future__ import annotations

import asyncio
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from aiohttp import ClientSession, web

DISCORD_API = "https://discord.com/api/v10"
ADMINISTRATOR = 1 << 3
SESSION_COOKIE = "alu_web_session"
SESSION_TTL = 8 * 60 * 60
STATE_TTL = 10 * 60
PRODUCTION_PUBLIC_URL = "https://asph.discloud.app"


@dataclass(slots=True)
class WebUser:
    user_id: str
    username: str
    global_name: str | None
    avatar: str | None
    staff: bool
    admin_guild_ids: set[str] = field(default_factory=set)


class DiscordOAuth:
    """Small in-memory OAuth/session store for the single bot process."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.configured_client_id = os.getenv("DISCORD_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
        configured_public_url = os.getenv("WEB_PUBLIC_URL", "").strip().rstrip("/")
        self.public_url = configured_public_url or PRODUCTION_PUBLIC_URL
        self.allowed_staff_ids = {
            value.strip()
            for value in os.getenv("WEB_STAFF_USER_IDS", "").split(",")
            if value.strip()
        }
        self.sessions: dict[str, tuple[float, WebUser]] = {}
        self.states: dict[str, float] = {}
        self._lock = asyncio.Lock()

    @property
    def client_id(self) -> str:
        bot_user = getattr(self.bot, "user", None)
        bot_id = getattr(bot_user, "id", None)
        if bot_id:
            return str(bot_id)
        return self.configured_client_id

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/callback"

    def login_url(self, state: str) -> str:
        from urllib.parse import urlencode
        params = urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
        })
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
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        async with ClientSession() as session:
            async with session.post(f"{DISCORD_API}/oauth2/token", data=payload, timeout=15) as response:
                if response.status != 200:
                    raise web.HTTPBadGateway(text="Discord OAuth token exchange failed.")
                return await response.json()

    async def discord_get(self, path: str, access_token: str) -> Any:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with ClientSession() as session:
            async with session.get(f"{DISCORD_API}{path}", headers=headers, timeout=15) as response:
                if response.status != 200:
                    raise web.HTTPBadGateway(text="Discord OAuth API request failed.")
                return await response.json()

    async def _configured_staff_role_ids(self, guild_ids: set[str]) -> dict[str, str]:
        """Return guild -> configured Staff/admin role ID from persisted setup."""
        db = getattr(self.bot, "db", None)
        # PyMongo AsyncDatabase deliberately does not support truth-value testing.
        # Compare it to None explicitly instead of evaluating it with `not`/bool().
        if not guild_ids or db is None:
            return {}
        rows = await db.settings.find({"_id": {"$in": list(guild_ids)}}).to_list(length=len(guild_ids))
        result: dict[str, str] = {}
        for row in rows:
            guild_id = str(row.get("_id", ""))
            role_id = row.get("admin_role_id")
            if role_id:
                result[guild_id] = str(role_id)
        return result

    async def build_user(self, access_token: str) -> WebUser:
        profile = await self.discord_get("/users/@me", access_token)
        guilds = await self.discord_get("/users/@me/guilds", access_token)
        user_id = str(profile["id"])

        global_staff = user_id in self.allowed_staff_ids
        guild_ids = {str(guild.get("id")) for guild in guilds if guild.get("id")}
        configured_roles = await self._configured_staff_role_ids(guild_ids)
        admin_guild_ids: set[str] = set()

        for guild in guilds:
            guild_id = str(guild.get("id", ""))
            if not guild_id:
                continue
            try:
                permissions = int(guild.get("permissions", 0))
            except (TypeError, ValueError):
                permissions = 0

            member_roles = {str(role_id) for role_id in (guild.get("roles") or [])}
            staff_role_id = configured_roles.get(guild_id)
            if permissions & ADMINISTRATOR or (staff_role_id and staff_role_id in member_roles):
                admin_guild_ids.add(guild_id)

        staff = global_staff or bool(admin_guild_ids)
        if global_staff:
            admin_guild_ids = {str(getattr(guild, "id", "")) for guild in getattr(self.bot, "guilds", [])}

        return WebUser(
            user_id=user_id,
            username=str(profile.get("username", "Unknown")),
            global_name=profile.get("global_name"),
            avatar=profile.get("avatar"),
            staff=staff,
            admin_guild_ids=admin_guild_ids,
        )

    async def create_session(self, user: WebUser) -> str:
        token = secrets.token_urlsafe(32)
        async with self._lock:
            self.sessions[token] = (time.time() + SESSION_TTL, user)
        return token

    async def get_session(self, request: web.Request) -> WebUser | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        async with self._lock:
            entry = self.sessions.get(token)
            if not entry:
                return None
            expiry, user = entry
            if expiry <= time.time():
                self.sessions.pop(token, None)
                return None
            return user

    async def destroy_session(self, request: web.Request) -> None:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            async with self._lock:
                self.sessions.pop(token, None)

    def set_session_cookie(self, response: web.StreamResponse, token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_TTL,
            httponly=True,
            secure=self.public_url.startswith("https://"),
            samesite="Lax",
            path="/",
        )
