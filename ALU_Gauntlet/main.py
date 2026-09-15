import os
import asyncio
from .core.core import bot
EXTENSIONS = ["ALU_Gauntlet.cogs.player","ALU_Gauntlet.cogs.defense","ALU_Gauntlet.cogs.challenges","ALU_Gauntlet.cogs.competition","ALU_Gauntlet.cogs.staff","ALU_Gauntlet.cogs.season","ALU_Gauntlet.cogs.administration","ALU_Gauntlet.cogs.help","ALU_Gauntlet.cogs.system"]
async def load_cogs():
    for extension in EXTENSIONS: await bot.load_extension(extension)
async def runner():
    await load_cogs(); token=os.getenv("DISCORD_BOT_TOKEN")
    if not token: raise RuntimeError("DISCORD_BOT_TOKEN is required in production")
    await bot.start(token)
if __name__=="__main__": asyncio.run(runner())
