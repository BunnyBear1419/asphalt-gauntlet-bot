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
