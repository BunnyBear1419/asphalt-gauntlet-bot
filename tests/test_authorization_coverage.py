"""Regression tests for privileged Discord command authorization.

Every command listed here changes configuration, exposes staff/admin data, or
performs an operational action. Public player/help commands are intentionally
not included. The test accepts the bot's two supported authorization styles:
- @require_admin() decorator (including admin command groups)
- explicit check_admin_privileges(...) / Administrator permission checks
"""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "ALU_Gauntlet" / "cogs"


PRIVILEGED_COMMANDS = {
    "administration.py": {
        "setimage_cmd",
        "admin_setpi_cmd",
        "admin_removeracer_cmd",
        "delete_id_cmd",
        "identity_cmd",
        "sync_cmd",
    },
    "season.py": {
        "season_auto_cmd",
        "season_schedule_cmd",
        "season_reset_cmd",
        "season_start_cmd",
        "season_status_cmd",
        "season_end_cmd",
    },
    "staff.py": {
        "missing_defense_cmd",
        "adminlog_cmd",
        "staff_dashboard_cmd",
        "pending_cmd",
        "listplayers_cmd",
        "clear_history_cmd",
        "dbcheck_cmd",
        "backup_cmd",
    },
    "operations.py": {"status_cmd"},
}


def _functions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _decorator_names(node):
    names = set()
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name):
            names.add(decorator.id)
        elif isinstance(decorator, ast.Call):
            target = decorator.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
        elif isinstance(decorator, ast.Attribute):
            names.add(decorator.attr)
    return names


def _calls_name(node, target_name: str) -> bool:
    return any(
        isinstance(child, ast.Call)
        and (
            (isinstance(child.func, ast.Name) and child.func.id == target_name)
            or (isinstance(child.func, ast.Attribute) and child.func.attr == target_name)
        )
        for child in ast.walk(node)
    )


def test_privileged_commands_have_authorization_guards():
    missing = []
    for filename, command_names in PRIVILEGED_COMMANDS.items():
        functions = _functions(COGS / filename)
        for command_name in command_names:
            assert command_name in functions, f"Privileged command {filename}:{command_name} is missing."
            node = functions[command_name]
            decorators = _decorator_names(node)
            authorized = (
                "require_admin" in decorators
                or "has_permissions" in decorators
                or _calls_name(node, "check_admin_privileges")
            )
            if not authorized:
                missing.append(f"{filename}:{command_name}")
    assert not missing, "Privileged commands missing an authorization guard: " + ", ".join(missing)


def test_season_history_remains_public():
    functions = _functions(COGS / "season.py")
    node = functions["seasonhistory_cmd"]
    assert "require_admin" not in _decorator_names(node)
    assert not _calls_name(node, "check_admin_privileges")


def test_force_sync_requires_discord_administrator():
    functions = _functions(COGS / "system.py")
    node = functions["force_command"]
    assert "has_permissions" in _decorator_names(node)
