"""Payload cleanup for rejected tournament media.

Rejected submissions keep their audit metadata (who uploaded what, who rejected
it, and when) but must not keep the binary payload. Production stores payloads in
GridFS (bucket ``rsl_tournament_media``); lightweight/legacy documents keep them
inline in a ``data`` field.

Everything here is idempotent and best-effort: a failed purge returns ``False``,
leaves the document untouched, and is retried by the startup sweep.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

BUCKET_NAME = "rsl_tournament_media"


def _default_bucket_factory(db: Any):
    # Imported lazily so this module stays importable without GridFS installed
    # (unit tests inject a fake bucket factory instead).
    from gridfs.asynchronous import AsyncGridFSBucket

    return AsyncGridFSBucket(db, bucket_name=BUCKET_NAME)


def _is_no_file(exc: Exception) -> bool:
    # gridfs.errors.NoFile means the blob is already gone, which is the goal.
    return type(exc).__name__ == "NoFile"


async def purge_media_payload(
    db: Any,
    media: dict,
    *,
    bucket_factory: Callable[[Any], Any] | None = None,
) -> bool:
    """Remove the stored payload of one media document.

    Returns True when no payload remains afterwards (including "there never was
    one"), False when a GridFS delete failed and should be retried later.
    """
    media_id = media.get("_id")
    if media_id is None:
        return False

    gridfs_id = media.get("gridfs_id")
    if media.get("storage") == "gridfs" and gridfs_id:
        try:
            from bson import ObjectId

            bucket = (bucket_factory or _default_bucket_factory)(db)
            try:
                await bucket.delete(ObjectId(str(gridfs_id)))
            except Exception as exc:
                if not _is_no_file(exc):
                    raise
        except Exception:
            log.exception("Failed to delete tournament media GridFS payload %s for %s", gridfs_id, media_id)
            return False

    try:
        await db.tournament_media.update_one(
            {"_id": media_id},
            {
                "$set": {"storage": "purged", "payload_purged_at": time.time()},
                "$unset": {"data": "", "gridfs_id": ""},
            },
        )
    except Exception:
        # The blob is gone but the pointer remains; the next sweep sees NoFile
        # and finishes the metadata update.
        log.exception("Failed to record tournament media payload purge for %s", media_id)
        return False
    return True


async def purge_rejected_tournament_media(
    db: Any,
    *,
    limit: int = 200,
    bucket_factory: Callable[[Any], Any] | None = None,
) -> int:
    """Sweep rejected media whose payload is still stored. Returns purged count."""
    purged = 0
    cursor = db.tournament_media.find(
        {
            "status": "rejected",
            "$or": [
                {"storage": "gridfs", "gridfs_id": {"$exists": True}},
                {"data": {"$exists": True}},
            ],
        },
        {"data": 0},
    ).limit(max(1, min(1000, int(limit))))
    async for media in cursor:
        if await purge_media_payload(db, media, bucket_factory=bucket_factory):
            purged += 1
    return purged
