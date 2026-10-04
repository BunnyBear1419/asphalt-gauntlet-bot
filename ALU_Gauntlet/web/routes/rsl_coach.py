"""Deterministic, guild-scoped RSL Coach extension.

This module deliberately uses only RSL data already stored in MongoDB. It does
not call an external AI service and never mixes data across guilds.
"""
from __future__ import annotations

from typing import Any

from aiohttp import web

from .._web_context import ALU_TRACKS
from .core import CoreRoutesMixin
from .gauntlet import GauntletRoutesMixin


def _parse_ms(value: Any) -> int:
    try:
        text = str(value or "").strip().replace(",", ".")
        if ":" in text:
            minutes, seconds = text.split(":", 1)
            return int(round((float(minutes) * 60 + float(seconds)) * 1000))
        return int(round(float(text) * 1000))
    except (TypeError, ValueError):
        return 0


def _format_ms(ms: int) -> str:
    ms = max(0, int(ms))
    minutes, rem = divmod(ms, 60000)
    seconds, millis = divmod(rem, 1000)
    return f"{minutes}:{seconds:02d}.{millis:03d}"


def build_coach_recommendations(
    *,
    personal_rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
    tracks: tuple[str, ...] | list[str] = ALU_TRACKS,
) -> dict[str, Any]:
    """Build explainable practice recommendations from already scoped data."""
    personal: dict[str, dict[str, Any]] = {}
    for row in personal_rows:
        track = str(row.get("track") or "").strip()
        best_ms = int(row.get("best_ms") or 0)
        if not track or best_ms <= 0:
            continue
        current = personal.get(track.casefold())
        if current is None or best_ms < current["best_ms"]:
            personal[track.casefold()] = {
                "track": track,
                "best_ms": best_ms,
                "car": str(row.get("car") or row.get("car_name") or ""),
            }

    refs: dict[str, dict[str, Any]] = {}
    for row in reference_rows:
        track = str(row.get("course") or row.get("track") or "").strip()
        ref_ms = _parse_ms(row.get("time") or row.get("lap_time"))
        if not track or ref_ms <= 0:
            continue
        key = track.casefold()
        candidate = {
            "track": track,
            "time_ms": ref_ms,
            "title": str(row.get("title") or "RSL Reference"),
            "car": str(row.get("car") or ""),
            "driver": str(row.get("driver") or ""),
            "official": bool(row.get("official", False)),
        }
        current = refs.get(key)
        if current is None or ref_ms < current["time_ms"] or (
            ref_ms == current["time_ms"] and candidate["official"] and not current["official"]
        ):
            refs[key] = candidate

    gaps = []
    for key, ref in refs.items():
        mine = personal.get(key)
        if not mine:
            continue
        gap_ms = mine["best_ms"] - ref["time_ms"]
        if gap_ms > 50:
            gaps.append({
                "track": ref["track"],
                "your_time": _format_ms(mine["best_ms"]),
                "reference_time": _format_ms(ref["time_ms"]),
                "gap_ms": gap_ms,
                "gap": _format_ms(gap_ms),
                "car": mine["car"],
                "reference_car": ref["car"],
                "reference_title": ref["title"],
                "reason": f"You are {gap_ms / 1000:.3f}s off the best approved RSL reference.",
                "priority": "High" if gap_ms >= 1000 else "Medium",
            })
    gaps.sort(key=lambda row: row["gap_ms"], reverse=True)

    known = {key for key in personal}
    missing = [track for track in tracks if str(track).casefold() not in known]
    return {
        "version": 1,
        "method": "deterministic-rsl-data",
        "summary": {
            "personal_tracks": len(personal),
            "reference_tracks": len(refs),
            "actionable_gaps": len(gaps),
            "unrecorded_tracks": len(missing),
        },
        "recommendations": gaps[:8],
        "learn_next": [{"track": track, "reason": "No personal best is recorded for this track yet."} for track in missing[:5]],
    }


async def rsl_coach_page(self: GauntletRoutesMixin, request: web.Request) -> web.StreamResponse:
    await self.require_user(request)
    return await self._page_response("rsl-coach.html", request)


async def rsl_coach(self: GauntletRoutesMixin, request: web.Request) -> web.Response:
    user, guild_id, _ = await self.require_guild_member(request)
    uid, guild = str(user.user_id), str(guild_id)

    personal_rows = await self.bot.db.lap_times.find(
        {"guild_id": guild, "user_id": uid}
    ).sort("best_ms", 1).limit(500).to_list(length=500)

    reference_rows = await self.bot.db.gauntlet_references.find(
        {"guild_id": guild, "status": {"$in": ["approved", "published"]}}
    ).sort("created_at", -1).limit(2000).to_list(length=2000)

    driver = await self.bot.db.drivers.find_one({"_id": f"{guild}_{uid}"}) or {}
    recommendations = build_coach_recommendations(
        personal_rows=personal_rows,
        reference_rows=reference_rows,
        tracks=list(ALU_TRACKS),
    )
    recommendations["driver"] = {
        "division": str(driver.get("division") or driver.get("division_name") or "Unranked"),
        "elo": int(driver.get("elo", 1000) or 1000),
        "season_points": int(driver.get("season_points", 0) or 0),
    }
    recommendations["scope"] = {"guild_id": guild, "user_id": uid}
    return web.json_response(recommendations)


def _install() -> None:
    """Install the extension without changing the existing route family files."""
    if not hasattr(GauntletRoutesMixin, "rsl_coach_page"):
        setattr(GauntletRoutesMixin, "rsl_coach_page", rsl_coach_page)
        setattr(GauntletRoutesMixin, "rsl_coach", rsl_coach)

    original = getattr(CoreRoutesMixin, "_configure_routes")
    if getattr(original, "_rsl_coach_wrapped", False):
        return

    def wrapped(self: CoreRoutesMixin, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        if not any(getattr(route, "resource", None) and route.resource.canonical == "/rsl-coach" for route in self.app.router.routes()):
            self.app.router.add_get("/rsl-coach", self.rsl_coach_page)
        if not any(getattr(route, "resource", None) and route.resource.canonical == "/api/rsl/coach" for route in self.app.router.routes()):
            self.app.router.add_get("/api/rsl/coach", self.rsl_coach)
        return result

    wrapped._rsl_coach_wrapped = True
    CoreRoutesMixin._configure_routes = wrapped


_install()
