from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ALU_Gauntlet" / "core" / "rsl_reliability.py"
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
ADMIN = ROOT / "ALU_Gauntlet" / "web" / "static" / "admin.html"
MAIN = ROOT / "ALU_Gauntlet" / "main.py"


def test_final_reliability_helpers_cover_requested_controls():
    source = MODULE.read_text(encoding="utf-8")
    for marker in (
        "backup_directory_snapshot",
        "retention_policy",
        "release_gate",
        "economy_integrity_snapshot",
        "attention_queue_snapshot",
        "build_reliability_snapshot",
        "create_recovery_checkpoint",
    ):
        assert marker in source


def test_reliability_admin_surface_is_merged_into_existing_operations_center():
    server = SERVER.read_text(encoding="utf-8")
    admin = ADMIN.read_text(encoding="utf-8")
    assert 'action == "reliability"' in server
    assert 'action == "recovery_checkpoint"' in server
    assert '"/api/admin/operations"' in server
    assert "Reliability &amp; Recovery" in admin
    assert "load-reliability" in admin
    assert "create-recovery-checkpoint" in admin


def test_recovery_checkpoint_has_a_guild_scoped_index():
    main = MAIN.read_text(encoding="utf-8")
    assert "rsl_recovery_checkpoints" in main
    assert "idx_rsl_recovery_checkpoint" in main


def test_discord_status_exposes_reliability_signals():
    source = (ROOT / "ALU_Gauntlet" / "cogs" / "operations.py").read_text(encoding="utf-8")
    assert "build_reliability_snapshot" in source
    assert '"Reliability"' in source


def test_release_gate_catches_duplicate_web_routes():
    import re
    source = SERVER.read_text(encoding="utf-8")
    route_block = source[source.index("def _configure_routes"):source.index("def _configure_routes") + 18000]
    routes = re.findall(r'router\.add_(?:get|post|put|delete)\\("([^"]+)"', route_block)
    assert len(routes) == len(set(routes))
    assert '"/api/admin/operations"' in route_block
    assert '"/api/admin/backup"' in route_block
