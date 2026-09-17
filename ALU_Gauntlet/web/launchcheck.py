"""Read-only production readiness checks for the web control center."""
from __future__ import annotations
import os
import time
from typing import Any


class LaunchCheckService:
    """Mirror the important staff launch/health signals without mutating state."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @staticmethod
    def _check(name: str, ok: bool, detail: str, severity: str = "error") -> dict[str, Any]:
        return {"name": name, "ok": bool(ok), "detail": detail, "severity": severity}

    async def run(self, guild_id: str) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        ready = bool(getattr(self.bot, "is_ready", lambda: False)())
        checks.append(self._check("Discord gateway", ready, "Bot is ready." if ready else "Bot is not ready."))

        latency = getattr(self.bot, "latency", None)
        latency_ok = latency is not None and latency != float("inf")
        latency_text = f"{round(latency * 1000, 1)} ms" if latency_ok else "Unavailable"
        checks.append(self._check("Discord latency", latency_ok, latency_text, "warning"))

        mongo = getattr(self.bot, "mongo_client", None)
        mongo_ok = False
        if mongo:
            try:
                started = time.perf_counter()
                await mongo.admin.command("ping")
                mongo_ms = round((time.perf_counter() - started) * 1000, 1)
                mongo_ok = True
                checks.append(self._check("MongoDB", True, f"Connected • {mongo_ms} ms"))
            except Exception as exc:
                checks.append(self._check("MongoDB", False, f"Ping failed: {str(exc)[:160]}"))
        else:
            checks.append(self._check("MongoDB", False, "MongoDB client is not connected."))

        required = tuple(getattr(self.bot, "REQUIRED_COLLECTIONS", ()))
        if mongo_ok and required:
            try:
                existing = set(await self.bot.db.list_collection_names())
                missing = sorted(set(required) - existing)
                checks.append(self._check("Database collections", not missing, "All required collections exist." if not missing else "Missing: " + ", ".join(missing)))
            except Exception as exc:
                checks.append(self._check("Database collections", False, f"Check failed: {str(exc)[:160]}"))
        elif not mongo_ok:
            checks.append(self._check("Database collections", False, "Skipped because MongoDB is unavailable.", "warning"))

        settings = None
        if mongo_ok:
            try:
                settings = await self.bot.db.settings.find_one({"_id": str(guild_id)}) or {}
                required_settings = ("registration_channel_id", "review_channel_id", "log_channel_id", "admin_role_id", "player_role_id", "timezone")
                missing_settings = [key for key in required_settings if not settings.get(key)]
                checks.append(self._check("Server setup", not missing_settings, "Required setup is configured." if not missing_settings else "Missing: " + ", ".join(missing_settings)))
            except Exception as exc:
                checks.append(self._check("Server setup", False, f"Could not read configuration: {str(exc)[:160]}"))
        else:
            checks.append(self._check("Server setup", False, "Skipped because MongoDB is unavailable.", "warning"))

        guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == str(guild_id)), None)
        checks.append(self._check("Discord server", guild is not None, "Bot is connected to this server." if guild else "Bot is not connected to this server."))

        token_ok = bool(os.getenv("DISCORD_BOT_TOKEN"))
        checks.append(self._check("Bot token", token_ok, "DISCORD_BOT_TOKEN is configured." if token_ok else "DISCORD_BOT_TOKEN is missing."))

        issues = [c for c in checks if not c["ok"] and c["severity"] == "error"]
        warnings = [c for c in checks if not c["ok"] and c["severity"] == "warning"]
        return {
            "guild_id": str(guild_id),
            "ready": not issues,
            "summary": "READY" if not issues else "NOT READY",
            "checks": checks,
            "errors": len(issues),
            "warnings": len(warnings),
            "read_only": True,
            "simulator_enabled": False,
        }
