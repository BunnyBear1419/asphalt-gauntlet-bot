import os
import asyncio
import discord
from .core.core import bot
from .core.ui_fixes import install_ui_fixes
from .web.server import WebControlCenter

install_ui_fixes()

EXTENSIONS = [
    "ALU_Gauntlet.cogs.player", "ALU_Gauntlet.cogs.defense", "ALU_Gauntlet.cogs.challenges",
    "ALU_Gauntlet.cogs.competition", "ALU_Gauntlet.cogs.staff", "ALU_Gauntlet.cogs.season",
    "ALU_Gauntlet.cogs.administration", "ALU_Gauntlet.cogs.help", "ALU_Gauntlet.cogs.system",
    "ALU_Gauntlet.cogs.operations", "ALU_Gauntlet.cogs.dashboard_setup_bridge",
    "ALU_Gauntlet.cogs.tournament", "ALU_Gauntlet.cogs.asphalt_account",
]

async def _apply_rsl_identity():
    """Keep the live Discord bot identity aligned with the Racing Syndicate League brand."""
    if bot.user:
        try:
            if bot.user.name != "Racing Syndicate League":
                await bot.user.edit(username="Racing Syndicate League")
        except Exception:
            # Discord may rate-limit username changes; the bot remains fully operational.
            pass
        try:
            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Racing Syndicate League"))
        except Exception:
            pass


@bot.event
async def on_ready():
    await _apply_rsl_identity()

async def load_cogs():
    for extension in EXTENSIONS:
        await bot.load_extension(extension)

async def runner():
    await load_cogs()
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required in production")
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("WEB_PORT", "8080")))
    web_center = WebControlCenter(bot, host=host, port=port)
    await web_center.start()
    try:
        await bot.start(token)
    finally:
        await web_center.stop()

if __name__ == "__main__":
    asyncio.run(runner())
