"""Bridge the staff dashboard's Server Setup action to the canonical picker wizard.

This keeps the dashboard UI in core.py intact while replacing the legacy setup
modal path at runtime. The old top-level /setup command is also removed from
the application command tree before the first sync.
"""
from __future__ import annotations

import logging

from discord.ext import commands

from ..core.core import StaffActionSelect, bot
from ..core.setup_wizard import launch_setup_wizard


class DashboardSetupBridgeCog(commands.Cog):
    """Route Staff → Server Setup to the picker-only setup wizard."""

    async def cog_load(self) -> None:
        original_callback = StaffActionSelect.callback

        async def bridged_callback(select, interaction):
            values = getattr(select, "values", None) or []
            if values and values[0] == "setup_direct":
                await launch_setup_wizard(interaction)
                return
            await original_callback(select, interaction)

        StaffActionSelect.callback = bridged_callback
        self._original_callback = original_callback

        # /setup is a legacy top-level alias. Remove it from the local tree so
        # the normal application-command sync removes it from Discord too.
        removed = bot.tree.remove_command("setup")
        if removed:
            logging.info("Removed legacy /setup application command; use Staff → Server Setup.")

    async def cog_unload(self) -> None:
        original = getattr(self, "_original_callback", None)
        if original is not None:
            StaffActionSelect.callback = original


async def setup(bot_instance):
    await bot_instance.add_cog(DashboardSetupBridgeCog(bot_instance))
