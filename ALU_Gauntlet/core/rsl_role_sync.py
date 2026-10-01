"""Discord-side application of the RSL seasonal role policy."""
from __future__ import annotations

from typing import Iterable
import logging

import discord

log = logging.getLogger(__name__)

from .rsl_roles import (
    GAUNTLET_SEASONAL_ROLES,
    TOURNAMENT_SEASONAL_ROLES,
    XP_LEVEL_ROLES,
    build_gauntlet_season_roles,
    build_tournament_season_roles,
    PERMANENT_ACHIEVEMENT_ROLES,
)


async def _ensure_roles(guild: discord.Guild, names: Iterable[str], role_names: dict[str, str] | None = None, role_ids: dict[str, str] | None = None) -> dict[str, discord.Role]:
    role_names = role_names or {}
    role_ids = role_ids or {}
    roles = {role.name: role for role in guild.roles}
    result = {}
    for name in names:
        role = None
        configured_id = str(role_ids.get(name) or "")
        if configured_id:
            try:
                role = guild.get_role(int(configured_id))
            except (TypeError, ValueError):
                role = None
        display_name = str(role_names.get(name) or name).strip() or name
        if role is None:
            role = roles.get(display_name) or roles.get(name)
        if role is None:
            try:
                role = await guild.create_role(name=display_name, reason="RSL managed progression role")
            except Exception:
                log.exception("Failed to create managed RSL role %s in guild %s", display_name, guild.id)
                continue
        elif role.name != display_name:
            try:
                await role.edit(name=display_name, reason="RSL achievement role name update")
            except Exception:
                log.exception("Failed to rename managed RSL role %s in guild %s", name, guild.id)
        result[name] = role
    return result


async def sync_gauntlet_season_roles(
    guild: discord.Guild,
    *,
    division_winners: dict[int | str, str] | None = None,
    player_stats: list[dict] | None = None,
    overall_activity_stats: list[dict] | None = None,
    champion_user_id: str | int | None = None,
    desired_roles: dict[str, Iterable[str]] | None = None,
    role_names: dict[str, str] | None = None,
    role_ids: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Apply the exact current-season Gauntlet role assignment to Discord.

    Existing seasonal Gauntlet roles are authoritative and are removed before
    applying the new assignment. Failures are logged by the caller and never
    alter competitive standings or season settlement.
    """
    desired = (
        {
            str(role): sorted({str(user_id) for user_id in users if user_id is not None})
            for role, users in (desired_roles or {}).items()
            if str(role) in GAUNTLET_SEASONAL_ROLES
        }
        if desired_roles is not None
        else build_gauntlet_season_roles(
            division_winners=division_winners or {},
            player_stats=player_stats or [],
            champion_user_id=champion_user_id,
            overall_activity_stats=overall_activity_stats or [],
        )
    )
    managed = await _ensure_roles(guild, GAUNTLET_SEASONAL_ROLES, role_names, role_ids)
    desired_by_user = {
        str(user_id): set(roles)
        for user_id, roles in {}
    }
    for role_name, users in desired.items():
        for user_id in users:
            desired_by_user.setdefault(str(user_id), set()).add(role_name)

    for member in guild.members:
        existing_ids = {role.id for role in member.roles}
        removals = [
            managed[name]
            for name in GAUNTLET_SEASONAL_ROLES
            if name in managed
            and managed[name].id in existing_ids
            and name not in desired_by_user.get(str(member.id), set())
        ]
        additions = [
            managed[name]
            for name in desired_by_user.get(str(member.id), set())
            if name in managed and managed[name].id not in existing_ids
        ]
        if removals:
            try:
                await member.remove_roles(*removals, reason="RSL season role rotation")
            except Exception:
                log.exception("Failed to remove seasonal RSL roles from member %s in guild %s", member.id, guild.id)
        if additions:
            try:
                await member.add_roles(*additions, reason="RSL season role assignment")
            except Exception:
                log.exception("Failed to add seasonal RSL roles to member %s in guild %s", member.id, guild.id)
    return desired


async def reconcile_gauntlet_season_roles(
    db,
    guild: discord.Guild,
    *,
    role_names: dict[str, str] | None = None,
    role_ids: dict[str, str] | None = None,
) -> int:
    """Durably re-apply the latest completed-season Gauntlet role snapshot."""
    state = await db.season_state.find_one({"_id": f"guild_{guild.id}"}) or {}
    snapshot = state.get("gauntlet_role_snapshot")
    if not isinstance(snapshot, dict):
        return 0
    desired = {
        str(role): sorted({str(uid) for uid in users if uid is not None})
        for role, users in snapshot.items()
        if str(role) in GAUNTLET_SEASONAL_ROLES
    }
    if not desired:
        return 0
    await sync_gauntlet_season_roles(
        guild,
        desired_roles=desired,
        role_names=role_names,
        role_ids=role_ids,
    )
    return 1


async def sync_tournament_season_roles(
    guild: discord.Guild,
    *,
    tournament_champion: str | int | Iterable[str | int] | None,
    runner_up: str | int | Iterable[str | int] | None = None,
    third_place: str | int | Iterable[str | int] | None = None,
    finalists: Iterable[str | int] = (),
    role_names: dict[str, str] | None = None,
    role_ids: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Apply the current tournament-season recognition roles.

    Tournament completion is authoritative: seasonal tournament roles are
    reconciled from the newly completed event so an older champion/runner-up
    cannot retain a stale seasonal role after a replacement event completes.
    """
    desired = build_tournament_season_roles(
        tournament_champion=tournament_champion,
        runner_up=runner_up,
        third_place=third_place,
        finalists=finalists,
    )
    managed = await _ensure_roles(guild, TOURNAMENT_SEASONAL_ROLES, role_names, role_ids)
    desired_by_user: dict[str, set[str]] = {}
    for role_name, users in desired.items():
        for user_id in users:
            desired_by_user.setdefault(str(user_id), set()).add(role_name)

    for member in guild.members:
        existing_ids = {role.id for role in member.roles}
        removals = [
            managed[name]
            for name in TOURNAMENT_SEASONAL_ROLES
            if name in managed
            and managed[name].id in existing_ids
            and name not in desired_by_user.get(str(member.id), set())
        ]
        additions = [
            managed[name]
            for name in desired_by_user.get(str(member.id), set())
            if name in managed and managed[name].id not in existing_ids
        ]
        if removals:
            try:
                await member.remove_roles(*removals, reason="RSL tournament role rotation")
            except Exception:
                log.exception("Failed to remove tournament seasonal roles from member %s in guild %s", member.id, guild.id)
        if additions:
            try:
                await member.add_roles(*additions, reason="RSL tournament role assignment")
            except Exception:
                log.exception("Failed to add tournament seasonal roles to member %s in guild %s", member.id, guild.id)
    return desired


async def sync_tournament_achievement_roles(
    guild: discord.Guild,
    *,
    achievements: dict[str, Iterable[str]] | None = None,
    role_names: dict[str, str] | None = None,
    role_ids: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Add permanent tournament achievement roles without seasonal removals.

    Permanent roles are additive and idempotent. A failed Discord assignment is
    logged but never removes an existing achievement, so a later completion or
    reconciliation can safely retry it.
    """
    desired = {
        str(role): sorted({str(user_id) for user_id in users if user_id is not None})
        for role, users in (achievements or {}).items()
        if str(role) in PERMANENT_ACHIEVEMENT_ROLES
    }
    managed = await _ensure_roles(guild, PERMANENT_ACHIEVEMENT_ROLES, role_names, role_ids)
    for role_name, users in desired.items():
        role = managed.get(role_name)
        if role is None:
            continue
        for user_id in users:
            member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
            if member is None:
                continue
            if role.id in {existing.id for existing in member.roles}:
                continue
            try:
                await member.add_roles(role, reason="RSL permanent tournament achievement")
            except Exception:
                log.exception(
                    "Failed to add permanent tournament achievement %s to member %s in guild %s",
                    role_name, member.id, guild.id,
                )
    return desired


async def reconcile_completed_tournament_achievement_roles(
    db,
    guild: discord.Guild,
    *,
    role_names: dict[str, str] | None = None,
    role_ids: dict[str, str] | None = None,
) -> int:
    """Recover permanent tournament achievements from completed events.

    MongoDB tournament records remain authoritative if Discord role assignment
    failed during completion. Re-running this reconciliation is idempotent and
    only adds permanent roles; it never removes them.
    """
    reconciled = 0
    cursor = db.tournaments.find({"guild_id": str(guild.id), "status": "completed"})
    async for tournament in cursor:
        tournament_id = str(tournament.get("_id") or "")
        if not tournament_id:
            continue

        participants: set[str] = set()
        team_size = int(tournament.get("team_size", 1) or 1)
        if team_size > 1:
            regs = db.tournament_club_registrations.find({
                "tournament_id": tournament_id,
                "status": {"$in": ["accepted", "checked_in"]},
            })
            async for reg in regs:
                participants.update(str(uid) for uid in (reg.get("lineup") or []) if uid)
        else:
            regs = db.tournament_registrations.find({
                "tournament_id": tournament_id,
                "status": {"$in": ["accepted", "checked_in"]},
            })
            async for reg in regs:
                uid = reg.get("user_id")
                if uid:
                    participants.add(str(uid))

        try:
            from .rsl_tournament_rewards import settle_tournament_rewards
            await settle_tournament_rewards(db, tournament)
        except Exception:
            log.exception("Failed to recover tournament rewards for %s", tournament_id)

        achievements: dict[str, set[str]] = {}
        if participants:
            achievements["Tournament Participant"] = participants

        standings = tournament.get("standings") or []
        champion_id = str(tournament.get("champion_id") or "")
        champion_row = next(
            (row for row in standings if str(row.get("entrant_id") or "") == champion_id),
            None,
        )
        if champion_row is not None and int(champion_row.get("losses", 0) or 0) == 0:
            perfect: set[str] = set()
            if team_size > 1:
                regs = db.tournament_club_registrations.find({
                    "tournament_id": tournament_id,
                    "status": {"$in": ["accepted", "checked_in"]},
                    "club_id": champion_id,
                })
                async for reg in regs:
                    perfect.update(str(uid) for uid in (reg.get("lineup") or []) if uid)
            elif champion_id:
                perfect.add(champion_id)
            if perfect:
                achievements["Perfect Tournament Run"] = perfect

        if achievements:
            await sync_tournament_achievement_roles(
                guild,
                achievements=achievements,
                role_names=role_names,
                role_ids=role_ids,
            )
            reconciled += 1
    return reconciled

async def clear_gauntlet_season_roles(guild: discord.Guild, role_names: dict[str, str] | None = None, role_ids: dict[str, str] | None = None) -> None:
    """Remove managed Gauntlet seasonal roles when a new season opens."""
    managed = await _ensure_roles(guild, GAUNTLET_SEASONAL_ROLES, role_names, role_ids)
    for member in guild.members:
        existing_ids = {role.id for role in member.roles}
        removals = [
            managed[name]
            for name in GAUNTLET_SEASONAL_ROLES
            if name in managed and managed[name].id in existing_ids
        ]
        if removals:
            try:
                await member.remove_roles(*removals, reason="RSL new-season role reset")
            except Exception:
                log.exception("Failed to reset seasonal RSL roles for member %s in guild %s", member.id, guild.id)


async def sync_xp_rank_role(member: discord.Member, level: int, role_names: dict[str, str] | None = None, role_ids: dict[str, str] | None = None) -> str | None:
    """Keep exactly the highest unlocked permanent XP role on a member."""
    current = None
    for threshold, role_name in sorted(XP_LEVEL_ROLES.items()):
        if int(level) >= threshold:
            current = role_name
    managed = await _ensure_roles(member.guild, XP_LEVEL_ROLES.values(), role_names, role_ids)
    existing_ids = {role.id for role in member.roles}
    removals = [
        role
        for name, role in managed.items()
        if role.id in existing_ids and name != current
    ]
    additions = [
        managed[current]
    ] if current and current in managed and managed[current].id not in existing_ids else []
    if removals:
        try:
            await member.remove_roles(*removals, reason="RSL XP rank progression")
        except Exception:
            log.exception("Failed to remove XP rank roles from member %s in guild %s", member.id, member.guild.id)
    if additions:
        try:
            await member.add_roles(*additions, reason="RSL XP rank progression")
        except Exception:
            log.exception("Failed to add XP rank role to member %s in guild %s", member.id, member.guild.id)
    return current
