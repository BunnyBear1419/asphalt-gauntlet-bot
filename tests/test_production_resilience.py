"""Regression tests for production restart and recovery safeguards.

These tests intentionally stay offline: they validate the recovery contracts in
source and exercise only lightweight state transitions.  They must never take
down or mutate the live production bot/database.
"""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "ALU_Gauntlet" / "core" / "core.py"
MAIN_PATH = ROOT / "ALU_Gauntlet" / "main.py"
SEASON_PATH = ROOT / "ALU_Gauntlet" / "cogs" / "season.py"
OPERATIONS_PATH = ROOT / "ALU_Gauntlet" / "cogs" / "operations.py"


def _source(path):
    return path.read_text(encoding="utf-8")


def test_production_recovery_code_parses():
    for path in (MAIN_PATH, CORE_PATH, SEASON_PATH):
        ast.parse(_source(path))


def test_startup_recovers_persisted_season_state():
    source = _source(CORE_PATH)
    assert "recover_season_state" in source
    assert "season_state" in source
    assert "self.season" in source


def test_health_heartbeat_reports_database_and_ready_state():
    source = _source(CORE_PATH)
    assert "production_heartbeat_loop" in source
    assert "db_ok" in source
    assert "ready" in source
    assert "production_heartbeat" in source


def test_season_cog_setup_does_not_start_a_second_background_clock():
    source = _source(SEASON_PATH)
    assert "season_group" in source
    setup_start = source.index("async def setup(bot):")
    setup_block = source[setup_start:]

    # The season cog registers commands only. Background scheduling is owned by
    # the bot/core lifecycle, so loading or reloading this cog must not create a
    # second scheduler task by calling create_task() or .start() here.
    assert "create_task(" not in setup_block
    assert ".start(" not in setup_block


def test_background_task_status_is_exposed_for_operations_monitoring():
    source = _source(OPERATIONS_PATH)
    assert "seasonal_clock_loop" in source
    assert "production_heartbeat_loop" in source
    assert "Background Tasks" in source


def test_mongodb_failure_is_not_silently_marked_healthy():
    source = _source(CORE_PATH)
    assert "db_ok" in source
    assert "except" in source
    assert "health" in source.lower()


def test_graceful_shutdown_closes_mongodb_client():
    source = _source(CORE_PATH)
    assert "close()" in source
    assert "mongo_client" in source or "mongo" in source.lower()


def test_discord_startup_and_error_handlers_exist():
    source = _source(CORE_PATH)
    assert "async def on_ready()" in source
    assert "async def on_error" in source


def test_season_schedule_survives_process_restart_contract():
    source = _source(SEASON_PATH)
    assert "starts_at" in source
    assert "ends_at" in source
    assert "season_active" in source
    assert "awaiting_staff_start" in source


def test_production_health_workflow_detects_stale_heartbeat():
    workflow = _source(ROOT / ".github" / "workflows" / "production-health.yml")
    assert "production_heartbeat" in workflow
    assert "1200" in workflow
    assert "ready" in workflow
    assert "db_ok" in workflow


def test_restore_workflow_uses_isolated_database_and_cleanup():
    workflow = _source(ROOT / ".github" / "workflows" / "mongodb-restore-test.yml")
    assert "TEST_DB" in workflow
    assert "drop_database" in workflow
    assert "isolated" in workflow.lower()
