from pathlib import Path

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

def test_structured_dispute_workflow_is_mongo_backed_and_audited():
    source = CONTROLS.read_text(encoding="utf-8")
    assert "async def create_dispute" in source
    assert "async def resolve_dispute" in source
    assert "DISPUTE_CREATED" in source
    assert "DISPUTE_RESOLVED" in source
    assert "status" in source

def test_web_control_routes_and_middleware_are_wired():
    source = SERVER.read_text(encoding="utf-8")
    for marker in (
        "production_controls",
        "maintenance_mode",
        "/production-controls",
        "/api/admin/maintenance",
        "/api/disputes",
    ):
        assert marker in source

def test_release_baseline_document_exists():
    doc = DOC.read_text(encoding="utf-8")
    for marker in (
        "RSL v1.0 Production Baseline",
        "Maintenance Mode",
        "Dispute / Review",
        "Backup and Restore",
        "Release Freeze",
    ):
        assert marker in doc
