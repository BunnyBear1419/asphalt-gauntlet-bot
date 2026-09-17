"""Discord OAuth2 authentication for the web control center."""
from __future__ import annotations

import asyncio
import os
import secrets
import time
from dataclasses import dataclass
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
    admin_guild_ids: frozenset[str]
    guild_ids: frozenset[str]


class DiscordOAuth:
    """Small in-memory OAuth/session store for the single bot process."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.client_id = os.getenv("DISCORD_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
        self.public_url = os.getenv("WEB_PUBLIC_URL", PRODUCTION_PUBLIC_URL).rstrip("/")
        self.allowed_staff_ids = {value.strip() for value in os.getenv("WEB_STAFF_USER_IDS", "").split(",") if value.strip()}
        self.sessions: dict[str, tuple[float, WebUser]] = {}
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

    async def build_user(self, access_token: str) -> WebUser:
        profile = await self.discord_get("/users/@me", access_token)
        guilds = await self.discord_get("/users/@me/guilds", access_token)
        user_id = str(profile["id"])
        admin_guild_ids: set[str] = set()
        guild_ids: set[str] = {str(guild.get("id")) for guild in guilds if guild.get("id")}
        for guild in guilds:
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
            except (TypeError, ValueError, KeyError):
                continue
        staff = user_id in self.allowed_staff_ids or bool(admin_guild_ids)
        return WebUser(user_id=user_id, username=str(profile.get("username", "Unknown")), global_name=profile.get("global_name"), avatar=profile.get("avatar"), staff=staff, admin_guild_ids=frozenset(admin_guild_ids), guild_ids=frozenset(guild_ids))

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
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, httponly=True, secure=self.public_url.startswith("https://"), samesite="Lax", path="/")
