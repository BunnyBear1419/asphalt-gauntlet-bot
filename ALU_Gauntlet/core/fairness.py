"""RSL Gauntlet fairness analytics and match-protection helpers.

These signals are advisory. They never automatically accuse, punish, demote, or
block a driver. Staff can review the evidence before taking any action.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Any


SCORE_BUCKETS = ("5-0", "4-1", "3-2", "2-3", "1-4", "0-5")


def score_bucket(courses_beat: int, perspective_won: bool) -> str:
    score = max(0, min(5, int(courses_beat)))
    own = score if perspective_won else 5 - score
    return f"{own}-{5-own}"


def fair_match_snapshot(challenger: dict[str, Any], opponent: dict[str, Any]) -> dict[str, Any]:
    challenger_elo = int(challenger.get("elo", 1000) or 1000)
    opponent_elo = int(opponent.get("elo", 1000) or 1000)
    challenger_pi = int(challenger.get("garage_pi", 0) or 0)
    opponent_pi = int(opponent.get("garage_pi", 0) or 0)
    try:
        from .core import get_division_for_pi
        same_division = get_division_for_pi(challenger_pi)["name"] == get_division_for_pi(opponent_pi)["name"]
    except Exception:
        same_division = True
    return {
        "challenger_elo": challenger_elo,
        "opponent_elo": opponent_elo,
        "elo_gap": abs(challenger_elo - opponent_elo),
        "challenger_pi": challenger_pi,
        "opponent_pi": opponent_pi,
        "pi_gap": abs(challenger_pi - opponent_pi),
        "same_division": same_division,
        "summary": f"ELO gap {abs(challenger_elo-opponent_elo):,} • PI gap {abs(challenger_pi-opponent_pi):,} • {'same division' if same_division else 'cross-division'}",
    }


async def record_match_fairness_stats(db, match_data: dict[str, Any]) -> None:
    """Record per-driver dominance history and the last three opponents.

    A match is claimed once so retries cannot duplicate race counters/history.
    """
    match_id = str(match_data.get("_id", ""))
    claim = await db.matches.update_one(
        {"_id": match_id, "rsl_fairness_stats_applied": {"$ne": True}},
        {"$set": {"rsl_fairness_stats_applied": True}},
    )
    if getattr(claim, "modified_count", 0) != 1:
        return

    guild_id = str(match_data.get("guild_id", ""))
    challenger_id = str(match_data.get("challenger_id", ""))
    opponent_id = str(match_data.get("opponent_id", ""))
    winner_id = str(match_data.get("w_id") or match_data.get("winner_id") or "")
    if winner_id not in {challenger_id, opponent_id}:
        await db.matches.update_one({"_id": match_id}, {"$unset": {"rsl_fairness_stats_applied": ""}})
        raise ValueError("Match fairness stats require a valid winner")

    loser_id = opponent_id if winner_id == challenger_id else challenger_id
    courses_beat = int(match_data.get("courses_beat", 0) or 0)
    winner_bucket = score_bucket(courses_beat, True)
    loser_bucket = score_bucket(courses_beat, False)

    for user_id, bucket, race_wins in (
        (winner_id, winner_bucket, courses_beat),
        (loser_id, loser_bucket, 5 - courses_beat),
    ):
        await db.drivers.update_one(
            {"_id": f"{guild_id}_{user_id}"},
            {
                "$inc": {
                    "rsl_dominance.total_matches": 1,
                    "rsl_dominance.total_races": 5,
                    "rsl_dominance.race_wins": race_wins,
                    "rsl_dominance.race_losses": 5 - race_wins,
                    f"rsl_dominance.score_buckets.{bucket}": 1,
                },
                "$set": {"rsl_dominance.last_match_score": bucket},
                "$push": {
                    "gauntlet_recent_opponents": {
                        "$each": [{"user_id": loser_id if user_id == winner_id else winner_id, "match_id": match_id}],
                        "$slice": -3,
                    }
                },
            },
        )


async def build_fairness_review(db, guild_id: str, limit: int = 50) -> dict[str, Any]:
    """Build staff-only advisory fairness signals from recorded match evidence."""
    guild_id = str(guild_id)
    drivers = await db.drivers.find({"guild_id": guild_id}).to_list(length=5000)
    matches = await db.matches.find(
        {"guild_id": guild_id, "reverted": {"$ne": True}, "w_id": {"$exists": True}}
    ).sort("timestamp", -1).to_list(length=5000)

    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        for uid in (str(match.get("challenger_id", "")), str(match.get("opponent_id", ""))):
            if uid:
                by_user[uid].append(match)

    division_values: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        from .core import get_division_for_pi
        for driver in drivers:
            division_values[get_division_for_pi(int(driver.get("garage_pi", 0) or 0))["name"]].append(driver)
    except Exception:
        division_values["Unknown"] = drivers

    medians = {}
    for division, rows in division_values.items():
        medians[division] = {
            "pi": median([int(x.get("garage_pi", 0) or 0) for x in rows]) if rows else 0,
            "elo": median([int(x.get("elo", 1000) or 1000) for x in rows]) if rows else 1000,
        }

    reviews = []
    for driver in drivers:
        uid = str(driver.get("user_id", ""))
        history = by_user.get(uid, [])
        played = len(history)
        if played < 8:
            continue
        wins = sum(1 for m in history if str(m.get("w_id")) == uid)
        win_rate = wins / played if played else 0
        scores = [
            score_bucket(int(m.get("courses_beat", 0) or 0), str(m.get("w_id")) == uid)
            for m in history
        ]
        counts = Counter(scores)
        flags = []
        if counts["3-2"] >= 5 and counts["3-2"] / played >= 0.60 and win_rate >= 0.70:
            flags.append("High concentration of narrow 3-2 wins")
        try:
            from .core import get_division_for_pi
            division = get_division_for_pi(int(driver.get("garage_pi", 0) or 0))["name"]
        except Exception:
            division = "Unknown"
        med = medians.get(division, {"pi": 0, "elo": 1000})
        if med["pi"] and int(driver.get("garage_pi", 0) or 0) >= med["pi"] * 1.15 and int(driver.get("elo", 1000) or 1000) <= med["elo"] - 100:
            flags.append("Garage PI materially above division median while ELO is below median")
        recent_scores = scores[:5]
        if sum(1 for x in recent_scores if x in {"4-1", "5-0"}) >= 3 and len(scores) >= 8:
            prior = scores[5:10]
            if prior and sum(1 for x in prior if x == "3-2") >= 3:
                flags.append("Recent dominance increase after a narrow-result run")
        recent_opponents = [str(x.get("opponent_id")) for x in (driver.get("gauntlet_recent_opponents") or [])]
        if len(recent_opponents) < 3:
            recent_opponents = [str((m.get("opponent_id") if str(m.get("challenger_id")) == uid else m.get("challenger_id"))) for m in history[:3]]
        if len(set(recent_opponents)) < len(recent_opponents) and len(recent_opponents) >= 3:
            flags.append("Repeated recent opponent selection")
        if flags:
            reviews.append({
                "user_id": uid,
                "name": str(driver.get("game_id") or driver.get("username") or uid),
                "elo": int(driver.get("elo", 1000) or 1000),
                "garage_pi": int(driver.get("garage_pi", 0) or 0),
                "played": played,
                "wins": wins,
                "win_rate": round(win_rate * 100, 1),
                "score_counts": {bucket: counts.get(bucket, 0) for bucket in SCORE_BUCKETS},
                "flags": flags,
            })
    reviews.sort(key=lambda row: (len(row["flags"]), row["played"]), reverse=True)
    return {
        "advisory_only": True,
        "drivers_scanned": len(drivers),
        "matches_scanned": len(matches),
        "reviews": reviews[:max(1, min(int(limit), 100))],
    }
