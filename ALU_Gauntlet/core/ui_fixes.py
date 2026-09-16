"""Production Discord UI compatibility fixes.

Discord does not permit a modal submission to respond with another modal.
These adapters keep the existing defense workflow while inserting a normal
button interaction between each modal step.
"""

from __future__ import annotations

import random

import discord

from .core import (
    DashboardView,
    DefenseCarsModal,
    DefenseRanksModal,
    DefenseTimesModal,
    TopLeaderboardView,
    invoke_hidden_command,
)


_RANDOM_BUTTON_STYLES = (
    discord.ButtonStyle.primary,
    discord.ButtonStyle.secondary,
)
_ORIGINAL_VIEW_ADD_ITEM = discord.ui.View.add_item


class DefenseCarsLauncherView(discord.ui.View):
    """Open the car-entry modal from a normal component interaction."""

    def __init__(self, state: dict, owner_id: int | str):
        super().__init__(timeout=120)
        self.state = state
        self.owner_id = str(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.owner_id:
            await interaction.response.send_message(
                "❌ This defense setup belongs to another player.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Continue to Car Setup", style=discord.ButtonStyle.primary, emoji="🚗")
    async def continue_to_cars(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DefenseCarsModal(self.state))


class DefenseRanksLauncherView(discord.ui.View):
    """Open the rank-entry modal from a normal component interaction."""

    def __init__(self, state: dict, owner_id: int | str):
        super().__init__(timeout=120)
        self.state = state
        self.owner_id = str(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.owner_id:
            await interaction.response.send_message(
                "❌ This defense setup belongs to another player.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Continue to Rank Setup", style=discord.ButtonStyle.primary, emoji="🏆")
    async def continue_to_ranks(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DefenseRanksModal(self.state))


async def _defense_times_submit(self: DefenseTimesModal, interaction: discord.Interaction):
    self.state["laps"] = [field.value.strip() for field in self.children]
    await interaction.response.send_message(
        "✅ Lap times saved. Click **Continue to Car Setup** to enter the five defense cars.",
        view=DefenseCarsLauncherView(self.state, interaction.user.id), ephemeral=True
    )


async def _defense_cars_submit(self: DefenseCarsModal, interaction: discord.Interaction):
    self.state["cars"] = [field.value.strip() for field in self.children]
    await interaction.response.send_message(
        "✅ Defense cars saved. Click **Continue to Rank Setup** to enter the five ranks.",
        view=DefenseRanksLauncherView(self.state, interaction.user.id), ephemeral=True
    )


def _styled_view_add_item(self: discord.ui.View, item: discord.ui.Item):
    """Apply consistent button colors while reserving red/green for actions.

    Discord buttons use preset styles rather than arbitrary RGB colors.
    Cancel buttons are always red/danger, approve buttons are always green/
    success, and buttons left at the default secondary style are randomized
    between blue/primary and gray/secondary. Explicitly styled buttons remain
    unchanged unless their label is an action we reserve a color for.
    """
    if isinstance(item, discord.ui.Button):
        label = (item.label or "").strip().casefold()
        if "cancel" in label:
            item.style = discord.ButtonStyle.danger
        elif "approve" in label:
            item.style = discord.ButtonStyle.success
        elif item.style == discord.ButtonStyle.secondary:
            item.style = random.choice(_RANDOM_BUTTON_STYLES)
    return _ORIGINAL_VIEW_ADD_ITEM(self, item)


_ORIGINAL_DASHBOARD_RUN_ACTION = DashboardView.run_action
_ORIGINAL_TOP_VIEW_INIT = TopLeaderboardView.__init__


async def _dashboard_run_action(self, interaction: discord.Interaction, action: str):
    """Add the missing dashboard registration action while preserving others."""
    if action == "register":
        await invoke_hidden_command(interaction, "register")
        return
    await _ORIGINAL_DASHBOARD_RUN_ACTION(self, interaction, action)


def _patched_top_view_init(self: TopLeaderboardView):
    """Populate the legacy leaderboard callback's expected ``self.values`` field."""
    _ORIGINAL_TOP_VIEW_INIT(self)
    for item in self.children:
        if getattr(item, "custom_id", None) != "top_leaderboard_select":
            continue
        original = item.callback

        async def callback(interaction: discord.Interaction, *args, _item=item, _original=original, **kwargs):
            self.values = list(getattr(_item, "values", []))
            return await _original(interaction, *args, **kwargs)

        item.callback = callback
        break


_INSTALLED = False


def install_ui_fixes() -> None:
    """Install idempotent production UI compatibility fixes before bot start."""
    global _INSTALLED
    if _INSTALLED:
        return

    DefenseTimesModal.on_submit = _defense_times_submit
    DefenseCarsModal.on_submit = _defense_cars_submit
    DashboardView.run_action = _dashboard_run_action
    TopLeaderboardView.__init__ = _patched_top_view_init
    discord.ui.View.add_item = _styled_view_add_item
    _INSTALLED = True
