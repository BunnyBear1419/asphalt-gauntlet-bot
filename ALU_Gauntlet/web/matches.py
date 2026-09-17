"""Read-only match data access for the web control center."""
from __future__ import annotations

from typing import Any


class MatchService:
    """Expose safe match projections without changing settlement state."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @staticmethod
    def _public_match(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("_id", "")),
            "guild_id": str(row.get("guild_id", "")),
            "challenger_id": str(row.get("challenger_id", "")),
            "opponent_id": str(row.get("opponent_id", "")),
            "season_number": int(row.get("season_number", 0) or 0),
            "courses_beat": int(row.get("courses_beat", 0) or 0),
            "challenger_won": bool(row.get("challenger_won", False)),
            "status": str(row.get("status", "completed")),
            "created_at": row.get("created_at", row.get("timestamp")),
            "completed_at": row.get("completed_at"),
        }

    async def list_matches(self, guild_id: str, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        cursor = self.bot.db.matches.find({"guild_id": str(guild_id)}).sort("created_at", -1).limit(limit)
        rows = await cursor.to_list(length=limit)
        return [self._public_match(row) for row in rows]

    async def get_match(self, guild_id: str, match_id: str) -> dict[str, Any] | None:
        row = await self.bot.db.matches.find_one({"_id": match_id, "guild_id": str(guild_id)})
        if not row:
            return None
        return self._public_match(row)
