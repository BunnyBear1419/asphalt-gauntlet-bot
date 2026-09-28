"""Discord-side application of the RSL seasonal role policy."""
from __future__ import annotations

from typing import Iterable

import discord

from .rsl_roles import (
    GAUNTLET_SEASONAL_ROLES,
    XP_LEVEL_ROLES,
    build_gauntlet_season_roles,
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
                continue
        elif role.name != display_name:
            try:
                await role.edit(name=display_name, reason="RSL achievement role name update")
            except Exception:
                pass
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
                pass
        if additions:
            try:
                await member.add_roles(*additions, reason="RSL season role assignment")
            except Exception:
                pass
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
                pass


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
            pass
    if additions:
        try:
            await member.add_roles(*additions, reason="RSL XP rank progression")
        except Exception:
            pass
    return current
