"""Discord UI for purchasing non-bankable daily Gauntlet Tickets."""
from __future__ import annotations

import discord

from ..core.rsl_economy import purchase_daily_ticket


class BuyTicketView(discord.ui.View):
    def __init__(self, bot, guild_id: str, user_id: str, today_provider, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.today_provider = today_provider

    @discord.ui.button(label="Buy Extra Ticket", emoji="🎟️", style=discord.ButtonStyle.primary)
    async def buy_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id or str(interaction.guild_id) != self.guild_id:
            await interaction.response.send_message("❌ This ticket purchase belongs to another driver.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        today = await self.today_provider(self.guild_id)
        result = await purchase_daily_ticket(
            self.bot.db,
            guild_id=self.guild_id,
            user_id=self.user_id,
            today=today,
        )
        if result.get("ok"):
            await interaction.followup.send(
                f"🎟️ **Extra Ticket Purchased!**\n"
                f"Cost: **{result['cost']:,} RSL Coins**\n"
                f"Paid tickets today: **{result['purchased_tickets']}/5**\n"
                f"Tickets remaining: **{result['tickets_remaining']}/10**\n"
                f"Unused tickets expire at the next daily reset.",
                ephemeral=True,
            )
            return

        messages = {
            "profile_not_found": "❌ You need an RSL driver profile before buying tickets.",
            "purchase_limit": "⚠️ You have already purchased all 5 extra tickets for today.",
            "insufficient_coins": f"🪙 You do not have enough RSL Coins. Next ticket costs **{result.get('cost', 0):,}**.",
            "purchase_race_or_state_changed": "⚠️ Your ticket balance changed before the purchase completed. Please try again.",
        }
        await interaction.followup.send(messages.get(result.get("reason"), "⚠️ The ticket purchase could not be completed."), ephemeral=True)
