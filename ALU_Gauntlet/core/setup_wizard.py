from __future__ import annotations

import time
from typing import Any

import discord

from .core import (
    ASPHALT_THEME_COLOR,
    TIMEZONE_CHOICES,
    audit_admin_action,
    bot,
    check_admin_privileges,
    dispatch_audit_log,
    require_staff_interaction,
)

SETUP_FIELDS = (
    "registration_channel_id", "review_channel_id", "log_channel_id",
    "announcement_channel_id", "match_results_channel_id", "admin_role_id",
    "player_role_id", "timezone",
)
CHANNEL_FIELDS = (
    ("registration_channel_id", "Main / registration channel"),
    ("review_channel_id", "Staff review channel"),
    ("log_channel_id", "Log channel"),
    ("announcement_channel_id", "Announcement channel"),
    ("match_results_channel_id", "Match-results channel"),
)
ROLE_FIELDS = (("admin_role_id", "Staff / admin role"), ("player_role_id", "Player role"))

TOURNAMENT_CHANNEL_FIELDS = (
    ("tournament_main_channel_id", "Tournament main channel"),
    ("tournament_log_channel_id", "Tournament log channel"),
    ("tournament_bracket_channel_id", "Bracket / result channel"),
    ("tournament_admin_channel_id", "Tournament admin channel"),
    ("tournament_announcement_channel_id", "Tournament announcement channel"),
)
TOURNAMENT_ROLE_FIELDS = (
    ("tournament_admin_role_id", "Tournament admin role"),
    ("tournament_player_announcement_role_id", "Tournament player-announcement role"),
)
TOURNAMENT_FIELDS = tuple(key for key, _ in TOURNAMENT_CHANNEL_FIELDS + TOURNAMENT_ROLE_FIELDS)


class SetupWizard:
    """Guild-scoped state for the interactive, picker-only server setup wizard."""

    def __init__(self, interaction: discord.Interaction):
        self.guild_id = str(interaction.guild_id)
        self.owner_id = interaction.user.id
        self.values: dict[str, Any] = {"timezone": "UTC"}
        self.tournament_target = TOURNAMENT_CHANNEL_FIELDS[0][0]
        self.channel_target = CHANNEL_FIELDS[0][0]
        self.role_target = ROLE_FIELDS[0][0]

    def owns(self, interaction: discord.Interaction) -> bool:
        return str(interaction.guild_id) == self.guild_id and interaction.user.id == self.owner_id

    def guild(self) -> discord.Guild | None:
        return bot.get_guild(int(self.guild_id))

    def channel(self, key: str) -> discord.TextChannel | None:
        value = self.values.get(key)
        guild = self.guild()
        channel = guild.get_channel(int(value)) if guild and value else None
        return channel if isinstance(channel, discord.TextChannel) else None

    def role(self, key: str) -> discord.Role | None:
        value = self.values.get(key)
        guild = self.guild()
        return guild.get_role(int(value)) if guild and value else None

    def channel_count(self) -> int:
        return sum(1 for key, _ in CHANNEL_FIELDS if self.channel(key))

    def role_count(self) -> int:
        return sum(1 for key, _ in ROLE_FIELDS if self.role(key))

    def complete_count(self) -> int:
        return self.channel_count() + self.role_count() + int(bool(self.values.get("timezone")))


async def _authorized(interaction: discord.Interaction, wizard: SetupWizard) -> bool:
    if not wizard.owns(interaction):
        await interaction.response.send_message("❌ This setup panel belongs to another administrator.", ephemeral=True)
        return False
    return await require_staff_interaction(interaction)


class SetupWizardView(discord.ui.View):
    def __init__(self, wizard: SetupWizard):
        super().__init__(timeout=900)
        self.wizard = wizard
        self.channels.label = f"Channels ({wizard.channel_count()}/{len(CHANNEL_FIELDS)})"
        self.roles.label = f"Roles ({wizard.role_count()}/{len(ROLE_FIELDS)})"
        self.timezone.label = "Timezone ✓" if wizard.values.get("timezone") else "Timezone"
        self.tournament.label = "🏆 Tournament Setup"

    @discord.ui.button(label="Channels", style=discord.ButtonStyle.primary, row=0)
    async def channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(embed=build_channels_embed(self.wizard), view=SetupChannelsView(self.wizard))

    @discord.ui.button(label="Roles", style=discord.ButtonStyle.primary, row=0)
    async def roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(embed=build_roles_embed(self.wizard), view=SetupRolesView(self.wizard))

    @discord.ui.button(label="Timezone", style=discord.ButtonStyle.primary, row=0)
    async def timezone(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(embed=build_timezone_embed(self.wizard, 0), view=TimezoneWizardView(self.wizard, 0))

    @discord.ui.button(label="🏆 Tournament Setup", style=discord.ButtonStyle.primary, row=1)
    async def tournament(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(embed=build_tournament_embed(self.wizard), view=TournamentSetupView(self.wizard))

    @discord.ui.button(label="Review & Save", style=discord.ButtonStyle.success, row=2)
    async def review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _authorized(interaction, self.wizard):
            return
        missing = missing_setup_fields(self.wizard)
        if missing:
            await interaction.response.send_message("❌ Still needed: " + ", ".join(missing) + ".", ephemeral=True)
            return
        await interaction.response.edit_message(embed=build_review_embed(self.wizard), view=SetupReviewView(self.wizard))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(content="⚙️ Server setup cancelled.", embed=None, view=None)


class SetupChannelsView(discord.ui.View):
    """Choose a channel setting, then select the actual Discord channel with a native picker."""

    def __init__(self, wizard: SetupWizard):
        super().__init__(timeout=900)
        self.wizard = wizard
        self.target_select = discord.ui.Select(
            placeholder="1. Choose what this channel is for",
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    description="Configured" if wizard.channel(key) else "Not configured yet",
                    default=key == wizard.channel_target,
                )
                for key, label in CHANNEL_FIELDS
            ],
            row=0,
        )
        self.target_select.callback = self._target_changed
        self.add_item(self.target_select)
        self.channel_select = discord.ui.ChannelSelect(
            placeholder="2. Select a text channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1,
        )
        self.channel_select.callback = self._channel_changed
        self.add_item(self.channel_select)
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=2)
        back.callback = self._back
        self.add_item(back)

    async def _target_changed(self, interaction: discord.Interaction):
        if not await _authorized(interaction, self.wizard):
            return
        self.wizard.channel_target = self.target_select.values[0]
        await interaction.response.edit_message(embed=build_channels_embed(self.wizard), view=SetupChannelsView(self.wizard))

    async def _channel_changed(self, interaction: discord.Interaction):
        if not await _authorized(interaction, self.wizard):
            return
        channel = self.channel_select.values[0] if self.channel_select.values else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ Please select a text channel.", ephemeral=True)
            return
        guild = self.wizard.guild()
        me = guild.me if guild else None
        if me:
            permissions = channel.permissions_for(me)
            if not permissions.view_channel or not permissions.send_messages:
                await interaction.response.send_message(
                    "❌ I can't use that channel. Please choose a channel where the bot can **View Channel** and **Send Messages**.",
                    ephemeral=True,
                )
                return
        self.wizard.values[self.wizard.channel_target] = str(channel.id)
        await interaction.response.edit_message(embed=build_channels_embed(self.wizard), view=SetupChannelsView(self.wizard))

    async def _back(self, interaction: discord.Interaction):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(embed=build_main_embed(self.wizard), view=SetupWizardView(self.wizard))


class SetupRolesView(discord.ui.View):
    """Choose a role setting, then select the actual server role with a native picker."""

    def __init__(self, wizard: SetupWizard):
        super().__init__(timeout=900)
        self.wizard = wizard
        self.target_select = discord.ui.Select(
            placeholder="1. Choose what this role is for",
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    description="Configured" if wizard.role(key) else "Not configured yet",
                    default=key == wizard.role_target,
                )
                for key, label in ROLE_FIELDS
            ],
            row=0,
        )
        self.target_select.callback = self._target_changed
        self.add_item(self.target_select)
        self.role_select = discord.ui.RoleSelect(
            placeholder="2. Select a server role",
            min_values=1,
            max_values=1,
            row=1,
        )
        self.role_select.callback = self._role_changed
        self.add_item(self.role_select)
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=2)
        back.callback = self._back
        self.add_item(back)

    async def _target_changed(self, interaction: discord.Interaction):
        if not await _authorized(interaction, self.wizard):
            return
        self.wizard.role_target = self.target_select.values[0]
        await interaction.response.edit_message(embed=build_roles_embed(self.wizard), view=SetupRolesView(self.wizard))

    async def _role_changed(self, interaction: discord.Interaction):
        if not await _authorized(interaction, self.wizard):
            return
        role = self.role_select.values[0] if self.role_select.values else None
        if role is None or role.is_default() or role.managed:
            await interaction.response.send_message(
                "❌ Please select a normal server role, not @everyone or a managed role.",
                ephemeral=True,
            )
            return
        self.wizard.values[self.wizard.role_target] = str(role.id)
        await interaction.response.edit_message(embed=build_roles_embed(self.wizard), view=SetupRolesView(self.wizard))

    async def _back(self, interaction: discord.Interaction):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(embed=build_main_embed(self.wizard), view=SetupWizardView(self.wizard))



class TournamentSetupView(discord.ui.View):
    """Separate picker-based setup for tournament channels and roles."""

    def __init__(self, wizard: SetupWizard):
        super().__init__(timeout=900)
        self.wizard = wizard
        targets = TOURNAMENT_CHANNEL_FIELDS + TOURNAMENT_ROLE_FIELDS
        self.target_select = discord.ui.Select(
            placeholder="1. Choose a tournament setting",
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    description="Configured" if wizard.values.get(key) else "Not configured yet",
                    default=key == wizard.tournament_target,
                )
                for key, label in targets
            ],
            row=0,
        )
        self.target_select.callback = self._target_changed
        self.add_item(self.target_select)
        if wizard.tournament_target in {key for key, _ in TOURNAMENT_CHANNEL_FIELDS}:
            self.picker = discord.ui.ChannelSelect(
                placeholder="2. Select a text channel",
                channel_types=[discord.ChannelType.text],
                min_values=1, max_values=1, row=1,
            )
        else:
            self.picker = discord.ui.RoleSelect(
                placeholder="2. Select a tournament role",
                min_values=1, max_values=1, row=1,
            )
        self.picker.callback = self._picker_changed
        self.add_item(self.picker)
        back = discord.ui.Button(label="Back to Setup", style=discord.ButtonStyle.secondary, row=2)
        back.callback = self._back
        self.add_item(back)
        save = discord.ui.Button(label="Save Tournament Setup", style=discord.ButtonStyle.success, row=2)
        save.callback = self._save
        self.add_item(save)

    async def _target_changed(self, interaction: discord.Interaction):
        if not await _authorized(interaction, self.wizard):
            return
        self.wizard.tournament_target = self.target_select.values[0]
        await interaction.response.edit_message(
            embed=build_tournament_embed(self.wizard),
            view=TournamentSetupView(self.wizard),
        )

    async def _picker_changed(self, interaction: discord.Interaction):
        if not await _authorized(interaction, self.wizard):
            return
        key = self.wizard.tournament_target
        if key in {k for k, _ in TOURNAMENT_CHANNEL_FIELDS}:
            channel = self.picker.values[0] if self.picker.values else None
            if not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message("❌ Please select a text channel.", ephemeral=True)
                return
            guild = self.wizard.guild()
            me = guild.me if guild else None
            if me:
                permissions = channel.permissions_for(me)
                if not permissions.view_channel or not permissions.send_messages:
                    await interaction.response.send_message(
                        "❌ I can't use that channel. Choose one where the bot can View Channel and Send Messages.",
                        ephemeral=True,
                    )
                    return
            self.wizard.values[key] = str(channel.id)
        else:
            role = self.picker.values[0] if self.picker.values else None
            if role is None or role.is_default() or role.managed:
                await interaction.response.send_message(
                    "❌ Please select a normal server role, not @everyone or a managed role.",
                    ephemeral=True,
                )
                return
            self.wizard.values[key] = str(role.id)
        await interaction.response.edit_message(
            embed=build_tournament_embed(self.wizard),
            view=TournamentSetupView(self.wizard),
        )

    async def _back(self, interaction: discord.Interaction):
        if await _authorized(interaction, self.wizard):
            await interaction.response.edit_message(
                embed=build_main_embed(self.wizard), view=SetupWizardView(self.wizard)
            )

    async def _save(self, interaction: discord.Interaction):
        if not await _authorized(interaction, self.wizard):
            return
        missing = [
            label for key, label in TOURNAMENT_CHANNEL_FIELDS + TOURNAMENT_ROLE_FIELDS
            if not self.wizard.values.get(key)
        ]
        if missing:
            await interaction.response.send_message(
                "❌ Still needed: " + ", ".join(missing) + ".", ephemeral=True
            )
            return
        await interaction.response.defer()
        await bot.db.settings.update_one(
            {"_id": self.wizard.guild_id},
            {"$set": {key: self.wizard.values[key] for key in TOURNAMENT_FIELDS}},
            upsert=True,
        )
        await dispatch_audit_log(
            self.wizard.guild_id,
            "🏆 Tournament Setup Updated",
            f"Tournament channels and roles configured by {interaction.user.mention}.",
            color=ASPHALT_THEME_COLOR,
        )
        await interaction.edit_original_response(
            content="✅ Tournament setup saved. Your Gauntlet setup remains unchanged.",
            embed=None,
            view=None,
        )

class TimezoneWizardView(discord.ui.View):
    """Paged native dropdown because Discord select menus allow at most 25 options."""

    def __init__(self, wizard: SetupWizard, page: int):
        super().__init__(timeout=900)
        self.wizard = wizard
        self.page = max(0, min(page, max(0, (len(TIMEZONE_CHOICES) - 1) // 25)))
        chunk = TIMEZONE_CHOICES[self.page * 25:(self.page + 1) * 25]
        self.timezone_select = discord.ui.Select(
            placeholder="Select the server timezone",
            options=[
                discord.SelectOption(
                    label=label[:100],
                    value=value,
                    description="Current server timezone" if value == wizard.values.get("timezone") else None,
                    default=value == wizard.values.get("timezone"),
                )
                for label, value in chunk
            ],
            min_values=1,
            max_values=1,
            row=0,
        )
        self.timezone_select.callback = self._select
        self.add_item(self.timezone_select)
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)
        if self.page > 0:
            previous = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, row=1)
            previous.callback = self._previous
            self.add_item(previous)
        if (self.page + 1) * 25 < len(TIMEZONE_CHOICES):
            next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, row=1)
            next_button.callback = self._next
            self.add_item(next_button)

    async def _select(self, interaction: discord.Interaction):
        if not await _authorized(interaction, self.wizard):
            return
        self.wizard.values["timezone"] = self.timezone_select.values[0]
        await interaction.response.edit_message(embed=build_timezone_embed(self.wizard, self.page), view=TimezoneWizardView(self.wizard, self.page))

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
            await interaction.response.send_message("❌ Setup is incomplete: " + ", ".join(missing) + ".", ephemeral=True)
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
        await audit_admin_action(interaction, "Setup", "Updated the league channel, role, and timezone configuration using the picker-based setup wizard.")
        await interaction.edit_original_response(
            content="",
            embed=discord.Embed(
                title="✅ Server Setup Saved",
                description="All selected channels, roles, and timezone settings were saved for this Discord server.",
                color=ASPHALT_THEME_COLOR,
            ),
            view=None,
        )

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


def _status(value: Any) -> str:
    return "✅ Configured" if value else "⬜ Not configured"


def build_main_embed(wizard: SetupWizard) -> discord.Embed:
    complete = wizard.complete_count()
    total = len(SETUP_FIELDS)
    description = (
        "Set up the Gauntlet using **Discord's native pickers**.\n"
        "No channel IDs, role IDs, or timezone strings need to be entered manually.\n\n"
        f"**Progress:** {complete}/{total} configured\n\n"
        f"📺 **Channels:** {wizard.channel_count()}/{len(CHANNEL_FIELDS)}\n"
        f"🎭 **Roles:** {wizard.role_count()}/{len(ROLE_FIELDS)}\n"
        f"🌎 **Timezone:** {_status(wizard.values.get("timezone"))}\n\n"
        "🏆 **Tournament:** Configure tournament channels and roles with the Tournament Setup button.\n\n"
        "Nothing is saved until you choose **Review & Save**."
    )
    return discord.Embed(title="⚙️ Server Setup", description=description, color=ASPHALT_THEME_COLOR)


def build_channels_embed(wizard: SetupWizard) -> discord.Embed:
    lines = []
    for key, label in CHANNEL_FIELDS:
        channel = wizard.channel(key)
        marker = " ← editing" if key == wizard.channel_target else ""
        lines.append(f"**{label}:** {channel.mention if channel else 'Not selected'}{marker}")
    return discord.Embed(
        title="📺 Setup · Channels",
        description=(
            "Use the first dropdown to choose the channel's purpose, then use Discord's native channel picker.\n\n"
            + "\n".join(lines)
        ),
        color=ASPHALT_THEME_COLOR,
    )


def build_roles_embed(wizard: SetupWizard) -> discord.Embed:
    lines = []
    for key, label in ROLE_FIELDS:
        role = wizard.role(key)
        marker = " ← editing" if key == wizard.role_target else ""
        lines.append(f"**{label}:** {role.mention if role else 'Not selected'}{marker}")
    return discord.Embed(
        title="🎭 Setup · Roles",
        description=(
            "Use the first dropdown to choose the role's purpose, then use Discord's native role picker.\n\n"
            + "\n".join(lines)
        ),
        color=ASPHALT_THEME_COLOR,
    )


def build_tournament_embed(wizard: SetupWizard) -> discord.Embed:
    guild = wizard.guild()
    channel_keys = {key for key, _ in TOURNAMENT_CHANNEL_FIELDS}
    lines = ["Use the first dropdown to choose a purpose, then select the matching Discord channel or role."]
    for key, label in TOURNAMENT_CHANNEL_FIELDS + TOURNAMENT_ROLE_FIELDS:
        value = wizard.values.get(key)
        obj = None
        if guild and value:
            try:
                obj = guild.get_channel(int(value)) if key in channel_keys else guild.get_role(int(value))
            except (TypeError, ValueError):
                obj = None
        lines.append(f"**{label}:** {obj.mention if obj else 'Not selected'}")
    return discord.Embed(title="🏆 Tournament Setup", description="\n\n".join(lines), color=ASPHALT_THEME_COLOR)


def build_timezone_embed(wizard: SetupWizard, page: int) -> discord.Embed:
    total_pages = max(1, (len(TIMEZONE_CHOICES) + 24) // 25)
    current = wizard.values.get("timezone")
    label = next((name for name, value in TIMEZONE_CHOICES if value == current), None)
    current_text = label if label else "Not selected"
    return discord.Embed(
        title="🌎 Setup · Timezone",
        description=(
            f"**Current:** {current_text}\n\n"
            f"Select the server timezone from the native dropdown below. Page **{page + 1}/{total_pages}**."
        ),
        color=ASPHALT_THEME_COLOR,
    )


def build_review_embed(wizard: SetupWizard) -> discord.Embed:
    def channel(key: str) -> str:
        value = wizard.channel(key)
        return value.mention if value else "Not selected"

    def role(key: str) -> str:
        value = wizard.role(key)
        return value.mention if value else "Not selected"

    timezone = wizard.values.get("timezone")
    timezone_label = next((name for name, value in TIMEZONE_CHOICES if value == timezone), "Not selected")
    return discord.Embed(
        title="🔎 Review Server Setup",
        description=(
            "Everything below is shown by name/mention; no raw Discord IDs are exposed.\n\n"
            f"**Channels**\n"
            f"• Main: {channel('registration_channel_id')}\n"
            f"• Staff: {channel('review_channel_id')}\n"
            f"• Logs: {channel('log_channel_id')}\n"
            f"• Announcements: {channel('announcement_channel_id')}\n"
            f"• Match results: {channel('match_results_channel_id')}\n\n"
            f"**Roles**\n"
            f"• Admin/staff: {role('admin_role_id')}\n"
            f"• Player: {role('player_role_id')}\n\n"
            f"**Timezone**\n"
            f"• {timezone_label}\n\n"
            "Select **Save Setup** to apply these settings."
        ),
        color=ASPHALT_THEME_COLOR,
    )


async def launch_setup_wizard(interaction: discord.Interaction) -> bool:
    """Authorize and launch the guild-isolated picker-based setup panel."""
    if not interaction.guild:
        await interaction.response.send_message("❌ Server setup can only be used inside a Discord server.", ephemeral=True)
        return False
    if not interaction.user.guild_permissions.administrator and not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator or configured admin role required.", ephemeral=True)
        return False

    wizard = SetupWizard(interaction)
    existing = await bot.db.settings.find_one({"_id": wizard.guild_id})
    if existing:
        for key in SETUP_FIELDS + TOURNAMENT_FIELDS:
            if existing.get(key) is not None:
                wizard.values[key] = existing[key]

    await interaction.response.send_message(
        embed=build_main_embed(wizard),
        view=SetupWizardView(wizard),
        ephemeral=True,
    )
    return True
