"""Final RSL reliability and recovery helpers.

These helpers consolidate the remaining operational safeguards without creating
duplicate dashboards or changing competition outcomes. They are advisory except
for explicit checkpoint creation requested by staff.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .platform_assurance import anomaly_flags, readiness_check, redact_document
from .rsl_hardening import ADMIN_CAPABILITIES


RELIABILITY_VERSION = "2"
DEFAULT_RETENTION_DAYS = {
    "system_events": 365,
    "ticket_events": 365,
    "notification_deliveries": 90,
    "performance_events": 30,
}


def backup_directory_snapshot(root: str | None = None, *, now: float | None = None) -> dict[str, Any]:
    """Describe local backup evidence without exposing backup contents."""
    now = float(now or time.time())
    path = Path(root or os.getenv("BACKUP_DIR", "./backups"))
    if not path.is_dir():
        return {
            "configured": True,
            "available": False,
            "path": str(path),
            "file_count": 0,
            "latest_at": None,
            "age_seconds": None,
            "total_bytes": 0,
        }
    files = [p for p in path.rglob("*") if p.is_file()]
    latest = max((p.stat().st_mtime for p in files), default=0.0)
    total = sum(max(0, int(p.stat().st_size)) for p in files)
    return {
        "configured": True,
        "available": bool(files),
        "path": str(path),
        "file_count": len(files),
        "latest_at": latest or None,
        "age_seconds": (max(0.0, now - latest) if latest else None),
        "total_bytes": total,
    }


def retention_policy(settings: dict[str, Any] | None = None) -> dict[str, int]:
    configured = (settings or {}).get("retention_days") or {}
    result = dict(DEFAULT_RETENTION_DAYS)
    for key in result:
        try:
            value = int(configured.get(key, result[key]))
            result[key] = max(7, min(value, 3650))
        except (TypeError, ValueError):
            pass
    return result


def release_gate(checks: dict[str, bool | None]) -> dict[str, Any]:
    """Return a deterministic pre-release gate result."""
    return readiness_check(checks)


async def economy_integrity_snapshot(db: Any, guild_id: str) -> dict[str, Any]:
    """Find impossible or suspicious ledger records without changing balances."""
    gid = str(guild_id)
    issues: list[dict[str, Any]] = []
    checked = 0
    try:
        cursor = db.rsl_economy_transactions.find({"guild_id": gid}).sort("created_at", -1).limit(5000)
        async for row in cursor:
            checked += 1
            amount = row.get("amount", 0)
            try:
                amount = int(amount)
            except (TypeError, ValueError):
                issues.append({"type": "invalid_amount", "id": str(row.get("_id", ""))})
                continue
            if abs(amount) > 100000:
                issues.append({"type": "extreme_transaction", "id": str(row.get("_id", "")), "amount": amount})
            if not str(row.get("user_id") or "").isdigit():
                issues.append({"type": "invalid_user", "id": str(row.get("_id", ""))})
    except Exception as exc:
        return {"ok": False, "checked": checked, "issues": [{"type": "ledger_unavailable", "detail": str(exc)[:160]}]}
    return {"ok": not issues, "checked": checked, "issues": issues[:100]}


async def attention_queue_snapshot(db: Any, guild_id: str, *, now: float | None = None) -> dict[str, Any]:
    """Summarize existing queues staff should inspect first."""
    now = float(now or time.time())
    gid = str(guild_id)
    counts: dict[str, int] = {}
    queries = {
        "open_tickets": ("rsl_tickets", {"guild_id": gid, "active": True}),
        "pending_media": ("tournament_media", {"guild_id": gid, "status": "pending"}),
        "pending_references": ("reference_pending", {"guild_id": gid, "status": "pending"}),
        "pending_defense": ("drivers", {"guild_id": gid, "defense_review_pending": True}),
        "stale_matches": ("active_challenges", {"guild_id": gid, "status": "processing", "processing_at": {"$lt": now - 900}}),
        "completed_bonus_recovery": ("active_challenges", {"guild_id": gid, "status": "completed", "rsl_bonus_checked": {"$ne": True}, "rsl_bonus_recovery_status": {"$ne": "needs_staff_review"}}),
        "bonus_staff_review": ("matches", {"guild_id": gid, "rsl_bonus_recovery_status": "needs_staff_review"}),
        "security_events": ("system_events", {"guild_id": gid, "event_type": {"$in": [
            "AUTH_FAILURE", "RATE_LIMIT", "UPLOAD_REJECTED", "PERMISSION_DENIED",
            "ECONOMY_ANOMALY", "XP_ANOMALY", "MATCH_ANOMALY",
        ]}}),
    }
    for key, (collection, query) in queries.items():
        try:
            counts[key] = int(await db[collection].count_documents(query))
        except Exception:
            counts[key] = 0
    try:
        counts["pending_coin_transactions"] = int(
            await db.rsl_economy_transactions.count_documents(
                {"guild_id": gid, "status": "pending"}
            )
        )
    except Exception:
        counts["pending_coin_transactions"] = 0
    try:
        state = await db.season_state.find_one({"_id": f"guild_{gid}"}, {"gauntlet_role_snapshot": 1})
        counts["season_role_recovery"] = 1 if (state or {}).get("gauntlet_role_snapshot") else 0
    except Exception:
        counts["season_role_recovery"] = 0
    # Computed once, after every queue is counted (it used to be summed twice,
    # which also counted the first total inside the second).
    counts["total"] = sum(value for key, value in counts.items() if key != "total")
    return counts


async def build_reliability_snapshot(db: Any, guild_id: str, *, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build one compact snapshot for the existing Admin System/Operations surface."""
    now = time.time()
    economy = await economy_integrity_snapshot(db, str(guild_id))
    attention = await attention_queue_snapshot(db, str(guild_id), now=now)
    try:
        await db.command("ping")
        database_ok = True
    except Exception:
        database_ok = False
    backup = backup_directory_snapshot(now=now)
    readiness = release_gate({
        "database": database_ok,
        "backup_evidence": backup["available"] if os.getenv("BACKUP_DIR") else None,
        "economy_integrity": economy["ok"],
        "discord": None,
        "competition_safe_mode": True,
    })
    return {
        "version": RELIABILITY_VERSION,
        "generated_at": now,
        "readiness": readiness,
        "attention": attention,
        "economy": economy,
        "backup": backup,
        "retention_days": retention_policy(settings),
        "admin_capabilities": sorted(ADMIN_CAPABILITIES),
        "safe_mode": bool(((settings or {}).get("maintenance_mode") or {}).get("enabled")),
    }


async def create_recovery_checkpoint(db: Any, guild_id: str, actor_id: str, *, release: str = "") -> dict[str, Any]:
    """Store a redacted operational checkpoint for recovery review."""
    gid = str(guild_id)
    now = time.time()
    settings = await db.settings.find_one({"_id": gid}) or {}
    season = await db.season_state.find_one({"_id": f"guild_{gid}"}) or {}
    checkpoint = {
        "guild_id": gid,
        "created_at": now,
        "created_by": str(actor_id),
        "release": str(release),
        "settings": redact_document(settings),
        "season_state": redact_document(season),
        "collection_counts": {},
    }
    for collection in ("drivers", "matches", "clubs", "tournaments", "rsl_tickets"):
        try:
            checkpoint["collection_counts"][collection] = int(await db[collection].count_documents({"guild_id": gid}))
        except Exception:
            checkpoint["collection_counts"][collection] = 0
    result = await db.rsl_recovery_checkpoints.insert_one(checkpoint)
    checkpoint["id"] = str(result.inserted_id)
    return checkpoint
