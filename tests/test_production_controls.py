from pathlib import Path
from web_source import web_source

ROOT = Path(__file__).resolve().parents[1]
CONTROLS = ROOT / "ALU_Gauntlet" / "core" / "production_controls.py"
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
DOC = ROOT / "docs" / "RSL_V1_RELEASE.md"

def test_production_controls_define_safe_maintenance_surface():
    source = CONTROLS.read_text(encoding="utf-8")
    assert "MAINTENANCE_PATH_PREFIXES" in source
    assert "/api/gauntlet/" in source
    assert "/api/tournaments/" in source
    assert "is_mutating_competition_path" in source
    assert "set_maintenance_mode" in source

def test_web_control_routes_and_middleware_are_wired():
    source = web_source()
    for marker in (
        "production_controls",
        "maintenance_mode",
        "/api/admin/maintenance",
    ):
        assert marker in source

def test_release_baseline_document_exists():
    doc = DOC.read_text(encoding="utf-8")
    for marker in (
        "RSL v1.0 Production Baseline",
        "Maintenance Mode",
        "Discord Support & Disputes",
        "Backup and Restore",
        "Release Freeze",
    ):
        assert marker in doc

from ALU_Gauntlet.core.production_controls import is_maintenance_enabled, is_mutating_competition_path, maintenance_message

def test_maintenance_path_policy_is_read_only_friendly():
    assert not is_mutating_competition_path("/api/gauntlet/matches", "GET")
    assert is_mutating_competition_path("/api/gauntlet/matches/report", "POST")
    assert is_mutating_competition_path("/api/tournaments/results", "PUT")
    assert not is_mutating_competition_path("/api/admin/maintenance", "PUT")

def test_maintenance_defaults_are_safe():
    assert not is_maintenance_enabled({})
    assert "temporarily paused" in maintenance_message({})
