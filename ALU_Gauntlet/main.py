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
    "ALU_Gauntlet.cogs.tournament", "ALU_Gauntlet.cogs.notifications", "ALU_Gauntlet.cogs.activity_rewards", "ALU_Gauntlet.cogs.rsl_xp", "ALU_Gauntlet.cogs.economy_moderation", "ALU_Gauntlet.cogs.asphalt_account",
    "ALU_Gauntlet.cogs.translation", "ALU_Gauntlet.cogs.match_assistant", "ALU_Gauntlet.cogs.tickets",
]


async def _ensure_database_indexes():
    """Enforce the uniqueness rules relied on by concurrent web/Discord writes."""
    db = getattr(bot, "db", None)
    if db is None:
        raise RuntimeError("MongoDB must be initialized before database indexes are created")

    await db.rsl_activity_events.create_index(
        [("guild_id", 1), ("user_id", 1), ("activity_type", 1), ("event_id", 1)],
        unique=True,
        name="uniq_rsl_activity_event",
    )
    await db.rsl_xp_events.create_index(
        [("guild_id", 1), ("user_id", 1), ("source", 1), ("event_id", 1)],
        unique=True,
        name="uniq_rsl_xp_event",
    )
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
    await db.club_invitations.create_index(
        [("club_id", 1), ("invitee_id", 1)],
        unique=True,
        partialFilterExpression={"status": "pending"},
        name="uniq_pending_club_invitation",
    )
    await db.club_join_requests.create_index(
        [("club_id", 1), ("user_id", 1)],
        unique=True,
        partialFilterExpression={"status": "pending"},
        name="uniq_pending_club_join_request",
    )
    await db.club_invitations.create_index([("invitee_id", 1), ("status", 1), ("created_at", -1)], name="idx_club_invitations")
    await db.club_join_requests.create_index([("club_id", 1), ("status", 1), ("created_at", -1)], name="idx_club_join_requests")
    await db.tournament_action_locks.create_index(
        [("tournament_id", 1), ("match_id", 1)],
        unique=True,
        name="uniq_tournament_action_lock",
    )
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
    try:
        await db.notification_deliveries.drop_index("uniq_notification_delivery")
    except Exception:
        pass
    try:
        await db.rsl_economy_transactions.drop_index("uniq_rsl_economy_message_transaction")
    except Exception:
        pass
    await db.rsl_economy_transactions.create_index(
        [("guild_id", 1), ("user_id", 1), ("created_at", -1)],
        name="idx_rsl_economy_history",
    )
    await db.notification_deliveries.create_index(
        [("event_id", 1), ("user_id", 1), ("lead_days", 1)],
        unique=True,
        name="uniq_notification_delivery",
    )
    await db.web_sessions.create_index(
        [("expires_at", 1)],
        expireAfterSeconds=0,
        name="ttl_web_sessions",
    )
    # Sessions created before the TTL migration stored Unix timestamps. They
    # cannot participate in a MongoDB date TTL index, so remove them once at
    # startup rather than leaving stale legacy sessions around indefinitely.
    await db.web_sessions.delete_many({"expires_at": {"$type": "number"}})

    await db.rsl_tickets.create_index([("guild_id", 1), ("status", 1), ("updated_at", -1)], name="idx_rsl_tickets_queue")
    await db.rsl_tickets.create_index([("guild_id", 1), ("user_id", 1), ("status", 1)], name="idx_rsl_tickets_user_status")
    await db.rsl_tickets.create_index([("guild_id", 1), ("user_id", 1), ("type", 1), ("active", 1)], unique=True, partialFilterExpression={"active": True}, name="uniq_rsl_active_ticket_type")
    await db.rsl_ticket_events.create_index([("guild_id", 1), ("ticket_id", 1), ("created_at", -1)], name="idx_rsl_ticket_events")
    await db.rsl_ticket_notifications.create_index([("event_key", 1)], unique=True, name="uniq_rsl_ticket_notification_event")
    await db.rsl_ticket_notifications.create_index([("guild_id", 1), ("status", 1), ("retry_at", 1)], name="idx_rsl_ticket_notification_retry")
    await db.rsl_recovery_checkpoints.create_index([("guild_id", 1), ("created_at", -1)], name="idx_rsl_recovery_checkpoint")
    await db.active_challenges.create_index(
        [("guild_id", 1), ("status", 1), ("processing_at", 1)],
        name="idx_active_challenge_status_processing",
    )
    await db.active_challenges.create_index(
        [("guild_id", 1), ("status", 1), ("rsl_bonus_checked", 1)],
        name="idx_active_challenge_bonus_recovery",
    )
    await db.rsl_economy_transactions.create_index(
        [("guild_id", 1), ("status", 1), ("created_at", 1)],
        name="idx_rsl_economy_pending_recovery",
    )
    await db.drivers.create_index(
        [("guild_id", 1), ("rsl_xp", 1)],
        name="idx_rsl_xp_role_reconciliation",
    )

    # Defense-in-depth uniqueness guard. Older Mongo deployments can reject
    # the $in partial-filter form, and legacy duplicate rows can prevent index
    # creation. Never make the entire bot fail startup for this optimization.
    duplicate_cursor = db.active_challenges.aggregate([
        {"$match": {"status": {"$in": ["active", "processing"]}}},
        {"$group": {
            "_id": {"guild_id": "$guild_id", "challenger_id": "$challenger_id"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$limit": 1},
    ])
    duplicates = await duplicate_cursor.to_list(length=1)
    if duplicates:
        import logging
        logging.getLogger(__name__).error(
            "Skipping active Gauntlet uniqueness index because legacy duplicate active challenges exist: %s",
            duplicates[0],
        )
    else:
        try:
            await db.active_challenges.create_index(
                [("guild_id", 1), ("challenger_id", 1)],
                unique=True,
                partialFilterExpression={"status": {"$in": ["active", "processing"]}},
                name="uniq_active_gauntlet_challenge_per_player",
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Unable to create active Gauntlet uniqueness index; runtime atomic claims remain authoritative"
            )
    # Keep settlement IDs indexed for staff reconciliation/auditing. The
    # authoritative replay guard is the deterministic match _id itself, which
    # MongoDB already enforces as unique without risking startup failure if
    # legacy data contains duplicate settlement_id metadata.
    await db.matches.create_index(
        [("settlement_id", 1)],
        name="idx_gauntlet_settlement_id",
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
    from .core.rsl_role_sync import (
        reconcile_completed_tournament_achievement_roles,
        reconcile_gauntlet_season_roles,
    )
    from .core.rsl_economy_ledger import reconcile_pending_coin_transactions
    if not getattr(bot, "_rsl_role_recovery_done", False):
        bot._rsl_role_recovery_done = True
        bot._rsl_tournament_achievement_recovery_done = True
        for guild in bot.guilds:
            try:
                settings = await bot.db.settings.find_one({"_id": str(guild.id)}) or {}
                await reconcile_gauntlet_season_roles(
                    bot.db,
                    guild,
                    role_names=settings.get("achievement_role_names"),
                    role_ids=settings.get("achievement_role_ids"),
                )
                await reconcile_completed_tournament_achievement_roles(
                    bot.db,
                    guild,
                    role_names=settings.get("achievement_role_names"),
                    role_ids=settings.get("achievement_role_ids"),
                )
                await reconcile_pending_coin_transactions(
                    bot.db,
                    guild_id=str(guild.id),
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "Failed to recover RSL roles for guild %s", guild.id
                )


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
