import time
import os
import asyncio
import discord
import logging
from .core.core import bot
from .core.ui_fixes import install_ui_fixes
from .web.server import WebControlCenter

log = logging.getLogger(__name__)

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
    await db.gauntlet_reference_notes.create_index([("guild_id", 1), ("reference_id", 1), ("created_at", 1)], name="idx_gauntlet_reference_notes")
    await db.reference_intel.create_index([("guild_id", 1), ("course", 1), ("created_at", -1)], name="idx_reference_intel")
    await db.reference_intel_votes.create_index([("guild_id", 1), ("intel_id", 1), ("user_id", 1)], unique=True, name="uniq_reference_intel_vote")
    await db.reference_requests.create_index([("guild_id", 1), ("status", 1), ("votes", -1), ("created_at", -1)], name="idx_reference_requests")
    await db.reference_requests.create_index([("guild_id", 1), ("kind", 1), ("priority", -1), ("votes", -1), ("created_at", -1)], name="idx_reference_requests_kind_priority")
    await db.reference_requests.create_index([("guild_id", 1), ("fingerprint", 1)], unique=True, partialFilterExpression={"fingerprint": {"$exists": True}}, name="uniq_reference_request_fingerprint")
    await db.reference_request_votes.create_index([("guild_id", 1), ("request_id", 1), ("user_id", 1)], unique=True, name="uniq_reference_request_vote")
    await db.gauntlet_reference_notes.create_index([("guild_id", 1), ("user_id", 1), ("reference_id", 1)], name="idx_gauntlet_reference_notes_owner")
    await db.reference_pending.create_index([("guild_id", 1), ("status", 1), ("created_at", -1)], name="idx_reference_pending_review")
    await db.reference_guides.create_index([("guild_id", 1), ("status", 1), ("created_at", -1)], name="idx_reference_guides")
    await db.reference_history.create_index([("guild_id", 1), ("status", 1), ("event_date", -1), ("created_at", -1)], name="idx_reference_history")
    await db.reference_history.create_index([("guild_id", 1), ("category", 1), ("era", 1)], name="idx_reference_history_filters")
    await db.reference_events.create_index([("guild_id", 1), ("status", 1), ("start_date", -1), ("created_at", -1)], name="idx_reference_events")
    await db.reference_events.create_index([("guild_id", 1), ("category", 1), ("season", 1)], name="idx_reference_events_filters")
    await db.gauntlet_practice_plans.create_index([("guild_id", 1), ("user_id", 1)], unique=True, name="uniq_gauntlet_practice_plan")
    await db.lap_times.create_index([("guild_id", 1), ("user_id", 1), ("best_ms", 1)], name="idx_rsl_personal_records")
    await db.rsl_weekly_challenges.create_index([("guild_id", 1), ("week_start", -1)], name="idx_rsl_weekly_challenges")
    await db.rsl_reference_beats.create_index([("guild_id", 1), ("status", 1), ("created_at", -1)], name="idx_rsl_reference_beats")
    await db.rsl_reference_beat_submissions.create_index([("guild_id", 1), ("beat_id", 1), ("status", 1), ("ms", 1)], name="idx_rsl_reference_beat_submissions")
    await db.rsl_reference_beat_submissions.create_index([("guild_id", 1), ("beat_id", 1), ("user_id", 1)], unique=True, name="uniq_rsl_reference_beat_submission")
    await db.rsl_weekly_challenge_submissions.create_index([("guild_id", 1), ("challenge_id", 1), ("status", 1), ("score", -1), ("ms", 1)], name="idx_rsl_weekly_challenge_submissions")
    await db.rsl_weekly_challenge_submissions.create_index([("guild_id", 1), ("challenge_id", 1), ("user_id", 1)], unique=True, name="uniq_rsl_weekly_challenge_submission")
    await db.reference_guides.create_index([("guild_id", 1), ("category", 1), ("helpful", -1)], name="idx_reference_guides_category")
    await db.reference_guide_votes.create_index([("guild_id", 1), ("guide_id", 1), ("user_id", 1)], unique=True, name="uniq_reference_guide_vote")
    await db.reference_reputation_resets.create_index([("guild_id", 1), ("user_id", 1)], unique=True, name="uniq_reference_reputation_reset")
    await db.tournament_media.create_index(
        [("tournament_id", 1), ("status", 1), ("created_at", -1)],
        name="idx_tournament_media_gallery",
    )
    try:
        await db.notification_deliveries.drop_index("uniq_notification_delivery")
    except Exception:
        log.debug("Legacy notification delivery index was not present during startup cleanup", exc_info=True)
    try:
        await db.rsl_economy_transactions.drop_index("uniq_rsl_economy_message_transaction")
    except Exception:
        log.debug("Legacy economy transaction index was not present during startup cleanup", exc_info=True)
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
    await db.csp_reports.create_index(
        [("created_at", 1)],
        expireAfterSeconds=14 * 24 * 60 * 60,
        name="ttl_csp_reports",
    )
    await db.csp_reports.delete_many({"created_at": {"$type": "number"}})
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
    await db.rsl_recovery_checkpoints.create_index([("guild_id", 1), ("kind", 1), ("started_at", -1)], name="idx_rsl_recovery_run_started")
    await db.rsl_recovery_checkpoints.create_index([("expires_at", 1)], expireAfterSeconds=0, partialFilterExpression={"kind": "recovery_run"}, name="ttl_rsl_recovery_runs")
    await _cleanup_legacy_active_challenge_duplicates()
    # Defense-in-depth uniqueness guard. Older Mongo deployments can reject
    # the $in partial-filter form, and legacy duplicate rows can prevent index
    # creation. Never make the entire bot fail startup for this optimization.
    try:
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
    except Exception:
        duplicates = []
        import logging
        logging.getLogger(__name__).exception("Unable to preflight active Gauntlet challenge duplicates; continuing with guarded index creation")
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


async def _cleanup_legacy_active_challenge_duplicates():
    """Archive legacy duplicate active/processing challenges before uniqueness indexing."""
    db = getattr(bot, "db", None)
    if db is None:
        return
    import logging
    logger = logging.getLogger(__name__)
    try:
        cursor = db.active_challenges.aggregate([
            {"$match": {"status": {"$in": ["active", "processing"]}}},
            {"$group": {
                "_id": {"guild_id": "$guild_id", "challenger_id": "$challenger_id"},
                "count": {"$sum": 1},
            }},
            {"$match": {"count": {"$gt": 1}}},
        ])
        groups = await cursor.to_list(length=500)
        for group in groups:
            key = group.get("_id") or {}
            rows = await db.active_challenges.find({
                "guild_id": str(key.get("guild_id") or ""),
                "challenger_id": str(key.get("challenger_id") or ""),
                "status": {"$in": ["active", "processing"]},
            }).sort([("updated_at", -1), ("created_at", -1), ("_id", -1)]).to_list(length=100)
            if len(rows) < 2:
                continue
            challenge_ids = [str(row.get("_id") or "") for row in rows]
            reservations = {}
            async for reservation in db.matches.find(
                {"_id": {"$in": [f"{challenge_id}:match" for challenge_id in challenge_ids]}},
                {"_id": 1, "settlement_status": 1},
            ):
                reservations[str(reservation.get("_id") or "")] = str(reservation.get("settlement_status") or "").casefold()
            def _as_number(value):
                # Challenge timestamps are floats today, but legacy rows may be
                # missing them or hold strings; never let a mixed-type compare
                # abort the whole cleanup (and with it the unique index).
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return 0.0

            rows.sort(
                key=lambda row: (
                    reservations.get(f"{row.get('_id')}:match") == "completed",
                    _as_number(row.get("updated_at")),
                    _as_number(row.get("created_at")),
                    str(row.get("_id") or ""),
                ),
                reverse=True,
            )
            keep = rows[0]
            for duplicate in rows[1:]:
                await db.active_challenges.update_one(
                    {"_id": duplicate["_id"], "status": {"$in": ["active", "processing"]}},
                    {"$set": {
                        "status": "superseded",
                        "superseded_by": str(keep.get("_id")),
                        "superseded_at": time.time(),
                        "recovery_reason": "legacy_duplicate_cleanup",
                    }},
                )
                logger.warning(
                    "Archived legacy duplicate Gauntlet challenge %s for %s/%s; kept %s",
                    duplicate.get("_id"), key.get("guild_id"), key.get("challenger_id"), keep.get("_id"),
                )
    except Exception:
        logger.exception("Legacy duplicate Gauntlet challenge cleanup failed")

async def _ensure_advisory_rsl_indexes():
    db = getattr(bot, "db", None)
    if db is None:
        return
    import logging
    index_log = logging.getLogger(__name__)
    for collection, keys, name in (
        (db.active_challenges, [("guild_id", 1), ("status", 1), ("processing_at", 1)], "idx_active_challenge_status_processing"),
        (db.active_challenges, [("guild_id", 1), ("status", 1), ("rsl_bonus_checked", 1)], "idx_active_challenge_bonus_recovery"),
        (db.rsl_economy_transactions, [("guild_id", 1), ("status", 1), ("created_at", 1)], "idx_rsl_economy_pending_recovery"),
        (db.matches, [("guild_id", 1), ("rsl_bonus_recovery_status", 1)], "idx_match_bonus_recovery_status"),
        (db.drivers, [("guild_id", 1), ("rsl_xp_role_sync_pending", 1)], "idx_rsl_xp_role_reconciliation"),
    ):
        try:
            await collection.create_index(keys, name=name)
        except Exception:
            index_log.exception("Unable to create advisory RSL index %s", name)


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
            log.exception("Failed to reconcile Discord bot username during RSL identity update")
        try:
            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Racing Syndicate League"))
        except Exception:
            log.exception("Failed to update Discord bot presence during RSL identity reconciliation")


@bot.event
async def on_ready():
    await _apply_rsl_identity()
    try:
        await _ensure_advisory_rsl_indexes()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Advisory RSL index reconciliation failed during ready")
    if not getattr(bot, "_rsl_media_purge_done", False):
        bot._rsl_media_purge_done = True
        try:
            from .core.rsl_media_cleanup import purge_rejected_tournament_media
            purged = await purge_rejected_tournament_media(bot.db)
            if purged:
                import logging
                logging.getLogger(__name__).info("Purged %s rejected tournament media payload(s)", purged)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Rejected tournament media purge failed during ready")
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
