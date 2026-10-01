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
    division_winners: dict[int | str, str],
    player_stats: list[dict],
    overall_activity_stats: list[dict],
    champion_user_id: str | int | None,
    role_names: dict[str, str] | None = None,
    role_ids: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Apply the exact current-season Gauntlet role assignment to Discord.

    Existing seasonal Gauntlet roles are authoritative and are removed before
    applying the new assignment. Failures are logged by the caller and never
    alter competitive standings or season settlement.
    """
    desired = build_gauntlet_season_roles(
        division_winners=division_winners,
        player_stats=player_stats,
        champion_user_id=champion_user_id,
        overall_activity_stats=overall_activity_stats,
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


async def sync_tournament_season_roles(
    guild: discord.Guild,
    *,
    tournament_champion: str | int | None,
    runner_up: str | int | None = None,
    third_place: str | int | None = None,
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
