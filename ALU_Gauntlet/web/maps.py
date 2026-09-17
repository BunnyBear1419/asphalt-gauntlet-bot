"""Read-only map and timing data for the web control center."""
from __future__ import annotations

import re
from typing import Any


class MapService:
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @staticmethod
    def _track_id(track: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", track.lower()).strip("_")

    async def list_maps(self, tracks: list[str], limit: int = 200) -> list[dict[str, Any]]:
        records = await self.bot.db.map_records.find({}).to_list(length=5000)
        refs = await self.bot.db.map_references.find({}).to_list(length=5000)
        by_track = {str(row.get("track", "")): row for row in records}
        by_ref = {str(row.get("_id", "")): row for row in refs}
        result = []
        for track in tracks[:limit]:
            record = by_track.get(track, {})
            ref = by_ref.get(self._track_id(track), {})
            result.append({
                "track": track,
                "best_lap_time": record.get("best_lap_time") or self._format_ms(record.get("best_ms")),
                "best_ms": int(record.get("best_ms", 0) or 0),
                "record_holder_id": str(record.get("user_id", "")) if record.get("user_id") else None,
                "reference_lap_time": ref.get("best_lap_time"),
                "reference_ms": int(ref.get("best_ms", 0) or 0),
                "reference_video": ref.get("video_url"),
                "reference_status": "approved" if ref else "none",
            })
        return result

    async def get_map(self, track: str) -> dict[str, Any] | None:
        record = await self.bot.db.map_records.find_one({"_id": self._track_id(track)})
        ref = await self.bot.db.map_references.find_one({"_id": self._track_id(track)})
        if not record and not ref:
            return None
        return {
            "track": track,
            "record": record or {},
            "reference": ref or {},
        }

    @staticmethod
    def _format_ms(value: Any) -> str | None:
        try:
            ms = int(value or 0)
        except (TypeError, ValueError):
            return None
        if ms <= 0:
            return None
        minutes, remainder = divmod(ms, 60000)
        seconds, millis = divmod(remainder, 1000)
        return f"{minutes}:{seconds:02d}.{millis:03d}"
