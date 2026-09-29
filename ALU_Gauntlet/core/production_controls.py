"""Production safety controls shared by the RSL web control center.

This module keeps operational controls small, deterministic, and Mongo-backed.
It intentionally does not decide competition outcomes; it only pauses mutations,
records operational events, and provides a structured staff review queue.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

MAINTENANCE_KEY = "maintenance_mode"

MAINTENANCE_PATH_PREFIXES = (
    "/api/gauntlet/",
    "/api/tournaments/",
    "/api/clubs/",
    "/api/player/tickets/",
    "/api/player/register",
    "/api/player/challenge",
    "/api/player/defense",
)

def maintenance_message(settings: dict[str, Any] | None) -> str:
    mode = (settings or {}).get(MAINTENANCE_KEY) or {}
    return str(mode.get("message") or "RSL competitive actions are temporarily paused for maintenance. Profiles, history, and account settings remain available.")

def is_maintenance_enabled(settings: dict[str, Any] | None) -> bool:
    return bool(((settings or {}).get(MAINTENANCE_KEY) or {}).get("enabled"))

def is_mutating_competition_path(path: str, method: str) -> bool:
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    if path.startswith("/api/admin/") or path.startswith("/api/auth/"):
        return False
    return any(path.startswith(prefix) for prefix in MAINTENANCE_PATH_PREFIXES)

async def set_maintenance_mode(
    db: Any,
    guild_id: str,
    enabled: bool,
    message: str | None,
    actor_id: str,
) -> dict[str, Any]:
    now = time.time()
    payload = {
        "enabled": bool(enabled),
        "message": str(message or "").strip()[:500],
        "updated_at": now,
        "updated_by": str(actor_id),
    }
    await db.settings.update_one(
        {"_id": str(guild_id)},
        {"$set": {MAINTENANCE_KEY: payload}},
        upsert=True,
    )
    await record_system_event(
        db, guild_id, actor_id, "MAINTENANCE_MODE_CHANGED",
        target_type="guild", target_id=str(guild_id),
        details={"enabled": bool(enabled), "message": payload["message"]},
    )
    return payload

async def record_system_event(
    db: Any,
    guild_id: str,
    actor_id: str | None,
    event_type: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    event_id = uuid.uuid4().hex
    await db.system_events.insert_one({
        "_id": event_id,
        "guild_id": str(guild_id),
        "timestamp": time.time(),
        "event_type": str(event_type),
        "actor_id": str(actor_id) if actor_id is not None else None,
        "target_type": target_type,
        "target_id": target_id,
        "details": details or {},
    })
    return event_id

async def create_dispute(
    db: Any,
    guild_id: str,
    user_id: str,
    *,
    category: str,
    subject: str,
    description: str,
    target_type: str | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    now = time.time()
    dispute_id = uuid.uuid4().hex
    document = {
        "_id": dispute_id,
        "guild_id": str(guild_id),
        "user_id": str(user_id),
        "category": str(category or "general")[:40],
        "subject": str(subject or "RSL Review Request").strip()[:160],
        "description": str(description or "").strip()[:4000],
        "target_type": str(target_type or "").strip()[:40] or None,
        "target_id": str(target_id or "").strip()[:120] or None,
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "resolution": None,
        "resolved_by": None,
        "resolved_at": None,
    }
    await db.disputes.insert_one(document)
    await record_system_event(
        db, guild_id, user_id, "DISPUTE_CREATED",
        target_type="dispute", target_id=dispute_id,
        details={"category": document["category"], "target_type": document["target_type"], "target_id": document["target_id"]},
    )
    return document

async def resolve_dispute(
    db: Any,
    guild_id: str,
    dispute_id: str,
    staff_id: str,
    *,
    status: str,
    resolution: str,
) -> dict[str, Any] | None:
    if status not in {"resolved", "rejected", "escalated"}:
        raise ValueError("Invalid dispute status.")
    now = time.time()
    result = await db.disputes.find_one_and_update(
        {"_id": str(dispute_id), "guild_id": str(guild_id), "status": {"$in": ["open", "escalated"]}},
        {"$set": {
            "status": status,
            "resolution": str(resolution or "").strip()[:4000],
            "resolved_by": str(staff_id),
            "resolved_at": now,
            "updated_at": now,
        }},
        return_document=True,
    )
    if result:
        await record_system_event(
            db, guild_id, staff_id, "DISPUTE_RESOLVED",
            target_type="dispute", target_id=str(dispute_id),
            details={"status": status},
        )
    return result
