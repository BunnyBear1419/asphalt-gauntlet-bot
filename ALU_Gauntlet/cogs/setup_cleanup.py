import logging

from discord.ext import commands

from ..core.core import bot


class SetupCommandCleanupCog(commands.Cog):
    """Remove stale guild-scoped /setup commands from Discord itself."""

    @commands.Cog.listener()
    async def on_ready(self):
        if getattr(bot, "_setup_command_cleanup_done", False):
            return

        failed = 0
        removed = 0
        for guild in list(getattr(bot, "guilds", [])):
            try:
                commands_in_guild = await bot.tree.fetch_commands(guild=guild)
                for command in commands_in_guild:
                    if command.name != "setup":
                        continue
                    # ApplicationCommand.delete() performs the actual Discord
                    # REST DELETE for the guild-scoped command.
                    await command.delete()
                    removed += 1
                    logging.info(
                        "Deleted stale guild-scoped /setup command %s from guild %s",
                        command.id,
                        guild.id,
                    )
            except Exception:
                failed += 1
                logging.exception(
                    "Failed to clean guild-scoped /setup command in guild %s",
                    guild.id,
                )

        bot._setup_command_cleanup_done = failed == 0
        logging.info(
            "Guild /setup cleanup complete: removed=%d failed=%d",
            removed,
            failed,
        )


async def setup(bot_instance):
    await bot_instance.add_cog(SetupCommandCleanupCog(bot_instance))
