"""Read-only audit and system event access for the web control center."""
from __future__ import annotations
from typing import Any

class LogService:
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def list_logs(self, guild_id: str, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        rows = await self.bot.db.system_events.find({"guild_id": str(guild_id)}).sort("timestamp", -1).limit(limit).to_list(length=limit)
        result = []
        for row in rows:
            action = row.get("action") or row.get("event") or row.get("name") or "System Event"
            details = row.get("details") or row.get("message") or row.get("description") or ""
            event_type = str(row.get("type") or row.get("category") or ("admin" if "admin" in str(action).lower() else "system")).lower()
            result.append({
                "id": str(row.get("_id", "")),
                "timestamp": row.get("timestamp") or row.get("created_at") or row.get("time"),
                "type": event_type,
                "action": str(action),
                "details": str(details),
            })
        return result
