"""Compatibility bridge for the staff dashboard's canonical Server Setup wizard."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from ..core.core import StaffDashboardView, bot
from ..core.setup_wizard import (
    SetupChannelsView,
    SetupRolesView,
    _authorized,
    build_channels_embed,
    build_roles_embed,
    launch_setup_wizard,
)


class DashboardSetupBridgeCog(commands.Cog):
    """Route Staff → Server Setup directly to the picker-only setup wizard."""

    async def cog_load(self) -> None:
        original_run_action = StaffDashboardView.run_action

        async def bridged_run_action(view, interaction, action):
            if action == "setup_direct":
                await launch_setup_wizard(interaction)
                return
            await original_run_action(view, interaction, action)

        StaffDashboardView.run_action = bridged_run_action
        self._original_run_action = original_run_action

        # discord.py resolves ChannelSelect values to AppCommandChannel/AppCommandThread,
        # not necessarily discord.TextChannel. Resolve the selected ID back through the guild
        # cache before validating/storing it.
        original_channel_changed = SetupChannelsView._channel_changed
        original_role_changed = SetupRolesView._role_changed

        async def fixed_channel_changed(view, interaction):
            if not await _authorized(interaction, view.wizard):
                return

            selected = view.channel_select.values[0] if view.channel_select.values else None
            raw_values = (interaction.data or {}).get("values", []) if interaction.data else []
            raw_id = raw_values[0] if raw_values else None
            channel_id = getattr(selected, "id", None) or raw_id

            guild = view.wizard.guild()
            channel = guild.get_channel(int(channel_id)) if guild and channel_id else None
            if not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message("❌ Please select a text channel.", ephemeral=True)
                return

            me = guild.me if guild else None
            if me:
                permissions = channel.permissions_for(me)
                if not permissions.view_channel or not permissions.send_messages:
                    await interaction.response.send_message(
                        "❌ I can't use that channel. Please choose a channel where the bot can **View Channel** and **Send Messages**.",
                        ephemeral=True,
                    )
                    return

            view.wizard.values[view.wizard.channel_target] = str(channel.id)
            await interaction.response.edit_message(
                embed=build_channels_embed(view.wizard),
                view=SetupChannelsView(view.wizard),
            )

        async def fixed_role_changed(view, interaction):
            if not await _authorized(interaction, view.wizard):
                return

            selected = view.role_select.values[0] if view.role_select.values else None
            raw_values = (interaction.data or {}).get("values", []) if interaction.data else []
            raw_id = raw_values[0] if raw_values else None
            role_id = getattr(selected, "id", None) or raw_id

            guild = view.wizard.guild()
            role = guild.get_role(int(role_id)) if guild and role_id else None
            if role is None or role.is_default() or role.managed:
                await interaction.response.send_message(
                    "❌ Please select a normal server role, not @everyone or a managed role.",
                    ephemeral=True,
                )
                return

            view.wizard.values[view.wizard.role_target] = str(role.id)
            await interaction.response.edit_message(
                embed=build_roles_embed(view.wizard),
                view=SetupRolesView(view.wizard),
            )

        SetupChannelsView._channel_changed = fixed_channel_changed
        SetupRolesView._role_changed = fixed_role_changed
        self._original_channel_changed = original_channel_changed
        self._original_role_changed = original_role_changed

        # /setup is a legacy top-level alias. Remove it from the local tree so
        # normal application-command sync removes it from Discord.
        removed = bot.tree.remove_command("setup")
        if removed:
            logging.info("Removed legacy /setup application command; use Staff → Server Setup.")

    async def cog_unload(self) -> None:
        original = getattr(self, "_original_run_action", None)
        if original is not None:
            StaffDashboardView.run_action = original
        original_channel = getattr(self, "_original_channel_changed", None)
        if original_channel is not None:
            SetupChannelsView._channel_changed = original_channel
        original_role = getattr(self, "_original_role_changed", None)
        if original_role is not None:
            SetupRolesView._role_changed = original_role


async def setup(bot_instance):
    await bot_instance.add_cog(DashboardSetupBridgeCog(bot_instance))
