"""Compatibility bridge for the staff dashboard's canonical Server Setup wizard."""
from __future__ import annotations

import logging

from discord.ext import commands

from ..core.core import StaffDashboardView, bot
from ..core.setup_wizard import launch_setup_wizard


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

        # /setup is a legacy top-level alias. Remove it from the local tree so
        # normal application-command sync removes it from Discord.
        removed = bot.tree.remove_command("setup")
        if removed:
            logging.info("Removed legacy /setup application command; use Staff → Server Setup.")

    async def cog_unload(self) -> None:
        original = getattr(self, "_original_run_action", None)
        if original is not None:
            StaffDashboardView.run_action = original


async def setup(bot_instance):
    await bot_instance.add_cog(DashboardSetupBridgeCog(bot_instance))
