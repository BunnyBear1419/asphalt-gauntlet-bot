"""Read-only defense projections for the web control center."""
from __future__ import annotations

from typing import Any


class DefenseService:
    """Expose locked defenses and pending review requests without mutation access."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @staticmethod
    def _courses(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, dict):
            return []
        courses = value.get("courses")
        return courses if isinstance(courses, list) else []

    @staticmethod
    def _projection(row: dict[str, Any]) -> dict[str, Any]:
        defense = row.get("defense_locked") or {}
        pending = row.get("defense_review_payload") or {}
        locked_courses = DefenseService._courses(defense)
        pending_courses = DefenseService._courses(pending)
        return {
            "id": str(row.get("user_id", "")),
            "game_id": row.get("game_id"),
            "locked": bool(locked_courses),
            "locked_at": defense.get("locked_at") or defense.get("approved_at"),
            "locked_courses": locked_courses,
            "review_pending": bool(row.get("defense_review_pending")),
            "review_is_change": bool(pending.get("is_change")),
            "review_submitted_at": pending.get("submitted_at"),
            "review_submission_id": pending.get("submission_id"),
            "review_courses": pending_courses,
        }

    async def list_defenses(self, guild_id: str, status: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        rows = await self.bot.db.drivers.find({"guild_id": str(guild_id)}).to_list(length=limit)
        items = [self._projection(row) for row in rows]
        if status == "pending":
            items = [item for item in items if item["review_pending"]]
        elif status == "locked":
            items = [item for item in items if item["locked"]]
        elif status == "none":
            items = [item for item in items if not item["locked"] and not item["review_pending"]]
        items.sort(key=lambda item: (not item["review_pending"], str(item.get("game_id") or "").casefold()))
        return items

    async def get_defense(self, guild_id: str, user_id: str) -> dict[str, Any] | None:
        row = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"})
        return self._projection(row) if row else None
