"""RSL Gauntlet settlement recovery helpers.

Recovery is deliberately conservative:
- A processing challenge with a deterministic completed match reservation is
  closed to that exact match.
- A pending/unknown reservation is never reopened or re-settled.
- A processing challenge with no reservation is reopened only after the
  15-minute processing lease has expired.
- Ticket state is never restored by recovery; the challenge already consumed
  its ticket when it was created.
- The RSL margin bonus is optional. If its retries are exhausted the challenge
  is closed (so the player is never locked out) and the match is flagged
  ``needs_staff_review`` for the Admin System attention queue.
"""

from __future__ import annotations

import logging
import time

from .match_scoring import apply_rsl_performance_bonus

log = logging.getLogger(__name__)

PROCESSING_LEASE_SECONDS = 15 * 60
BONUS_RETRY_MAX_ATTEMPTS = 5
BONUS_RETRY_BASE_SECONDS = 5 * 60


async def _record_bonus_failure(db, reservation: dict, now: float, *, error: BaseException | None = None) -> bool:
    """Atomically advance the bonus retry counter and record its next action.

    Recovery can run concurrently from Discord, web, or scheduled workers.
    The retry counter therefore must not be derived from a stale reservation
    snapshot; use Mongo's atomic $inc and read the resulting durable count.
    """
    exhausted = False
    attempts = int(reservation.get("rsl_bonus_retry_attempts", 0) or 0) + 1
    try:
        result = await db.matches.update_one(
            {
                "_id": reservation["_id"],
                "settlement_status": "completed",
                "rsl_bonus_recovery_status": {"$ne": "needs_staff_review"},
            },
            {
                "$inc": {"rsl_bonus_retry_attempts": 1},
                "$set": {"rsl_bonus_last_error_at": now},
            },
        )
        if getattr(result, "modified_count", 0) != 1:
            current = await db.matches.find_one(
                {"_id": reservation["_id"]},
                {"rsl_bonus_retry_attempts": 1, "rsl_bonus_recovery_status": 1},
            ) or {}
            attempts = int(current.get("rsl_bonus_retry_attempts", attempts) or attempts)
            exhausted = str(current.get("rsl_bonus_recovery_status") or "").casefold() == "needs_staff_review"
        else:
            current = await db.matches.find_one(
                {"_id": reservation["_id"]},
                {"rsl_bonus_retry_attempts": 1},
            ) or {}
            attempts = int(current.get("rsl_bonus_retry_attempts", attempts) or attempts)
            exhausted = attempts >= BONUS_RETRY_MAX_ATTEMPTS

        if exhausted:
            await db.matches.update_one(
                {
                    "_id": reservation["_id"],
                    "settlement_status": "completed",
                    "rsl_bonus_retry_attempts": {"$gte": BONUS_RETRY_MAX_ATTEMPTS},
                },
                {"$set": {"rsl_bonus_recovery_status": "needs_staff_review"}},
            )
            log.error(
                "RSL performance bonus recovery exhausted for settlement %s after %s attempts; staff review required",
                reservation.get("_id"), attempts, exc_info=error is not None,
            )
        else:
            delay = BONUS_RETRY_BASE_SECONDS * (2 ** max(0, attempts - 1))
            await db.matches.update_one(
                {
                    "_id": reservation["_id"],
                    "settlement_status": "completed",
                    "rsl_bonus_recovery_status": {"$ne": "needs_staff_review"},
                },
                {
                    "$set": {
                        "rsl_bonus_next_retry_at": now + delay,
                        "rsl_bonus_recovery_status": "retry_scheduled",
                    }
                },
            )
            log.warning(
                "RSL performance bonus retry %s/%s scheduled for settlement %s in %ss",
                attempts, BONUS_RETRY_MAX_ATTEMPTS, reservation.get("_id"), delay, exc_info=error is not None,
            )
    except Exception:
        log.exception("Unable to record bonus retry state for settlement %s", reservation.get("_id"))
        return False
    return exhausted


async def _park_for_staff_review(db, challenge: dict, reservation: dict, guild_id: str, now: float, stats: dict) -> None:
    """Take an exhausted-bonus challenge out of the recovery queue.

    The base settlement is authoritative and the bonus is optional, so a
    ``processing`` challenge is closed instead of leaving the player locked. The
    flag is also written on the challenge so it drops out of the completed-bonus
    scan (the match carries the same flag for the staff attention count).
    """
    challenge_id = str(challenge.get("_id") or "")
    status = str(challenge.get("status") or "")
    if status == "processing":
        result = await db.active_challenges.update_one(
            {
                "_id": challenge_id,
                "guild_id": guild_id,
                "challenger_id": str(challenge.get("challenger_id") or ""),
                "status": "processing",
            },
            {
                "$set": {
                    "status": "completed",
                    "completed_at": now,
                    "match_id": reservation["_id"],
                    "ticket_burned": True,
                    "settlement_closed": True,
                    "rsl_bonus_skipped": True,
                    "rsl_bonus_recovery_status": "needs_staff_review",
                    "reconciled_at": now,
                    "reconciliation_reason": "bonus_retry_exhausted",
                },
                "$unset": {"processing_at": ""},
            },
        )
        if getattr(result, "modified_count", 0) == 1:
            stats["closed"] += 1
            stats["staff_review"] += 1
        else:
            stats["skipped"] += 1
    elif status == "completed":
        result = await db.active_challenges.update_one(
            {"_id": challenge_id, "guild_id": guild_id, "status": "completed"},
            {"$set": {"rsl_bonus_skipped": True, "rsl_bonus_recovery_status": "needs_staff_review", "reconciled_at": now}},
        )
        if getattr(result, "modified_count", 0) == 1:
            stats["staff_review"] += 1
        else:
            stats["skipped"] += 1
    else:
        stats["skipped"] += 1


async def reconcile_processing_challenges(db, guild_id: str) -> dict[str, int]:
    """Reconcile processing Gauntlet challenges for one guild.

    Returns counters suitable for operational logging.
    """
    guild_id = str(guild_id)
    now = time.time()
    stats = {"closed": 0, "reopened": 0, "pending": 0, "skipped": 0, "bonus_retried": 0, "bonus_failed": 0, "staff_review": 0}

    challenges = []
    async for challenge in db.active_challenges.find({
        "guild_id": guild_id,
        "$or": [
            {"status": "processing"},
            {"status": "completed", "rsl_bonus_checked": {"$ne": True}, "rsl_bonus_recovery_status": {"$ne": "needs_staff_review"}},
        ],
    }):
        challenges.append(challenge)

    challenge_ids = [str(item.get("_id") or "") for item in challenges if item.get("_id")]
    reservations = {}
    if challenge_ids:
        async for reservation in db.matches.find({
            "guild_id": guild_id,
            "_id": {"$in": [f"{challenge_id}:match" for challenge_id in challenge_ids]},
        }):
            reservations[str(reservation.get("_id") or "")] = reservation

    for challenge in challenges:
        challenge_id = str(challenge.get("_id") or "")
        if not challenge_id:
            stats["skipped"] += 1
            continue

        reservation = reservations.get(f"{challenge_id}:match")

        if reservation:
            retry_status = str(reservation.get("rsl_bonus_recovery_status") or "").casefold()
            if retry_status == "needs_staff_review":
                # Retries were exhausted on an earlier pass (or by an older build
                # that left the challenge locked in processing).
                await _park_for_staff_review(db, challenge, reservation, guild_id, now, stats)
                continue
            next_retry_at = reservation.get("rsl_bonus_next_retry_at")
            try:
                if next_retry_at is not None and float(next_retry_at) > now:
                    stats["pending"] += 1
                    continue
            except (TypeError, ValueError):
                pass
            settlement_status = str(reservation.get("settlement_status") or "").casefold()
            if settlement_status == "completed":
                # The base settlement is authoritative. The RSL margin marker
                # is also authoritative for recovery: zero-margin 3-2/2-3
                # results are explicitly marked as checked by the bonus helper.
                bonus_failed = False
                exhausted = False
                # Pre-marker settlements are valid historical records. If the
                # one-time margin claim is already durable, backfill the newer
                # checked marker without opening another bonus transaction.
                if reservation.get("rsl_bonus_checked") is True or reservation.get("rsl_margin_bonus_applied") is True:
                    if reservation.get("rsl_bonus_checked") is not True:
                        await db.matches.update_one(
                            {"_id": reservation["_id"], "rsl_margin_bonus_applied": True},
                            {"$set": {"rsl_bonus_checked": True}},
                        )
                else:
                    try:
                        await apply_rsl_performance_bonus(db, reservation)
                        refreshed = await db.matches.find_one(
                            {"_id": reservation["_id"]},
                            {"rsl_margin_bonus_applied": 1, "rsl_bonus_checked": 1},
                        ) or {}
                        if refreshed.get("rsl_bonus_checked") is True or refreshed.get("rsl_margin_bonus_applied") is True:
                            if refreshed.get("rsl_bonus_checked") is not True:
                                await db.matches.update_one(
                                    {"_id": reservation["_id"], "rsl_margin_bonus_applied": True},
                                    {"$set": {"rsl_bonus_checked": True}},
                                )
                            stats["bonus_retried"] += 1
                        else:
                            bonus_failed = True
                            stats["bonus_failed"] += 1
                            exhausted = await _record_bonus_failure(db, reservation, now)
                    except Exception as exc:
                        bonus_failed = True
                        stats["bonus_failed"] += 1
                        exhausted = await _record_bonus_failure(db, reservation, now, error=exc)

                if exhausted:
                    await _park_for_staff_review(db, challenge, reservation, guild_id, now, stats)
                    continue
                if bonus_failed:
                    # Base settlement is authoritative; do not leave the player
                    # locked in processing while the optional bonus retries.
                    result = await db.active_challenges.update_one(
                        {
                            "_id": challenge_id,
                            "guild_id": guild_id,
                            "challenger_id": str(challenge.get("challenger_id") or ""),
                            "status": "processing",
                        },
                        {
                            "$set": {
                                "status": "completed",
                                "completed_at": now,
                                "match_id": reservation["_id"],
                                "ticket_burned": True,
                                "settlement_closed": True,
                                "rsl_bonus_checked": False,
                                "reconciled_at": now,
                                "reconciliation_reason": "completed_settlement_bonus_retry",
                            },
                            "$unset": {"processing_at": ""},
                        },
                    )
                    if getattr(result, "modified_count", 0) == 1:
                        stats["closed"] += 1
                    else:
                        stats["skipped"] += 1
                    continue
                if str(challenge.get("status") or "") == "completed":
                    # Historical completed challenges may predate the challenge
                    # marker. Once the deterministic settlement is checked, make
                    # the challenge itself terminal so it leaves recovery scans.
                    result = await db.active_challenges.update_one(
                        {
                            "_id": challenge_id,
                            "guild_id": guild_id,
                            "status": "completed",
                        },
                        {
                            "$set": {
                                "rsl_bonus_checked": True,
                                "reconciled_at": now,
                                "reconciliation_reason": "completed_settlement_backfill",
                            },
                        },
                    )
                    if getattr(result, "modified_count", 0) == 1:
                        stats["closed"] += 1
                    else:
                        stats["skipped"] += 1
                    continue
                result = await db.active_challenges.update_one(
                    {
                        "_id": challenge_id,
                        "guild_id": guild_id,
                        "challenger_id": str(challenge.get("challenger_id") or ""),
                        "status": "processing",
                    },
                    {
                        "$set": {
                            "status": "completed",
                            "completed_at": now,
                            "match_id": reservation["_id"],
                            "ticket_burned": True,
                            "settlement_closed": True,
                            "rsl_bonus_checked": True,
                            "reconciled_at": now,
                            "reconciliation_reason": "completed_settlement",
                        },
                        "$unset": {"processing_at": ""},
                    },
                )
                if getattr(result, "modified_count", 0) == 1:
                    stats["closed"] += 1
                else:
                    stats["skipped"] += 1
            else:
                stats["pending"] += 1
            continue

        if str(challenge.get("status") or "") != "processing":
            stats["skipped"] += 1
            continue

        raw_processing_at = challenge.get("processing_at")
        try:
            processing_at = float(raw_processing_at) if raw_processing_at is not None else now
        except (TypeError, ValueError):
            processing_at = now

        if now - processing_at <= PROCESSING_LEASE_SECONDS:
            stats["skipped"] += 1
            continue

        result = await db.active_challenges.update_one(
            {
                "_id": challenge_id,
                "guild_id": guild_id,
                "challenger_id": str(challenge.get("challenger_id") or ""),
                "status": "processing",
            },
            {
                "$set": {
                    "status": "active",
                    "last_reminder": 0,
                    "recovered_at": now,
                    "recovery_reason": "processing_lease_expired_without_reservation",
                    "ticket_burned": True,
                    "settlement_closed": False,
                },
                "$unset": {"processing_at": ""},
            },
        )
        if getattr(result, "modified_count", 0) == 1:
            stats["reopened"] += 1
        else:
            stats["skipped"] += 1

    return stats
