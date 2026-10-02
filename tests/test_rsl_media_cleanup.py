import asyncio

import ALU_Gauntlet.core.rsl_media_cleanup as cleanup

GRIDFS_ID = "64b64b64b64b64b64b64b64b"


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def limit(self, _n):
        return self

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for row in self.rows:
            yield row


class _MediaCollection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.updates = []
        self.last_find = None

    def find(self, query, projection=None):
        self.last_find = (query, projection)
        return _Cursor(self.rows)

    async def update_one(self, query, update):
        self.updates.append((query, update))


class _DB:
    def __init__(self, rows=()):
        self.tournament_media = _MediaCollection(rows)


class _Bucket:
    def __init__(self, error=None):
        self.error = error
        self.deleted = []

    async def delete(self, file_id):
        if self.error is not None:
            raise self.error
        self.deleted.append(str(file_id))


class NoFile(Exception):
    """Stand-in for gridfs.errors.NoFile (matched by class name)."""


def _gridfs_media():
    return {"_id": "m1", "status": "rejected", "storage": "gridfs", "gridfs_id": GRIDFS_ID}


def test_purge_deletes_gridfs_payload_and_records_it():
    bucket = _Bucket()
    db = _DB()

    ok = asyncio.run(cleanup.purge_media_payload(db, _gridfs_media(), bucket_factory=lambda _db: bucket))

    assert ok is True
    assert bucket.deleted == [GRIDFS_ID]
    (query, update), = db.tournament_media.updates
    assert query == {"_id": "m1"}
    assert update["$set"]["storage"] == "purged"
    assert update["$unset"] == {"data": "", "gridfs_id": ""}


def test_purge_treats_missing_blob_as_success():
    db = _DB()
    ok = asyncio.run(cleanup.purge_media_payload(
        db, _gridfs_media(), bucket_factory=lambda _db: _Bucket(error=NoFile("gone")),
    ))
    assert ok is True
    assert len(db.tournament_media.updates) == 1


def test_purge_failure_keeps_pointer_so_the_sweep_can_retry():
    db = _DB()
    ok = asyncio.run(cleanup.purge_media_payload(
        db, _gridfs_media(), bucket_factory=lambda _db: _Bucket(error=RuntimeError("mongo down")),
    ))
    assert ok is False
    assert db.tournament_media.updates == []


def test_purge_inline_payload_never_touches_gridfs():
    def no_bucket(_db):
        raise AssertionError("inline media must not open a GridFS bucket")

    db = _DB()
    media = {"_id": "m2", "status": "rejected", "storage": "inline"}
    assert asyncio.run(cleanup.purge_media_payload(db, media, bucket_factory=no_bucket)) is True
    assert db.tournament_media.updates[0][1]["$unset"]["data"] == ""


def test_sweep_only_asks_for_rejected_media_and_skips_payload_bytes():
    bucket = _Bucket()
    db = _DB([_gridfs_media()])

    purged = asyncio.run(cleanup.purge_rejected_tournament_media(db, bucket_factory=lambda _db: bucket))

    assert purged == 1
    query, projection = db.tournament_media.last_find
    assert query["status"] == "rejected"
    assert projection == {"data": 0}
