"""Static regression tests for the dashboard-first command/UI architecture."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ALU_Gauntlet"
CORE = PACKAGE / "core" / "core.py"
ADMIN = PACKAGE / "cogs" / "administration.py"


def _source() -> str:
    return CORE.read_text(encoding="utf-8")


def _admin_source() -> str:
    return ADMIN.read_text(encoding="utf-8")


def _top_commands() -> dict[str, tuple[Path, str]]:
    found: dict[str, tuple[Path, str]] = {}
    for path in (PACKAGE / "cogs").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                text = ast.unparse(decorator)
                match = re.search(r"app_commands\.command\(name=['\"]([^'\"]+)", text)
                if match:
                    name = match.group(1)
                    assert name not in found, f"Duplicate top-level application command: {name}"
                    found[name] = (path, node.name)
    return found


def _groups() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in (PACKAGE / "cogs").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                text = ast.unparse(decorator)
                match = re.search(r"(\w+)_group\.command\(name=['\"]([^'\"]+)", text)
                if match:
                    found.setdefault(match.group(1), set()).add(match.group(2))
    return found


def _quoted_values(block: str) -> list[str]:
    return re.findall(r'\("[^\n]*?",\s*"([a-zA-Z0-9_]+)",', block)


def test_only_dashboard_and_staff_are_public():
    commands = _top_commands()
    assert set(commands) == {"dashboard", "staff"} | {
        "whatnext", "profile", "register", "mystatus",
        "delete_me", "setdefense", "mydefense", "changedefense", "submitdefense", "challenge",
        "submitmatch_direct", "leaderboard", "top", "maps", "besttime", "reference", "add_reference",
        "help", "status", "missingdefense", "adminlog", "pending", "listplayers", "clearhistory",
        "dbcheck", "backup", "diagnostics", "launchcheck", "setimage", "setup", "delete_id",
        "identity", "sync",
    }

    source = _source()
    assert 'required_commands = {"dashboard", "staff"}' in source
    assert "COMMAND_ARCHITECTURE_VERSION = 12" in _admin_source()


def test_every_non_public_top_level_command_is_explicitly_hidden():
    commands = set(_top_commands())
    public = {"dashboard", "staff"}
    hidden_match = re.search(r'HIDDEN_PLAYER_COMMANDS = \{(.*?)\n\}', _source(), re.S)
    hidden_staff_match = re.search(r'HIDDEN_STAFF_COMMANDS = \{(.*?)\n\}', _source(), re.S)
    assert hidden_match and hidden_staff_match
    hidden = set(re.findall(r'"([a-zA-Z0-9_]+)"', hidden_match.group(1))) | set(re.findall(r'"([a-zA-Z0-9_]+)"', hidden_staff_match.group(1)))
    # timezone remains as a legacy hidden alias in core.py after the standalone
    # top-level command was removed from the administration cog.
    assert commands - public == (hidden - {"season", "admin", "timezone"})
    assert not (public & hidden)


def test_group_commands_are_hidden_as_groups():
    groups = _groups()
    assert groups["season"] == {"auto", "schedule", "reset", "start", "status", "end", "history"}
    assert groups["admin"] == {"setpi", "removeracer"}
    source = _source()
    assert '"season", "admin",' in source


def test_dashboard_and_staff_action_values_are_unique_and_resolvable():
    source = _source()
    player_block = source[source.index("class DashboardActionSelect"):source.index("class DashboardView")]
    staff_block = source[source.index("class StaffActionSelect"):source.index("class StaffNextTaskButton")]
    player_values = _quoted_values(player_block)
    staff_values = _quoted_values(staff_block)
    assert len(player_values) == len(set(player_values))
    assert len(staff_values) == len(set(staff_values))

    hidden_names = set(re.findall(r'"([a-zA-Z0-9_]+)"', re.search(r'HIDDEN_PLAYER_COMMANDS = \{(.*?)\n\}', source, re.S).group(1)))
    hidden_names |= set(re.findall(r'"([a-zA-Z0-9_]+)"', re.search(r'HIDDEN_STAFF_COMMANDS = \{(.*?)\n\}', source, re.S).group(1)))
    direct_player = {"setdefense_confirm", "changedefense_confirm", "submitmatch_wizard", "maps_direct", "besttime_direct", "reference_direct", "add_reference_direct", "notifications", "delete_me", "seasonhistory", "matchcenter"}
    direct_staff = {"player_changes", "defense_reviews", "reference_reviews", "seasonauto_direct", "season_schedule_direct", "seasonreset_direct", "clearhistory_direct", "setup_direct", "timezone_direct", "identity_direct", "setimage_direct", "launchcheck", "seasonstatus", "seasonstart", "seasonend"}
    assert set(player_values) - direct_player <= hidden_names
    assert set(staff_values) - direct_staff <= hidden_names


def test_main_dashboard_rows_never_exceed_discord_button_limit():
    source = _source()
    assert source.count('row=2') >= 8
    player_nav = source[source.index("class DashboardView"):source.index("async def send_dashboard")]
    assert player_nav.count('row=2') == 5
    staff_nav = source[source.index("class StaffDashboardView"):source.index("class StaffCategorySelect")]
    assert staff_nav.count('row=2') == 3
    next_task = source[source.index("class StaffNextTaskButton"):source.index("class StaffDashboardView")]
    assert next_task.count('row=2') == 1


def test_dashboard_refresh_and_nested_home_edit_in_place():
    source = _source()
    assert 'await send_dashboard(interaction, edit=True)' in source
