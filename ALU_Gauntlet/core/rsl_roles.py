"""RSL progression, achievement, and seasonal Discord-role policy.

This module is deliberately Discord/Mongo independent. It defines which roles
are permanent progression/achievement roles and which roles belong only to the
current Gauntlet/tournament season. A caller can use the reconciliation output
to add/remove Discord roles without ever allowing an old seasonal winner to
survive into a new season.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

XP_LEVEL_ROLES = {
    5: "Bronze",
    10: "Silver",
    25: "Gold",
    50: "Platinum",
    75: "Champion",
    100: "Legend",
}
MEDIA_UNLOCK_LEVEL = 10

GAUNTLET_SEASONAL_ROLES = (
    "Division 1 Winner",
    "Division 2 Winner",
    "Division 3 Winner",
    "Division 4 Winner",
    "Division 5 Winner",
    "Division 6 Winner",
    "Top Active",
    "Top Wins",
    "Top Player",
    "Top Defender",
    "Top Challenger",
    "Most Improved",
    "Win Streak",
    "Season Champion",
)

TOURNAMENT_SEASONAL_ROLES = (
    "Tournament Champion",
    "Tournament Runner-Up",
    "Tournament 3rd Place",
    "Tournament Finalist",
    "Tournament MVP",
    "Top Tournament Wins",
    "Tournament Leader",
    "Tournament All-Star",
)

PERMANENT_ACHIEVEMENT_ROLES = (
    "Tournament Participant",
    "Tournament Veteran",
    "Perfect Tournament Run",
    "Grand Champion",
)

SEASONAL_ROLES = GAUNTLET_SEASONAL_ROLES + TOURNAMENT_SEASONAL_ROLES
MANAGED_ROLE_NAMES = tuple(dict.fromkeys(
    tuple(XP_LEVEL_ROLES.values()) + SEASONAL_ROLES + PERMANENT_ACHIEVEMENT_ROLES
))


def xp_rank(level: int) -> str | None:
    """Return the highest unlocked XP rank role, or None below level 5."""
    current = None
    for threshold, role in sorted(XP_LEVEL_ROLES.items()):
        if int(level) >= threshold:
            current = role
    return current


def media_unlocked(level: int) -> bool:
    """Players at level 10+ may post in RSL media channels."""
    return int(level) >= MEDIA_UNLOCK_LEVEL


def role_for_division(divisions: Mapping[int | str, Any]) -> dict[str, list[str]]:
    """Map division winners to their seasonal role names."""
    result: dict[str, list[str]] = {}
    for division in range(1, 7):
        winner = divisions.get(division, divisions.get(str(division)))
        if winner is not None:
            result[f"Division {division} Winner"] = [str(winner)]
    return result


def _top_users(records: Iterable[Mapping[str, Any]], metric: str) -> list[str]:
    rows = [r for r in records if r.get("user_id") is not None]
    if not rows:
        return []
    values = [int(r.get(metric, 0) or 0) for r in rows]
    best = max(values)
    if best <= 0:
        return []
    return sorted({
        str(r["user_id"]) for r in rows if int(r.get(metric, 0) or 0) == best
    })


def build_gauntlet_season_roles(
    *,
    division_winners: Mapping[int | str, Any],
    player_stats: Iterable[Mapping[str, Any]],
    champion_user_id: str | int | None = None,
    overall_activity_stats: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, list[str]]:
    """Build current-season Gauntlet role assignments.

    Ties receive the same statistical role rather than being resolved
    arbitrarily. Division winners and Season Champion are explicit inputs.
    """
    stats = list(player_stats)
    overall_activity = list(overall_activity_stats or ())
    result = role_for_division(division_winners)
    metrics = {
        "Top Active": "overall_activity_score",
        "Top Wins": "wins",
        "Top Player": "gauntlet_points",
        "Top Defender": "defense_wins",
        "Top Challenger": "challenge_wins",
        "Most Improved": "improvement",
        "Win Streak": "win_streak",
    }
    for role, metric in metrics.items():
        source = overall_activity if role == "Top Active" else stats
        users = _top_users(source, metric)
        if users:
            result[role] = users
    if champion_user_id is not None:
        result["Season Champion"] = [str(champion_user_id)]
    return result


def build_tournament_season_roles(
    *,
    tournament_champion: str | int | None = None,
    runner_up: str | int | None = None,
    third_place: str | int | None = None,
    finalists: Iterable[str | int] = (),
    mvp: str | int | None = None,
    player_stats: Iterable[Mapping[str, Any]] = (),
    leader_user_id: str | int | None = None,
    all_star_users: Iterable[str | int] = (),
) -> dict[str, list[str]]:
    """Build current-season tournament role assignments."""
    result: dict[str, list[str]] = {}

    def put(role: str, users: Iterable[str | int]) -> None:
        values = sorted({str(u) for u in users if u is not None})
        if values:
            result[role] = values

    put("Tournament Champion", [tournament_champion] if tournament_champion is not None else [])
    put("Tournament Runner-Up", [runner_up] if runner_up is not None else [])
    put("Tournament 3rd Place", [third_place] if third_place is not None else [])
    put("Tournament Finalist", finalists)
    put("Tournament MVP", [mvp] if mvp is not None else [])
    put("Top Tournament Wins", _top_users(player_stats, "tournament_wins"))
    put("Tournament Leader", [leader_user_id] if leader_user_id is not None else [])
    put("Tournament All-Star", all_star_users)
    return result


def reconcile_seasonal_roles(
    *,
    current_roles: Mapping[str | int, Iterable[str]],
    desired_roles: Mapping[str, Iterable[str]],
) -> dict[str, dict[str, list[str]]]:
    """Return exact seasonal add/remove operations for a season transition.

    Every managed seasonal role is considered authoritative for the new season.
    Therefore a role not present in desired_roles is removed from every player
    who currently has it.
    """
    normalized_current = {
        str(user_id): {str(role) for role in roles}
        for user_id, roles in current_roles.items()
    }
    desired = {
        str(role): {str(user_id) for user_id in users}
        for role, users in desired_roles.items()
    }

    all_users = set(normalized_current)
    for users in desired.values():
        all_users.update(users)

    changes: dict[str, dict[str, list[str]]] = {}
    for user_id in sorted(all_users):
        current = normalized_current.get(user_id, set())
        target = {role for role, users in desired.items() if user_id in users}
        target &= set(SEASONAL_ROLES)
        remove = sorted(current & set(SEASONAL_ROLES) - target)
        add = sorted(target - current)
        if add or remove:
            changes[user_id] = {"add": add, "remove": remove}
    return changes


def permanent_achievement_roles(
    *,
    tournament_participant: bool = False,
    tournament_veteran: bool = False,
    perfect_tournament_run: bool = False,
    grand_champion: bool = False,
) -> list[str]:
    """Return permanent tournament achievement roles earned by a player."""
    flags = {
        "Tournament Participant": tournament_participant,
        "Tournament Veteran": tournament_veteran,
        "Perfect Tournament Run": perfect_tournament_run,
        "Grand Champion": grand_champion,
    }
    return [role for role, earned in flags.items() if earned]
