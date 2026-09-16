"""Production Discord UI compatibility fixes.

These fixes are intentionally isolated from the large core module so they can be
regression-tested and deployed without duplicating the core implementation.
"""

from __future__ import annotations

import discord

from .core import (
    DashboardView,
    DefenseCarsModal,
    DefenseTimesModal,
    TopLeaderboardView,
    invoke_hidden_command,
)


class DefenseCarsLauncherView(discord.ui.View):
    """Bridge from the lap-times modal to the car modal.

    Discord does not allow a modal submission to respond with another modal.
    The first modal therefore posts this short-lived button view, and the
    button interaction opens the car modal as its own valid interaction.
    """

    def __init__(self, state: dict, owner_id: int | str):
        super().__init__(timeout=120)
        self.state = state
        self.owner_id = str(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.owner_id:
            await interaction.response.send_message(
                "❌ This defense setup belongs to another player.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Continue to Car Setup",
        style=discord.ButtonStyle.primary,
        emoji="🚗",
    )
    async def continue_to_cars(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_modal(DefenseCarsModal(self.state))


async def _defense_times_submit(
    self: DefenseTimesModal,
    interaction: discord.Interaction,
):
    self.state["laps"] = [
        field.value.strip()
        for field in (self.lap1, self.lap2, self.lap3, self.lap4, self.lap5)
    ]
    await interaction.response.send_message(
        "✅ Lap times saved. Click **Continue to Car Setup** to enter the five defense cars.",
        view=DefenseCarsLauncherView(self.state, interaction.user.id),
        ephemeral=True,
    )


_ORIGINAL_DASHBOARD_RUN_ACTION = DashboardView.run_action
_ORIGINAL_TOP_VIEW_INIT = TopLeaderboardView.__init__


async def _dashboard_run_action(self, interaction: discord.Interaction, action: str):
    """Add the missing dashboard registration route while preserving all others."""
    if action == "register":
        await invoke_hidden_command(interaction, "register")
        return
    await _ORIGINAL_DASHBOARD_RUN_ACTION(self, interaction, action)


def _patched_top_view_init(self: TopLeaderboardView):
    """Populate the legacy view callback's expected ``self.values`` field."""
    _ORIGINAL_TOP_VIEW_INIT(self)
    for item in self.children:
        if getattr(item, "custom_id", None) != "top_leaderboard_select":
            continue
        original = item.callback

        async def callback(
            interaction: discord.Interaction,
            *args,
            _item=item,
            _original=original,
            **kwargs,
        ):
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
    DashboardView.run_action = _dashboard_run_action
    TopLeaderboardView.__init__ = _patched_top_view_init
    _INSTALLED = True
