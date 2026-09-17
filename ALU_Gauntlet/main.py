import os
import asyncio
from .core.core import bot
from .core.ui_fixes import install_ui_fixes
from .web import WebControlCenter

install_ui_fixes()

EXTENSIONS = [
    "ALU_Gauntlet.cogs.player", "ALU_Gauntlet.cogs.defense", "ALU_Gauntlet.cogs.challenges",
    "ALU_Gauntlet.cogs.competition", "ALU_Gauntlet.cogs.staff", "ALU_Gauntlet.cogs.season",
    "ALU_Gauntlet.cogs.administration", "ALU_Gauntlet.cogs.help", "ALU_Gauntlet.cogs.system",
    "ALU_Gauntlet.cogs.operations", "ALU_Gauntlet.cogs.dashboard_setup_bridge",
]

async def load_cogs():
    for extension in EXTENSIONS:
        await bot.load_extension(extension)

async def runner():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required in production")

    host = "0.0.0.0"
    # Discloud TYPE=site routes public traffic to port 8080.
    port = 8080
    web_control_center = WebControlCenter(bot, host=host, port=port)

    # Start HTTP first so Discloud can reach /health immediately while the
    # Discord extensions and gateway are initializing.
    await web_control_center.start()
    try:
        await load_cogs()
        await bot.start(token)
    finally:
        await web_control_center.stop()

if __name__ == "__main__":
    asyncio.run(runner())
