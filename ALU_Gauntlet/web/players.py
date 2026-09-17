"""Read-only player data access for the web control center."""
from __future__ import annotations

from typing import Any


class PlayerService:
    """Expose safe, read-only projections of the existing driver collection."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @staticmethod
    def _public_player(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("user_id", "")),
            "game_id": row.get("game_id"),
            "elo": int(row.get("elo", 1000) or 1000),
            "garage_pi": int(row.get("garage_pi", 0) or 0),
            "season_registered": bool(row.get("season_registered", False)),
            "season_number": int(row.get("season_number", 0) or 0),
            "defense_locked": bool(row.get("defense_locked")),
            "streak": int(row.get("streak", 0) or 0),
            "career_wins": int(row.get("career_wins", 0) or 0),
            "career_played": int(row.get("career_played", 0) or 0),
        }

    async def list_players(
        self,
        guild_id: str,
        search: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        query: dict[str, Any] = {"guild_id": str(guild_id)}
        cursor = self.bot.db.drivers.find(query).sort("elo", -1).limit(limit)
        rows = await cursor.to_list(length=limit)
        players = [self._public_player(row) for row in rows]
        term = search.strip().casefold()
        if not term:
            return players
        return [
            player
            for player in players
            if term in str(player.get("game_id") or "").casefold()
            or term in str(player.get("id") or "").casefold()
        ]

    async def get_player(self, guild_id: str, user_id: str) -> dict[str, Any] | None:
        row = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"})
        if not row:
            return None
        return self._public_player(row)
