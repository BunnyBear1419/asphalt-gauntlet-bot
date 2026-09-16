"""Regression tests for the dashboard-only Server Setup entry point."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "ALU_Gauntlet" / "cogs" / "dashboard_setup_bridge.py"
MAIN = ROOT / "ALU_Gauntlet" / "main.py"


def test_staff_setup_action_routes_to_picker_wizard():
    source = BRIDGE.read_text(encoding="utf-8")
    assert "StaffActionSelect" in source
    assert 'values[0] == "setup_direct"' in source
    assert "launch_setup_wizard(interaction)" in source
    assert "original_callback(select, interaction)" in source


def test_legacy_setup_command_is_removed_before_application_sync():
    source = BRIDGE.read_text(encoding="utf-8")
    assert 'bot.tree.remove_command("setup")' in source
    assert "legacy /setup application command" in source


def test_bridge_loads_after_existing_cogs():
    source = MAIN.read_text(encoding="utf-8")
    assert '"ALU_Gauntlet.cogs.dashboard_setup_bridge"' in source
    assert source.index('"ALU_Gauntlet.cogs.dashboard_setup_bridge"') > source.index('"ALU_Gauntlet.cogs.administration"')
