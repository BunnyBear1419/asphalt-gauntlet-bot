import os
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from ..core.core import *


class OperationsCog(commands.Cog):
    """Production observability and player statistics."""

    @app_commands.command(name="status", description="Show live ALU Gauntlet bot and league status.")
    @require_admin()
    async def status_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=True):
            return
        await interaction.response.defer(ephemeral=True)
        gid = str(interaction.guild_id)
        now = time.time()
        mongo_ok = False
        mongo_ms = None
        try:
            started = time.perf_counter()
            await bot.mongo_client.admin.command("ping")
            mongo_ms = round((time.perf_counter() - started) * 1000, 1)
            mongo_ok = True
        except Exception:
            pass

        state = await bot.db.season_state.find_one({"_id": f"guild_{gid}"}) if mongo_ok else None
        season = int(state.get("season_number", 1)) if state else 1
        registered = await bot.db.drivers.count_documents({"guild_id": gid, "season_registered": True, "season_number": season}) if mongo_ok else 0
        active = await bot.db.active_challenges.count_documents({"guild_id": gid, "status": {"$in": ["active", "processing"]}}) if mongo_ok else 0
        pending = await bot.db.pending.count_documents({"guild_id": gid, "season_number": season}) if mongo_ok else 0
        stale = await bot.db.active_challenges.count_documents({"guild_id": gid, "status": "processing", "processing_at": {"$lt": now - 900}}) if mongo_ok else 0

        def task_icon(obj):
            try:
                if obj and obj.is_running(): return "🟢"
                if obj and obj.failed(): return "🔴"
            except Exception:
                pass
            return "⚪"

        embed = discord.Embed(title="🛰️ ALU GAUNTLET — LIVE STATUS", color=ASPHALT_VICTORY_COLOR if mongo_ok and not stale else ASPHALT_ALERT_COLOR, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Bot", value=f"🟢 Online\n⏱️ Uptime: `{format_duration(int(now - bot.started_at))}`\n🏓 Gateway: `{round(bot.latency * 1000, 1) if bot.latency != float('inf') else 'N/A'}ms`", inline=True)
        embed.add_field(name="Database", value=(f"🟢 MongoDB `{mongo_ms}ms`" if mongo_ok else "🔴 MongoDB unavailable"), inline=True)
        embed.add_field(name="Season", value=f"🏁 Season `{season}`\n👥 Registered `{registered}`\n⏳ Pending `{pending}`\n⚡ Active challenges `{active}`", inline=True)
        embed.add_field(name="Background Tasks", value=f"Season clock {task_icon(getattr(bot, 'seasonal_clock_loop', None))}\nReminders {task_icon(getattr(bot, 'player_reminder_loop', None))}\nBackups {task_icon(getattr(bot, 'backup_loop', None))}\nHeartbeat {task_icon(getattr(bot, 'production_heartbeat_loop', None))}", inline=True)
        backup = getattr(bot, 'last_backup_at', None)
        backup_text = "Not recorded this process" if not backup else f"{max(0, (now-backup)/3600):.1f}h ago"
        heartbeat = getattr(bot, 'last_health_success_at', None)
        hb_text = "Webhook not configured" if not os.getenv("HEALTH_WEBHOOK_URL") else (f"{max(0, now-heartbeat):.0f}s ago" if heartbeat else "Awaiting first successful heartbeat")
        embed.add_field(name="Recovery Signals", value=f"💾 Last backup: `{backup_text}`\n💓 Last heartbeat: `{hb_text}`\n{'⚠️ Stale processing challenge detected' if stale else '🟢 No stale challenge reservations'}", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)




async def setup(bot):
    await bot.add_cog(OperationsCog(bot))
