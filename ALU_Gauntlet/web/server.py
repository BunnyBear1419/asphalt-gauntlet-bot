"""Small aiohttp control-center server shared with the Discord bot."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "static"


class WebControlCenter:
    """Read-only Phase 1 web control center.

    Mutating controls are intentionally added only after authentication and
    permission checks are wired to the existing Gauntlet service layer.
    """

    def __init__(self, bot: Any, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.bot = bot
        self.host = host
        self.port = port
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._configure_routes()

    def _configure_routes(self) -> None:
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/api/status", self.status)
        self.app.router.add_static("/static/", WEB_DIR, show_index=False)

    async def index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(WEB_DIR / "index.html")

    async def status(self, request: web.Request) -> web.Response:
        ready = bool(getattr(self.bot, "is_ready", lambda: False)())
        guilds = list(getattr(self.bot, "guilds", []) or [])
        latency = getattr(self.bot, "latency", None)
        return web.json_response(
            {
                "bot": {
                    "online": ready,
                    "latency_ms": round(latency * 1000, 1) if latency is not None else None,
                    "guild_count": len(guilds),
                },
                "control_center": {
                    "phase": 1,
                    "mutations_enabled": False,
                },
            }
        )

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
