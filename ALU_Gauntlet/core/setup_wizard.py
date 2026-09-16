from __future__ import annotations

import time
from typing import Any

import discord

from .core import (
    ASPHALT_ALERT_COLOR,
    ASPHALT_THEME_COLOR,
    TIMEZONE_CHOICES,
    audit_admin_action,
    bot,
    check_admin_privileges,
    dispatch_audit_log,
    require_staff_interaction,
)


SETUP_FIELDS = (
    "registration_channel_id",
    "review_channel_id",
    "log_channel_id",
    "announcement_channel_id",
    "match_results_channel_id",
    "admin_role_id",
    "player_role_id",
    "timezone",
)


class SetupWizard:
    """Guild-scoped state for the interactive server setup wizard."""

    def __init__(self, interaction: discord.Interaction):
        self.guild_id = str(interaction.guild_id)
        self.owner_id = interaction.user.id
        self.values: dict[str, Any] = {"timezone": "UTC"}

    def owns(self, interaction: discord.Interaction) -> bool:
        return str(interaction.guild_id) == self.guild_id and interaction.user.id == self.owner_id

    def channel(self, key: str) -> discord.TextChannel | None:
        value = self.values.get(key)
        return bot.get_channel(int(value)) if value else None

    def role(self, key: str) -> discord.Role | None:
        value = self.values.get(key)
        if not value or not bot.guilds:
            return None
        guild = next((g for g in bot.guilds if str(g.id) == self.guild_id), None)
        return guild.get_role(int(value)) if guild else None


async def _authorized(interaction: discord.Interaction, wizard: SetupWizard) -> bool:
    if not wizard.owns(interaction):
        await interaction.response.send_message("❌ This setup panel belongs to another administrator.", ephemeral=True)
        return False
    if not await require_staff_interaction(interaction):
        return False
    return True


class SetupWizardView(discord.ui.View):
    """Main setup popup. Each section opens native Discord selectors."""

    def __init__(self, wizard: SetupWizard):
        super().__init__(timeout=900)
        self.wizard = wizard

    @discord.ui.button(label="Channels", style=discord.ButtonStyle.primary, row=0)
    async def channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _authorized(interaction, self.wizard):
            return
        await interaction.response.edit_message(
            embed=build_channels_embed(self.wizard),
            view=SetupChannelsView(self.wizard),
        )

    @discord.ui.button(label="Roles", style=discord.ButtonStyle.primary, row=0)
    async def roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _authorized(interaction, self.wizard):
            return
        await interaction.response.edit_message(
            embed=build_roles_embed(self.wizard),
            view=SetupRolesView(self.wizard),
        )

    @discord.ui.button(label="Timezone", style=discord.ButtonStyle.primary, row=0)
    async def timezone(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _authorized(interaction, self.wizard):
            return
        await interaction.response.edit_message(
            embed=build_timezone_embed(self.wizard, 0),
            view=TimezoneWizardView(self.wizard, 0),
        )

    @discord.ui.button(label="Review & Save", style=discord.ButtonStyle.success, row=1)
    async def review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _authorized(interaction, self.wizard):
            return
        missing = missing_setup_fields(self.wizard)
        if missing:
            await interaction.response.send_message(
                "❌ Please complete: " + ", ".join(missing) + ".",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            embed=build_review_embed(self.wizard),
            view=SetupReviewView(self.wizard),
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _authorized(interaction, self.wizard):
            return
        await interaction.response.edit_message(content="⚙️ Server setup cancelled.", embed=None, view=None)


class SetupChannelsView(discord.ui.View):
    def __init__(self, wizard: SetupWizard):
        super().__init__(timeout=900)
        self.wizard = wizard

        self.registration = discord.ui.ChannelSelect(
            placeholder="Select the public player/registration channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0,
        )
        self.registration.callback = self._registration
        self.add_item(self.registration)

        self.review = discord.ui.ChannelSelect(
            placeholder="Select the private staff review channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1,
        )
        self.review.callback = self._review
        self.add_item(self.review)

        self.log = discord.ui.ChannelSelect(
            placeholder="Select the private log channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=2,
        )
        self.log.callback = self._log
        self.add_item(self.log)

        self.announcement = discord.ui.ChannelSelect(
            placeholder="Select the public announcements channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=3,
        )
        self.announcement.callback = self._announcement
        self.add_item(self.announcement)

        self.results = discord.ui.ChannelSelect(
            placeholder="Select the public match-results channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=4,
        )
        self.results.callback = self._results
        self.add_item(self.results)

        self.back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=4)
        self.back_button.callback = self._back
        self.remove_item(self.results)
        self.add_item(self.results)

    async def _set(self, interaction: discord.Interaction, key: str, values: list[discord.abc.GuildChannel]):
        if not await _authorized(interaction, self.wizard):
            return
        if not values or not isinstance(values[0], discord.TextChannel):
            await interaction.response.send_message("❌ Please select a text channel.", ephemeral=True)
            return
        self.wizard.values[key] = str(values[0].id)
        await interaction.response.defer()

    async def _registration(self, interaction: discord.Interaction):
        await self._set(interaction, "registration_channel_id", self.registration.values)

    async def _review(self, interaction: discord.Interaction):
        await self._set(interaction, "review_channel_id", self.review.values)

    async def _log(self, interaction: discord.Interaction):
        await self._set(interaction, "log_channel_id", self.log.values)

    async def _announcement(self, interaction: discord.Interaction):
        await self._set(interaction, "announcement_channel_id", self.announcement.values)

    async def _results(self, interaction: discord.Interaction):
        await self._set(interaction, "match_results_channel_id", self.results.values)

    async def _back(self, interaction: discord.Interaction):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(embed=build_main_embed(self.wizard), view=SetupWizardView(self.wizard))


class SetupRolesView(discord.ui.View):
    def __init__(self, wizard: SetupWizard):
        super().__init__(timeout=900)
        self.wizard = wizard

        self.admin = discord.ui.RoleSelect(
            placeholder="Select the staff/admin role",
            min_values=1,
            max_values=1,
            row=0,
        )
        self.admin.callback = self._admin
        self.add_item(self.admin)

        self.player = discord.ui.RoleSelect(
            placeholder="Select the player role",
            min_values=1,
            max_values=1,
            row=1,
        )
        self.player.callback = self._player
        self.add_item(self.player)

        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=2)
        back.callback = self._back
        self.add_item(back)

    async def _set(self, interaction: discord.Interaction, key: str, values: list[discord.Role]):
        if not await _authorized(interaction, self.wizard):
            return
        if not values:
            await interaction.response.send_message("❌ Please select a role.", ephemeral=True)
            return
        role = values[0]
        if role.is_default() or role.managed:
            await interaction.response.send_message("❌ Please select a normal server role, not @everyone or a managed role.", ephemeral=True)
            return
        self.wizard.values[key] = str(role.id)
        await interaction.response.defer()

    async def _admin(self, interaction: discord.Interaction):
        await self._set(interaction, "admin_role_id", self.admin.values)

    async def _player(self, interaction: discord.Interaction):
        await self._set(interaction, "player_role_id", self.player.values)

    async def _back(self, interaction: discord.Interaction):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(embed=build_main_embed(self.wizard), view=SetupWizardView(self.wizard))


class TimezoneWizardView(discord.ui.View):
    def __init__(self, wizard: SetupWizard, page: int):
        super().__init__(timeout=900)
        self.wizard = wizard
        self.page = page
        chunk = TIMEZONE_CHOICES[self.page * 25 : (self.page + 1) * 25]
        options = [discord.SelectOption(label=label[:100], value=value, default=value == wizard.values.get("timezone")) for label, value in chunk]
        select = discord.ui.Select(placeholder="Select the server timezone", options=options, min_values=1, max_values=1, row=0)
        select.callback = self._select
        self.add_item(select)

        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)
        if page > 0:
            prev = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, row=1)
            prev.callback = self._previous
            self.add_item(prev)
        if (page + 1) * 25 < len(TIMEZONE_CHOICES):
            nxt = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, row=1)
            nxt.callback = self._next
            self.add_item(nxt)

    async def _select(self, interaction: discord.Interaction):
        if not await _authorized(interaction, self.wizard):
            return
        select = next(item for item in self.children if isinstance(item, discord.ui.Select))
        self.wizard.values["timezone"] = select.values[0]
        await interaction.response.edit_message(embed=build_timezone_embed(self.wizard, self.page), view=self)

    async def _back(self, interaction: discord.Interaction):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(embed=build_main_embed(self.wizard), view=SetupWizardView(self.wizard))

    async def _previous(self, interaction: discord.Interaction):
        if await _authorized(interaction, self.wizard):
            page = max(0, self.page - 1)
            await interaction.response.edit_message(embed=build_timezone_embed(self.wizard, page), view=TimezoneWizardView(self.wizard, page))

    async def _next(self, interaction: discord.Interaction):
        if await _authorized(interaction, self.wizard):
            page = self.page + 1
            await interaction.response.edit_message(embed=build_timezone_embed(self.wizard, page), view=TimezoneWizardView(self.wizard, page))


class SetupReviewView(discord.ui.View):
    def __init__(self, wizard: SetupWizard):
        super().__init__(timeout=900)
        self.wizard = wizard

    @discord.ui.button(label="Save Setup", style=discord.ButtonStyle.success, row=0)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _authorized(interaction, self.wizard):
            return
        missing = missing_setup_fields(self.wizard)
        if missing:
            await interaction.response.send_message("❌ Setup is incomplete: " + ", ".join(missing), ephemeral=True)
            return
        await interaction.response.defer()
        guild_id = self.wizard.guild_id
        await bot.db.settings.update_one(
            {"_id": guild_id},
            {"$set": {key: self.wizard.values[key] for key in SETUP_FIELDS}, "$setOnInsert": {"automatic_season_end": False}},
            upsert=True,
        )
        guild_state = await bot.db.season_state.find_one({"_id": f"guild_{guild_id}"})
        if not guild_state:
            legacy_state = await bot.db.season_state.find_one({"_id": "current_season"})
            await bot.db.season_state.update_one(
                {"_id": f"guild_{guild_id}"},
                {"$setOnInsert": {
                    "guild_id": guild_id,
                    "season_number": int(legacy_state.get("season_number", 1)) if legacy_state else 1,
                    "ends_at": float(legacy_state.get("ends_at", time.time() + 14 * 24 * 60 * 60)) if legacy_state else time.time() + 14 * 24 * 60 * 60,
                }},
                upsert=True,
            )
        await dispatch_audit_log(guild_id, "⚙️ Master Setup Initialized", f"Interactive server setup completed by authority {interaction.user.mention}.", color=ASPHALT_THEME_COLOR)
        await audit_admin_action(interaction, "Setup", "Updated the league channel, role, and timezone configuration using the setup wizard.")
        await interaction.edit_original_response(content="", embed=discord.Embed(title="✅ Server Setup Saved", description="All selected channels, roles, and timezone settings were saved for this Discord server.", color=ASPHALT_THEME_COLOR), view=None)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(embed=build_main_embed(self.wizard), view=SetupWizardView(self.wizard))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(content="⚙️ Server setup cancelled.", embed=None, view=None)


def missing_setup_fields(wizard: SetupWizard) -> list[str]:
    labels = {
        "registration_channel_id": "main channel",
        "review_channel_id": "staff review channel",
        "log_channel_id": "log channel",
        "announcement_channel_id": "announcement channel",
        "match_results_channel_id": "match-results channel",
        "admin_role_id": "admin role",
        "player_role_id": "player role",
        "timezone": "timezone",
    }
    return [label for key, label in labels.items() if not wizard.values.get(key)]


def build_main_embed(wizard: SetupWizard) -> discord.Embed:
    return discord.Embed(
        title="⚙️ Server Setup",
        description=(
            "Choose a section below to configure this server.\n\n"
            "**Channels** — select every league channel from Discord's channel picker.\n"
            "**Roles** — select the staff/admin and player roles.\n"
            "**Timezone** — select the server timezone, with paging when needed.\n\n"
            "Nothing is saved until you press **Review & Save**."
        ),
        color=ASPHALT_THEME_COLOR,
    )


def build_channels_embed(wizard: SetupWizard) -> discord.Embed:
    labels = [
        ("Main", "registration_channel_id"),
        ("Staff review", "review_channel_id"),
        ("Logs", "log_channel_id"),
        ("Announcements", "announcement_channel_id"),
        ("Match results", "match_results_channel_id"),
    ]
    lines = []
    for label, key in labels:
        channel = wizard.channel(key)
        lines.append(f"**{label}:** {channel.mention if channel else 'Not selected'}")
    return discord.Embed(title="📺 Setup · Channels", description="Select each channel below.\n\n" + "\n".join(lines), color=ASPHALT_THEME_COLOR)


def build_roles_embed(wizard: SetupWizard) -> discord.Embed:
    admin = wizard.role("admin_role_id")
    player = wizard.role("player_role_id")
    return discord.Embed(title="🎭 Setup · Roles", description=f"Select the roles below.\n\n**Admin/staff:** {admin.mention if admin else 'Not selected'}\n**Player:** {player.mention if player else 'Not selected'}", color=ASPHALT_THEME_COLOR)


def build_timezone_embed(wizard: SetupWizard, page: int) -> discord.Embed:
    total_pages = max(1, (len(TIMEZONE_CHOICES) + 24) // 25)
    current = wizard.values.get("timezone", "UTC")
    label = next((name for name, value in TIMEZONE_CHOICES if value == current), current)
    return discord.Embed(title="🌎 Setup · Timezone", description=f"**Current:** `{label}` (`{current}`)\n\nSelect a timezone below. Page **{page + 1}/{total_pages}**.", color=ASPHALT_THEME_COLOR)


def build_review_embed(wizard: SetupWizard) -> discord.Embed:
    def mention_channel(key: str) -> str:
        channel = wizard.channel(key)
        return channel.mention if channel else "Not selected"

    def mention_role(key: str) -> str:
        role = wizard.role(key)
        return role.mention if role else "Not selected"

    timezone = wizard.values.get("timezone", "UTC")
    timezone_label = next((name for name, value in TIMEZONE_CHOICES if value == timezone), timezone)
    description = (
        "Review the configuration before saving it.\n\n"
        f"**Channels**\n• Main: {mention_channel('registration_channel_id')}\n• Staff: {mention_channel('review_channel_id')}\n• Logs: {mention_channel('log_channel_id')}\n• Announcements: {mention_channel('announcement_channel_id')}\n• Match results: {mention_channel('match_results_channel_id')}\n\n"
        f"**Roles**\n• Admin/staff: {mention_role('admin_role_id')}\n• Player: {mention_role('player_role_id')}\n\n"
        f"**Timezone**\n• {timezone_label} (`{timezone}`)"
    )
    return discord.Embed(title="🔎 Review Server Setup", description=description, color=ASPHALT_THEME_COLOR)


async def launch_setup_wizard(interaction: discord.Interaction) -> bool:
    """Authorize and launch the guild-isolated setup selector panel."""
    if not interaction.guild:
        await interaction.response.send_message("❌ Server setup can only be used inside a Discord server.", ephemeral=True)
        return False
    if not interaction.user.guild_permissions.administrator and not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator or configured admin role required.", ephemeral=True)
        return False
    wizard = SetupWizard(interaction)
    existing = await bot.db.settings.find_one({"_id": wizard.guild_id})
    if existing:
        for key in SETUP_FIELDS:
            if existing.get(key) is not None:
                wizard.values[key] = existing[key]
    await interaction.response.send_message(embed=build_main_embed(wizard), view=SetupWizardView(wizard), ephemeral=True)
    return True
