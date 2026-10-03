from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_settlement_recovery_retries_missing_optional_rsl_bonus():
    source = (ROOT / "ALU_Gauntlet/core/rsl_recovery.py").read_text(encoding="utf-8")
    assert "from .match_scoring import apply_rsl_performance_bonus" in source
    assert 'rsl_bonus_checked' in source
    assert 'rsl_margin_bonus_applied' in source
    assert "await apply_rsl_performance_bonus(db, reservation)" in source
    assert 'stats["bonus_retried"]' in source
    assert 'stats["bonus_failed"]' in source


def test_settlement_recovery_keeps_base_settlement_authoritative_on_bonus_failure():
    source = (ROOT / "ALU_Gauntlet/core/rsl_recovery.py").read_text(encoding="utf-8")
    assert 'settlement_status == "completed"' in source
    assert '"status": "processing"' in source
    assert '"status": "completed"' in source
    assert 'settlement_closed": True' in source
    assert 'except Exception:' in source


def test_settlement_recovery_scans_completed_challenges_for_missing_bonus_without_reopening_them():
    source = (ROOT / "ALU_Gauntlet/core/rsl_recovery.py").read_text(encoding="utf-8")
    assert '"status": "processing"' in source
    assert '"status": "completed", "rsl_bonus_checked": {"$ne": True}' in source
    assert 'if str(challenge.get("status") or "") != "processing":' in source
    assert 'str(challenge.get("status") or "") != "processing"' in source


class _AsyncCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for row in self.rows:
            yield row


class _UpdateResult:
    def __init__(self, modified_count):
        self.modified_count = modified_count


class _FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.updates = []

    def find(self, query):
        if query.get("guild_id") == "guild-1" and query.get("_id", {}).get("$in"):
            ids = set(query["_id"]["$in"])
            return _AsyncCursor([row for row in self.rows if row.get("_id") in ids])
        return _AsyncCursor(self.rows)

    async def find_one(self, query, projection=None):
        return None

    async def update_one(self, query, update):
        self.updates.append((query, update))
        if "active_challenges" in getattr(self, "name", ""):
            return _UpdateResult(1)
        return _UpdateResult(1)


class _FakeDB:
    def __init__(self):
        self.active_challenges = _FakeCollection([{
            "_id": "challenge-1",
            "guild_id": "guild-1",
            "challenger_id": "driver-1",
            "status": "completed",
        }])
        self.active_challenges.name = "active_challenges"
        self.matches = _FakeCollection([{
            "_id": "challenge-1:match",
            "guild_id": "guild-1",
            "settlement_status": "completed",
        }])
        self.matches.name = "matches"


def test_completed_bonus_retry_failure_stays_recoverable(monkeypatch):
    import asyncio
    import ALU_Gauntlet.core.rsl_recovery as recovery

    async def fail_bonus(db, reservation):
        raise RuntimeError("temporary database outage")

    monkeypatch.setattr(recovery, "apply_rsl_performance_bonus", fail_bonus)
    db = _FakeDB()

    stats = asyncio.run(recovery.reconcile_processing_challenges(db, "guild-1"))

    assert stats["bonus_failed"] == 1
    (query, update), = db.active_challenges.updates
    assert query["status"] == "processing"
    assert update["$set"]["status"] == "completed"
    assert update["$set"]["settlement_closed"] is True
    assert update["$set"]["rsl_bonus_checked"] is False
    assert update["$unset"] == {"processing_at": ""}
    assert len(db.matches.updates) == 2
    assert db.matches.updates[0][1]["$inc"]["rsl_bonus_retry_attempts"] == 1
    assert db.matches.updates[0][1]["$set"]["rsl_bonus_last_error_at"]
    assert db.matches.updates[1][1]["$set"]["rsl_bonus_recovery_status"] == "retry_scheduled"


def test_settlement_recovery_has_bounded_bonus_retry_and_staff_review_terminal_state():
    source = (ROOT / "ALU_Gauntlet/core/rsl_recovery.py").read_text(encoding="utf-8")
    assert "BONUS_RETRY_MAX_ATTEMPTS = 5" in source
    assert "BONUS_RETRY_BASE_SECONDS = 5 * 60" in source
    assert '"rsl_bonus_next_retry_at"' in source
    assert '"needs_staff_review"' in source
    assert '"rsl_bonus_retry_attempts"' in source


def test_tournament_media_uses_gridfs_in_production_and_cleans_orphans():
    source = (ROOT / "ALU_Gauntlet/web/routes/tournament.py").read_text(encoding="utf-8")
    assert 'bucket_name="rsl_tournament_media"' in source
    assert 'await bucket.upload_from_stream' in source
    assert 'await bucket.delete(gridfs_id)' in source


def test_tournament_media_validation_matches_safe_image_limit():
    source = (ROOT / "ALU_Gauntlet/web/routes/tournament.py").read_text(encoding="utf-8")
    assert 'image.width > 4096 or image.height > 4096' in source
    assert 'image.width * image.height > 16_777_216' in source


def test_duplicate_cleanup_prefers_completed_settlement_reservation():
    source = (ROOT / "ALU_Gauntlet/main.py").read_text(encoding="utf-8")
    assert 'settlement_status' in source
    assert '== "completed"' in source
    assert 'rows.sort(' in source


def _db_with(challenge_status, match_extra=None):
    db = _FakeDB()
    db.active_challenges.rows[0]["status"] = challenge_status
    db.matches.rows[0].update(match_extra or {})
    return db


def test_exhausted_bonus_retries_close_processing_challenge_and_flag_staff_review(monkeypatch):
    import asyncio
    import ALU_Gauntlet.core.rsl_recovery as recovery

    async def fail_bonus(db, reservation):
        raise RuntimeError("permanent failure")

    monkeypatch.setattr(recovery, "apply_rsl_performance_bonus", fail_bonus)
    # Four earlier attempts: this failure is the fifth, so retries are exhausted.
    db = _db_with("processing", {"rsl_bonus_retry_attempts": recovery.BONUS_RETRY_MAX_ATTEMPTS - 1})

    stats = asyncio.run(recovery.reconcile_processing_challenges(db, "guild-1"))

    assert stats["bonus_failed"] == 1
    assert stats["closed"] == 1
    assert stats["staff_review"] == 1
    # The match is flagged for the Admin System attention queue...
    match_set = db.matches.updates[0][1]["$set"]
    assert match_set["rsl_bonus_recovery_status"] == "needs_staff_review"
    # ...and the player is released instead of staying locked in "processing".
    (query, update), = db.active_challenges.updates
    assert query["status"] == "processing"
    assert update["$set"]["status"] == "completed"
    assert update["$set"]["rsl_bonus_skipped"] is True
    assert update["$set"]["rsl_bonus_recovery_status"] == "needs_staff_review"
    assert update["$unset"] == {"processing_at": ""}


def test_previously_flagged_processing_challenge_is_released_without_retrying(monkeypatch):
    import asyncio
    import ALU_Gauntlet.core.rsl_recovery as recovery

    async def must_not_run(db, reservation):
        raise AssertionError("an exhausted bonus must not be retried")

    monkeypatch.setattr(recovery, "apply_rsl_performance_bonus", must_not_run)
    db = _db_with("processing", {"rsl_bonus_recovery_status": "needs_staff_review"})

    stats = asyncio.run(recovery.reconcile_processing_challenges(db, "guild-1"))

    assert stats["closed"] == 1
    assert stats["bonus_failed"] == 0
    assert db.active_challenges.updates[0][1]["$set"]["status"] == "completed"


def test_flagged_completed_challenge_leaves_the_recovery_scan(monkeypatch):
    import asyncio
    import ALU_Gauntlet.core.rsl_recovery as recovery

    async def must_not_run(db, reservation):
        raise AssertionError("an exhausted bonus must not be retried")

    monkeypatch.setattr(recovery, "apply_rsl_performance_bonus", must_not_run)
    db = _db_with("completed", {"rsl_bonus_recovery_status": "needs_staff_review"})

    stats = asyncio.run(recovery.reconcile_processing_challenges(db, "guild-1"))

    assert stats["staff_review"] == 1
    (query, update), = db.active_challenges.updates
    assert query["status"] == "completed"
    assert update["$set"]["rsl_bonus_recovery_status"] == "needs_staff_review"
    assert "status" not in update["$set"]



def test_bonus_failure_closes_processing_challenge_without_waiting_for_backoff():
    source = (ROOT / "ALU_Gauntlet/core/rsl_recovery.py").read_text(encoding="utf-8")
    assert '"reconciliation_reason": "completed_settlement_bonus_retry"' in source
    assert '"$unset": {"processing_at": ""}' in source


def test_media_quota_excludes_rejected_submissions():
    source = (ROOT / "ALU_Gauntlet/web/routes/tournament.py").read_text(encoding="utf-8")
    assert '"status": {"$ne": "rejected"}' in source


def test_csp_report_body_is_hard_capped_even_without_content_length():
    source = (ROOT / "ALU_Gauntlet/web/routes/core.py").read_text(encoding="utf-8")
    assert "request.content.read(64 * 1024 + 1)" in source
    assert "len(raw_body) > 64 * 1024" in source

def test_discord_and_web_bonus_failures_leave_recovery_marker_unchecked():
    challenges = (ROOT / "ALU_Gauntlet/cogs/challenges.py").read_text(encoding="utf-8")
    gauntlet = (ROOT / "ALU_Gauntlet/web/routes/gauntlet.py").read_text(encoding="utf-8")
    assert "bonus_checked = False" in challenges
    assert "bonus_checked = True" in challenges
    assert "'rsl_bonus_checked': bonus_checked" in challenges
    assert "bonus_checked = False" in gauntlet
    assert "bonus_checked = True" in gauntlet
    assert '"rsl_bonus_checked":bonus_checked' in gauntlet

def test_bonus_retry_counter_is_atomic_for_concurrent_recovery_workers():
    source = (ROOT / "ALU_Gauntlet/core/rsl_recovery.py").read_text(encoding="utf-8")
    helper = source[source.index("async def _record_bonus_failure"):source.index("async def _park_for_staff_review")]
    assert '"$inc": {"rsl_bonus_retry_attempts": 1}' in helper
    assert 'rsl_bonus_retry_attempts": {"$gte": BONUS_RETRY_MAX_ATTEMPTS}' in helper
    assert 'await db.matches.find_one(' in helper
    assert 'rsl_bonus_recovery_status": {"$ne": "needs_staff_review"}' in helper

\n\ndef test_recovery_run_has_durable_running_and_terminal_states():\n    source = (ROOT / "ALU_Gauntlet/core/rsl_recovery.py").read_text(encoding="utf-8")\n    assert '"kind": "recovery_run"' in source\n    assert '"status": "running"' in source\n    assert '"status": "completed"' in source\n    assert '"status": "failed"' in source\n    assert 'await _finish_recovery_run(db, guild_id, run_id, "failed", stats, error=exc)' in source\n\n\ndef test_recovery_diagnostics_treat_stale_running_run_as_stale_not_success():\n    source = (ROOT / "ALU_Gauntlet/core/rsl_reliability.py").read_text(encoding="utf-8")\n    assert 'async def recovery_run_snapshot' in source\n    assert 'status == "running" and updated_at and now - updated_at > 30 * 60' in source\n    assert 'status": "stale"' in source\n