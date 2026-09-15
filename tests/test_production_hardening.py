from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / "ALU_Gauntlet" / "core" / "core.py").read_text(encoding="utf-8")
PLAYER = (ROOT / "ALU_Gauntlet" / "cogs" / "player.py").read_text(encoding="utf-8")
DEFENSE = (ROOT / "ALU_Gauntlet" / "cogs" / "defense.py").read_text(encoding="utf-8")
COMPETITION = (ROOT / "ALU_Gauntlet" / "cogs" / "competition.py").read_text(encoding="utf-8")

def test_pymongo_async_is_used():
    assert "from pymongo import AsyncMongoClient" in CORE
    assert "AsyncIOMotorClient" not in CORE
    assert "ServerApi(\"1\"" in CORE

def test_match_lap_revert_provenance_exists():
    assert "lap_time_history" in CORE
    assert "source_match_id" in CORE
    assert "previous_record" in CORE

def test_live_health_heartbeat_exists():
    assert "production_heartbeat_loop" in CORE
    assert "HEALTH_WEBHOOK_URL" in CORE
    assert "HEALTH_CHANNEL_ID" not in CORE

def test_review_delivery_reconciliation_exists():
    for source in (PLAYER, DEFENSE, COMPETITION):
        assert "find_recent_bot_message" in source

def test_project_parses():
    for path in [ROOT / "main.py", *sorted((ROOT / "ALU_Gauntlet").rglob("*.py"))]:
        ast.parse(path.read_text(encoding="utf-8"))


def test_required_collections_include_all_operational_collections():
    assert 'REQUIRED_COLLECTIONS' in CORE
    for name in ('lap_time_history', 'system_events'):
        assert f'"{name}"' in CORE

def test_registration_reviews_are_submission_scoped():
    assert 'submission_id' in PLAYER
    assert 'approve_driver:{self.guild_id}:{self.user_id}:{self.submission_id}' in CORE
    assert 'RegistrationDeclineModal(self.user_id, self.guild_id, self.submission_id)' in CORE

def test_universal_map_rebuild_exists():
    assert 'async def rebuild_universal_map_record(' in CORE
    assert 'replace_one({"_id": global_id}, record, upsert=True' in CORE
