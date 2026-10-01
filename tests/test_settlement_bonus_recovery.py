from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_settlement_recovery_retries_missing_optional_rsl_bonus():
    source = (ROOT / "ALU_Gauntlet/core/rsl_recovery.py").read_text(encoding="utf-8")
    assert "from .match_scoring import apply_rsl_performance_bonus" in source
    assert 'if not reservation.get("rsl_margin_bonus_applied")' in source
    assert "await apply_rsl_performance_bonus(db, reservation)" in source
    assert 'stats["bonus_retried"]' in source
    assert 'stats["bonus_failed"]' in source


def test_settlement_recovery_keeps_base_settlement_authoritative_on_bonus_failure():
    source = (ROOT / "ALU_Gauntlet/core/rsl_recovery.py").read_text(encoding="utf-8")
    block = source.split('if settlement_status == "completed":', 1)[1].split('else:', 1)[0]
    assert 'status": "completed"' in block
    assert 'settlement_closed": True' in block
    assert 'except Exception:' in block
