from pathlib import Path
import ast
import asyncio
import importlib


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ALU_Gauntlet"
CORE = PACKAGE / "core" / "core.py"
COGS = PACKAGE / "cogs"
ENTRY = ROOT / "main.py"

EXPECTED_COGS = {
    "player.py": {
        "gauntlet", "whatnext", "profile", "register", "register_direct",
        "notifications", "mystatus", "delete_me",
    },
    "defense.py": {
        "setdefense", "mydefense", "changedefense", "submitdefense",
    },
    "challenges.py": {
        "challenge", "submitmatch_direct",
    },
    "competition.py": {
        "leaderboard", "top", "maps", "besttime", "reference", "add_reference",
    },
    "staff.py": {
        "missingdefense", "adminlog", "staff", "pending", "listplayers",
        "clearhistory", "dbcheck", "backup", "diagnostics", "launchcheck",
    },
    "season.py": {
        "season auto", "season schedule", "season reset", "season start",
        "season status", "season end", "season history",
    },
    "administration.py": {
        "setimage", "setup", "timezone", "admin setpi", "admin removeracer",
        "delete_id", "identity", "sync",
    },
    "help.py": {"help"},
    "system.py": {"forcesync"},
}

PUBLIC_COMMANDS = {"gauntlet", "register", "staff", "help"}
HIDDEN_PLAYER = {
    "whatnext", "mydefense", "challenge", "profile", "leaderboard", "top",
    "mystatus", "setdefense", "changedefense", "submitdefense", "notifications",
    "register_direct", "submitmatch_direct", "submitmatch", "maps", "besttime",
    "reference", "add_reference", "delete_me",
}
HIDDEN_STAFF = {
    "missingdefense", "adminlog", "pending", "listplayers", "dbcheck", "backup",
    "diagnostics", "sync", "launchcheck", "setimage", "setup", "timezone",
    "clearhistory", "identity", "delete_id", "season", "admin",
}


def _decorator_command_name(decorator):
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr != "command":
        return None
    for kw in decorator.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return None


def _command_names(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            name = _decorator_command_name(decorator)
            if name:
                # Group commands become "season auto" / "admin setpi".
                if isinstance(decorator.func, ast.Attribute) and isinstance(
                    decorator.func.value, ast.Name
                ):
                    parent = decorator.func.value.id
                    if parent in {"season_group", "admin_group"}:
                        name = f"{parent.removesuffix('_group')} {name}"
                names.add(name)

    return names


def _all_source_text():
    parts = [ENTRY.read_text(encoding="utf-8"), CORE.read_text(encoding="utf-8")]
    parts.extend(
        p.read_text(encoding="utf-8")
        for p in sorted(COGS.glob("*.py"))
        if p.name != "__init__.py"
    )
    return "\n".join(parts)


def test_cogs_package_structure():
    assert ENTRY.is_file()
    assert PACKAGE.is_dir()
    assert (PACKAGE / "__init__.py").is_file()
    assert (PACKAGE / "core" / "__init__.py").is_file()
    assert (PACKAGE / "core" / "core.py").is_file()
    assert (COGS / "__init__.py").is_file()

    for filename in EXPECTED_COGS:
        assert (COGS / filename).is_file(), f"Missing Cog: {filename}"


def test_every_cog_has_expected_commands():
    actual_total = 0

    for filename, expected in EXPECTED_COGS.items():
        actual = _command_names(COGS / filename)
        assert actual == expected, (
            f"{filename}: expected {sorted(expected)}, got {sorted(actual)}"
        )
        actual_total += len(actual)

    assert actual_total == 47


def test_entrypoint_declares_all_nine_cogs():
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    extensions = None

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "EXTENSIONS":
                    extensions = ast.literal_eval(node.value)

    assert extensions == [
        "ALU_Gauntlet.cogs.player",
        "ALU_Gauntlet.cogs.defense",
        "ALU_Gauntlet.cogs.challenges",
        "ALU_Gauntlet.cogs.competition",
        "ALU_Gauntlet.cogs.staff",
        "ALU_Gauntlet.cogs.season",
        "ALU_Gauntlet.cogs.administration",
        "ALU_Gauntlet.cogs.help",
        "ALU_Gauntlet.cogs.system",
    ]


def test_all_project_python_files_compile():
    for path in [ENTRY, CORE, PACKAGE / "__init__.py",
                 PACKAGE / "core" / "__init__.py",
                 *COGS.glob("*.py")]:
        ast.parse(path.read_text(encoding="utf-8"))


def test_clean_public_command_architecture_is_present():
    source = _all_source_text()
    assert 'required_commands = {"gauntlet", "help", "register", "staff"}' in source
    assert "HIDDEN_PLAYER_COMMANDS" in source
    assert "HIDDEN_STAFF_COMMANDS" in source
    assert 'COMMAND_ARCHITECTURE_VERSION = 7' in source

    for name in PUBLIC_COMMANDS:
        assert f'name="{name}"' in source or f"name='{name}'" in source


def test_hidden_command_sets_match_expected_architecture():
    source = CORE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in {
                "HIDDEN_PLAYER_COMMANDS", "HIDDEN_STAFF_COMMANDS"
            }:
                values[target.id] = ast.literal_eval(node.value)

    assert values["HIDDEN_PLAYER_COMMANDS"] == HIDDEN_PLAYER
    assert values["HIDDEN_STAFF_COMMANDS"] == HIDDEN_STAFF


def test_submit_match_is_inside_guided_player_flow():
    source = _all_source_text()
    assert "open_submitmatch_workflow" in source
    assert "Submit Match" in source
    assert "Challenges" in source
    assert '"submitmatch"' in source


def test_core_compatibility_helpers_remain_exported():
    source = CORE.read_text(encoding="utf-8")
    assert "def format_lap_time(" in source
    assert "def calculate_elo_change(" in source


def test_help_center_is_separate_and_documents_clean_surface():
    source = (COGS / "help.py").read_text(encoding="utf-8")
    assert '@app_commands.command(name=\'help\'' in source
    assert "/gauntlet" in source
    assert "/register" in source
    assert "/staff" in source
    assert "/help" in source


def test_production_safety_features_remain_in_core():
    source = CORE.read_text(encoding="utf-8")
    required = {
        "MongoDB transaction": "start_transaction()" in source and "start_session()" in source,
        "Database backups": "create_database_backup" in source and "backup_loop" in source,
        "Manual backup command": 'name="backup"' in source or "name='backup'" in source,
        "Season archive storage": '"standings": archive_rows' in source,
        "Admin error alerts": "send_admin_alert" in source and "on_app_command_error" in source,
        "Database audit": 'name="dbcheck"' in source or "name='dbcheck'" in source,
        "Deterministic match settlement": "settlement_id" in source and "settlement_status" in source,
    }
    assert all(required.values()), [k for k, v in required.items() if not v]


def test_no_obsolete_public_commands_or_old_match_ui_remnants():
    source = _all_source_text()
    for obsolete in (
        'name="admin"',
        'name="mychallenges"',
        'name="admin_backups"',
        'name="admin_restore"',
    ):
        # "admin" and the old backup commands must not be standalone slash commands.
        if obsolete == 'name="admin"':
            assert "app_commands.command(name='admin'" not in source
            assert 'app_commands.command(name="admin"' not in source
        else:
            assert obsolete not in source

    assert "DuelReportModal" not in source
    assert "submitted_courses" not in source
    assert "SequenceMatcher" not in source


def test_main_exposes_compatibility_api_without_duplicating_core():
    import main

    assert callable(main.format_lap_time)
    assert callable(main.calculate_elo_change)
    assert hasattr(main, "bot")
    assert hasattr(main, "load_cogs")


def test_cogs_can_be_imported_and_loaded_into_the_bot():
    import main

    async def run():
        for extension in main.EXTENSIONS:
            if extension not in main.bot.extensions:
                await main.bot.load_extension(extension)

        # This is the key runtime check for the split: every Cog must load
        # and grouped commands must be accepted by discord.py.
        loaded = set(main.bot.extensions)
        assert set(main.EXTENSIONS) <= loaded

        season = main.bot.tree.get_command("season")
        admin = main.bot.tree.get_command("admin")
        assert season is not None
        assert admin is not None
        assert {child.name for child in season.commands} == {
            "auto", "schedule", "reset", "start", "status", "end", "history"
        }
        assert {child.name for child in admin.commands} == {"setpi", "removeracer"}

        # Apply the same hiding operation used by production, without starting
        # the bot or touching MongoDB.
        main.configure_command_architecture()

        visible = {cmd.name for cmd in main.bot.tree.get_commands()}
        assert visible == PUBLIC_COMMANDS

        assert main.bot.tree.get_command("season") is None
        assert main.bot.tree.get_command("admin") is None

    asyncio.run(run())
