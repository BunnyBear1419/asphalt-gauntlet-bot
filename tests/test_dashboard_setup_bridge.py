"""Regression tests for the dashboard-only Server Setup entry point."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "ALU_Gauntlet" / "cogs" / "dashboard_setup_bridge.py"
MAIN = ROOT / "ALU_Gauntlet" / "main.py"


def test_staff_setup_action_routes_at_dashboard_action_layer():
    source = BRIDGE.read_text(encoding="utf-8")
    assert "StaffDashboardView" in source
    assert 'action == "setup_direct"' in source
    assert "launch_setup_wizard(interaction)" in source
    assert "original_run_action(view, interaction, action)" in source


def test_legacy_setup_command_is_removed_before_application_sync():
    source = BRIDGE.read_text(encoding="utf-8")
    assert 'bot.tree.remove_command("setup")' in source
    assert "legacy top-level alias" in source


def test_bridge_loads_after_existing_cogs():
    source = MAIN.read_text(encoding="utf-8")
    assert '"ALU_Gauntlet.cogs.dashboard_setup_bridge"' in source
    assert source.index('"ALU_Gauntlet.cogs.dashboard_setup_bridge"') > source.index('"ALU_Gauntlet.cogs.administration"')


def test_legacy_setup_command_is_not_defined_in_administration_cog():
    source = (ROOT / "ALU_Gauntlet" / "cogs" / "administration.py").read_text(encoding="utf-8")
    assert "@app_commands.command(name='setup'" not in source
    assert "@app_commands.command(name=\"setup\"" not in source


def test_web_setup_route_remains_private_and_is_not_the_discord_command():
    server = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    assert 'add_get("/setup", self.setup_page)' in server
    assert "async def setup_page" in server
    assert "await self.require_admin(request)" in server
