"""Pre-deployment legacy-data audit and one-time recovery cleanup.

This script is intentionally read-first: any guild-scoped document without an
owner blocks deployment. The production heartbeat is a documented global
singleton and is exempted. Legacy recovery-run rows without expires_at are
safe to remove because the current recovery-run schema requires a seven-day
TTL.
"""

from __future__ import annotations

import os
from pymongo import MongoClient


COLLECTIONS = (
    "drivers",
    "matches",
    "active_challenges",
    "pending",
    "system_events",
    "clubs",
    "club_members",
    "club_invitations",
    "club_join_requests",
    "tournament_registrations",
    "tournament_club_registrations",
    "tournament_media",
    "rsl_tickets",
    "rsl_ticket_events",
    "rsl_recovery_checkpoints",
    "rsl_economy_transactions",
    "rsl_xp_events",
    "rsl_activity_events",
    "web_brand_assets",
    "news",
    "reference_pending", "gauntlet_reference_notes", "reference_intel", "reference_intel_votes", "reference_requests", "reference_request_votes",
)


def main() -> int:
    uri = os.environ.get("MONGO_URI", "").strip()
    if not uri:
        raise SystemExit("MONGO_URI is required")

    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    try:
        client.admin.command("ping")
        db = client["asphalt_gauntlet"]

        total_missing = 0
        for name in COLLECTIONS:
            if name not in db.list_collection_names():
                continue
            query = {"guild_id": {"$exists": False}}
            if name == "system_events":
                query = {
                    "guild_id": {"$exists": False},
                    "_id": {"$ne": "production_heartbeat"},
                }
            count = db[name].count_documents(query)
            print(f"{name}: missing_guild_id={count}")
            total_missing += count

        if total_missing:
            raise SystemExit(
                f"Legacy guild ownership audit failed: {total_missing} record(s) "
                "are missing guild_id."
            )

        recovery = db.rsl_recovery_checkpoints
        deleted = recovery.delete_many(
            {"kind": "recovery_run", "expires_at": {"$exists": False}}
        ).deleted_count
        print(f"Deleted legacy recovery-run records without expires_at: {deleted}")
        print("Pre-deployment guild ownership audit passed.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
