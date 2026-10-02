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


async def test_completed_bonus_retry_failure_stays_recoverable(monkeypatch):
    import ALU_Gauntlet.core.rsl_recovery as recovery

    async def fail_bonus(db, reservation):
        raise RuntimeError("temporary database outage")

    monkeypatch.setattr(recovery, "apply_rsl_performance_bonus", fail_bonus)
    db = _FakeDB()

    stats = await recovery.reconcile_processing_challenges(db, "guild-1")

    assert stats["bonus_failed"] == 1
    challenge_updates = db.active_challenges.updates
    assert challenge_updates == []
