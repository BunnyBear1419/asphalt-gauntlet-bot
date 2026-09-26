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
    "ALU_Gauntlet.cogs.tournament", "ALU_Gauntlet.cogs.notifications", "ALU_Gauntlet.cogs.activity_rewards", "ALU_Gauntlet.cogs.asphalt_account",
]


async def _ensure_database_indexes():
    """Enforce the uniqueness rules relied on by concurrent web/Discord writes."""
    db = getattr(bot, "db", None)
    if db is None:
        raise RuntimeError("MongoDB must be initialized before database indexes are created")

    await db.club_members.create_index(
        [("guild_id", 1), ("user_id", 1)],
        unique=True,
        name="uniq_club_membership_per_guild",
    )
    await db.clubs.create_index(
        [("guild_id", 1), ("name_ci", 1)],
        unique=True,
        name="uniq_club_name_per_guild",
    )
    await db.tournament_action_locks.create_index(
        [("tournament_id", 1), ("match_id", 1)],
        unique=True,
        name="uniq_tournament_action_lock",
    )
    # Active registrations must be unique even when two requests race between
    # the application-level existence check and the insert.
    await db.tournament_registrations.create_index(
        [("tournament_id", 1), ("user_id", 1)],
        unique=True,
        partialFilterExpression={"status": {"$in": ["pending", "accepted", "checked_in"]}},
        name="uniq_active_tournament_player_registration",
    )
    await db.tournament_club_registrations.create_index(
        [("tournament_id", 1), ("club_id", 1)],
        unique=True,
        partialFilterExpression={"status": {"$in": ["pending", "accepted", "checked_in"]}},
        name="uniq_active_tournament_club_registration",
    )
    await db.tournament_media.create_index(
        [("tournament_id", 1), ("status", 1), ("created_at", -1)],
        name="idx_tournament_media_gallery",
    )
    # Notification delivery identity is event + user + lead-time reminder.
    # The previous index used a missing "phase" field, which made the event-time
    # reminder collide with the scheduled lead reminder for the same user/event.
    try:
        await db.notification_deliveries.drop_index("uniq_notification_delivery")
    except Exception:
        pass
    await db.notification_deliveries.create_index(
        [("event_id", 1), ("user_id", 1), ("lead_days", 1)],
        unique=True,
        name="uniq_notification_delivery",
    )


async def _wait_for_database(timeout=60):
    """Wait for the bot's MongoDB connection to be initialized during startup."""
    deadline = asyncio.get_running_loop().time() + timeout
    while getattr(bot, "db", None) is None:
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError("MongoDB initialization timed out during startup")
        await asyncio.sleep(0.25)


async def _apply_rsl_identity():
    """Keep the live Discord bot identity aligned with the Racing Syndicate League brand."""
    if bot.user:
        try:
            if bot.user.name != "Racing Syndicate League":
                await bot.user.edit(username="Racing Syndicate League")
        except Exception:
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
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required in production")

    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("WEB_PORT", "8080")))
    web_center = WebControlCenter(bot, host=host, port=port)

    await web_center.start()

    # bot.start() runs discord.py's setup_hook first. setup_hook initializes
    # MongoDB, so database-dependent cogs must not be loaded until that work
    # has completed and bot.db is available.
    bot_task = asyncio.create_task(bot.start(token))
    try:
        await _wait_for_database()
        await load_cogs()
        await _ensure_database_indexes()
        await bot_task
    finally:
        if not bot_task.done():
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass
        await web_center.stop()


if __name__ == "__main__":
    asyncio.run(runner())
