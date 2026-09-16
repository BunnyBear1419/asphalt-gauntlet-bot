from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PY_FILES = [ROOT / "main.py", ROOT / "ALU_Gauntlet" / "core" / "core.py"] + sorted((ROOT / "ALU_Gauntlet" / "cogs").glob("*.py"))

def project_source():
    return "\n".join(p.read_text(encoding="utf-8") for p in PY_FILES if p.is_file())

def has_any(source, *variants):
    return any(v in source for v in variants)

def test_all_project_python_parses():
    for path in PY_FILES:
        if path.is_file():
            ast.parse(path.read_text(encoding="utf-8"))

def test_production_safety_features_remain_available():
    source = project_source()
    required = {
        "MongoDB transaction": "start_transaction()" in source and "start_session()" in source,
        "Database backups": "create_database_backup" in source and "backup_loop" in source,
        "Manual backup command": has_any(source, "name='backup'", 'name="backup"'),
        "Season archive storage": has_any(source, '"standings": archive_rows', "'standings': archive_rows"),
        "Season archive command": has_any(source, "name='history'", 'name="history"', "name='seasonhistory'", 'name="seasonhistory"'),
        "Admin error alerts": "send_admin_alert" in source and "on_app_command_error" in source,
        "Database audit": has_any(source, "name='dbcheck'", 'name="dbcheck"'),
        "Deterministic match settlement": "settlement_id" in source and "settlement_status" in source,
    }
    failed = [k for k, v in required.items() if not v]
    assert not failed, failed

def test_cogs_package_is_present():
    expected = {"player.py", "defense.py", "challenges.py", "competition.py", "staff.py", "season.py", "administration.py", "help.py", "system.py", "operations.py", "dashboard_setup_bridge.py"}
    actual = {p.name for p in (ROOT / "ALU_Gauntlet" / "cogs").glob("*.py") if p.name != "__init__.py"}
    assert actual == expected

def test_root_loader_contains_all_cogs():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    package_source = (ROOT / "ALU_Gauntlet" / "main.py").read_text(encoding="utf-8")
    assert "from ALU_Gauntlet.main import runner" in source
    for cog in ("player", "defense", "challenges", "competition", "staff", "season", "administration", "help", "system", "operations", "dashboard_setup_bridge"):
        assert f"ALU_Gauntlet.cogs.{cog}" in package_source
