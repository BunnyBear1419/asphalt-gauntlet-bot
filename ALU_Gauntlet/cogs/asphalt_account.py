import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..core.core import bot

log = logging.getLogger(__name__)


class AsphaltAccountCog(commands.Cog):
    """Discord-side review controls for Asphalt account connections."""

    async def verify(self, interaction: discord.Interaction, player: discord.Member, game_id: str):
        if not interaction.guild_id or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Staff administrator access is required.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        key = f"{guild_id}_{player.id}"
        prefs = await bot.db.web_preferences.find_one({"_id": key}) or {}
        connection = prefs.get("asphalt_connection") or {}
        submitted_id = str(connection.get("game_id") or "").strip()
        game_id = str(game_id).strip()[:100]
        if not submitted_id:
            await interaction.response.send_message("❌ That player has no pending Asphalt account connection.", ephemeral=True)
            return
        if submitted_id != game_id:
            await interaction.response.send_message("❌ The Game ID does not match the player's submitted connection.", ephemeral=True)
            return
        duplicate = await bot.db.web_preferences.find_one({
            "guild_id": guild_id,
            "asphalt_connection.game_id": game_id,
            "_id": {"$ne": key},
            "asphalt_connection.status": "verified",
        })
        if duplicate:
            await interaction.response.send_message("❌ That Asphalt Game ID is already verified to another Discord account.", ephemeral=True)
            return
        connection.update({
            "status": "verified",
            "verified_by": str(interaction.user.id),
            "verified_at": discord.utils.utcnow().isoformat(),
            "updated_at": discord.utils.utcnow().isoformat(),
        })
        try:
            await bot.db.web_preferences.update_one({"_id": key}, {"$set": {"asphalt_connection": connection}}, upsert=True)
            await bot.db.drivers.update_one({"_id": key}, {"$set": {
                "asphalt_verified": True,
                "asphalt_game_id": game_id,
                "asphalt_game_name": connection.get("game_name"),
                "asphalt_verified_by": str(interaction.user.id),
                "asphalt_verified_at": connection["verified_at"],
            }}, upsert=True)

            # Confirm both collections reached the same verified state before
            # reporting success. If either write did not persist correctly,
            # restore the previous values rather than leaving a split state.
            saved_prefs = await bot.db.web_preferences.find_one({"_id": key}) or {}
            saved_driver = await bot.db.drivers.find_one({"_id": key}) or {}
            saved_connection = saved_prefs.get("asphalt_connection") or {}
            if (
                saved_connection.get("status") != "verified"
                or str(saved_connection.get("game_id") or "").strip() != game_id
                or saved_driver.get("asphalt_verified") is not True
                or str(saved_driver.get("asphalt_game_id") or "").strip() != game_id
            ):
                raise RuntimeError("Asphalt verification synchronization check failed.")
        except Exception:
            try:
                await bot.db.web_preferences.update_one({"_id": key}, {"$set": {"asphalt_connection": prefs.get("asphalt_connection")}}, upsert=True)
            except Exception:
                log.exception("Failed to compensate partial Asphalt verification for %s", key)
            raise
        await interaction.response.send_message(f"✅ **{player.display_name}** is now linked to Asphalt Game ID **{game_id}**.", ephemeral=True)

    async def reject(self, interaction: discord.Interaction, player: discord.Member):
        if not interaction.guild_id or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Staff administrator access is required.", ephemeral=True)
            return
        key = f"{interaction.guild_id}_{player.id}"
        prefs = await bot.db.web_preferences.find_one({"_id": key}) or {}
        connection = prefs.get("asphalt_connection") or {}
        if not connection.get("game_id"):
            await interaction.response.send_message("❌ That player has no Asphalt account connection to reject.", ephemeral=True)
            return
        connection.update({"status": "rejected", "rejected_by": str(interaction.user.id), "rejected_at": discord.utils.utcnow().isoformat(), "updated_at": discord.utils.utcnow().isoformat()})
        try:
            await bot.db.web_preferences.update_one({"_id": key}, {"$set": {"asphalt_connection": connection}}, upsert=True)
            await bot.db.drivers.update_one({"_id": key}, {"$set": {
                "asphalt_verified": False,
                "asphalt_game_id": None,
                "asphalt_game_name": None,
                "asphalt_verified_by": None,
                "asphalt_verified_at": None,
            }}, upsert=True)
        except Exception:
            try:
                await bot.db.web_preferences.update_one({"_id": key}, {"$set": {"asphalt_connection": prefs.get("asphalt_connection")}}, upsert=True)
            except Exception:
                log.exception("Failed to compensate partial Asphalt rejection for %s", key)
            raise
        await interaction.response.send_message(f"🚫 Asphalt account link rejected for **{player.display_name}**.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AsphaltAccountCog(bot))
