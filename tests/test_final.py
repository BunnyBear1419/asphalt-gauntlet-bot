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
    expected = {"player.py", "defense.py", "challenges.py", "competition.py", "staff.py", "season.py", "administration.py", "help.py", "system.py", "operations.py", "dashboard_setup_bridge.py", "tournament.py", "asphalt_account.py", "notifications.py"}
    actual = {p.name for p in (ROOT / "ALU_Gauntlet" / "cogs").glob("*.py") if p.name != "__init__.py"}
    assert actual == expected

def test_root_loader_contains_all_cogs():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    package_source = (ROOT / "ALU_Gauntlet" / "main.py").read_text(encoding="utf-8")
    assert "from ALU_Gauntlet.main import runner" in source
    for cog in ("player", "defense", "challenges", "competition", "staff", "season", "administration", "help", "system", "operations", "dashboard_setup_bridge", "tournament", "asphalt_account"):
        assert f"ALU_Gauntlet.cogs.{cog}" in package_source


def test_tournament_advancement_guards_are_present():
    source = (ROOT / "ALU_Gauntlet" / "cogs" / "tournament.py").read_text(encoding="utf-8")
    required = (
        "Bracket advancement target is invalid.",
        "Winner has already advanced to the target match.",
        "Bracket advancement target is already occupied.",
        "empty_index = slots.index(None)",
        "target_match[\"player_slots\"] = slots",
    )
    failed = [item for item in required if item not in source]
    assert not failed, failed


def test_double_elimination_losers_bracket_structure():
    from ALU_Gauntlet.core.tournament import generate_tournament_bracket

    expected_counts = {
        4: [1, 1],
        8: [2, 2, 1, 1],
        16: [4, 4, 2, 2, 1, 1],
        32: [8, 8, 4, 4, 2, 2, 1, 1],
    }
    for entrant_count, counts in expected_counts.items():
        bracket = generate_tournament_bracket("double_elimination", entrant_count)
        actual = [len(group["matches"]) for group in bracket["losers"]]
        assert actual == counts
        assert bracket["winners"][-1]["matches"][0]["winner_to"] == "GF-M1"
        assert bracket["winners"][-1]["matches"][0]["loser_to"] == f"LB-R{len(counts)}-M0"
        if len(bracket["winners"]) > 2:
            assert bracket["winners"][1]["matches"][0]["loser_to"] == "LB-R3-M0"

def test_tournament_result_paths_cover_all_bracket_sections():
    discord_source = (ROOT / "ALU_Gauntlet" / "cogs" / "tournament.py").read_text(encoding="utf-8")
    web_source = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    js_source = (ROOT / "ALU_Gauntlet" / "web" / "static" / "tournaments.js").read_text(encoding="utf-8")
    for source in (discord_source, web_source, js_source):
        for marker in ("grand_final", "grand_final_reset", "losers"):
            assert marker in source
    assert "tournament_admin_role_id" in web_source
    assert "can_manage_results" in web_source
    assert '"standings":t.get("standings")' in discord_source
    assert '/api/tournaments/start' in js_source
    assert 'id="start-tournament"' in js_source


def test_global_web_shell_contract_is_consistent():
    server = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    css = (ROOT / "ALU_Gauntlet" / "web" / "static" / "app.css").read_text(encoding="utf-8")
    admin = (ROOT / "ALU_Gauntlet" / "web" / "static" / "admin.html").read_text(encoding="utf-8")
    assert '"discord":"https://discord.gg/fmFk8Ejf2H"' in server
    assert '"cashapp":"https://cash.app/"' in server
    assert 'self._merge_branding({})' in server
    assert 'calendar_markup + companion_markup' in server
    assert '/assets/icons/matches.png' in server
    assert '/assets/icons/results.png' in server
    assert '/assets/rsl-shield.svg' not in admin
    assert '.top-nav>.rsl-profile-nav' in css
    assert '.top-nav>.rsl-search-trigger' in css


def test_web_route_and_shell_regressions_are_fixed():
    server = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    calendar = (ROOT / "ALU_Gauntlet" / "web" / "static" / "calendar.html").read_text(encoding="utf-8")
    assert 'self.app.router.add_get("/gauntlet/references/", self.gauntlet_references_page)' in server
    assert 'self.app.router.add_get("/tournaments/matches/", self.tournament_matches_page)' in server
    assert '</div>\\n    <div class="calendar-personal-actions">' not in calendar
    assert '</div>\\n    <section class="calendar-personal-panel">' not in calendar


def test_notification_delivery_index_matches_multi_phase_reminders():
    source = (ROOT / "ALU_Gauntlet" / "main.py").read_text(encoding="utf-8")
    assert '[("event_id", 1), ("user_id", 1), ("lead_days", 1)]' in source
    assert 'drop_index("uniq_notification_delivery")' in source
    notifications = (ROOT / "ALU_Gauntlet" / "cogs" / "notifications.py").read_text(encoding="utf-8")
    assert 'lead_days:g' in notifications
    assert 'event_id' in notifications and 'user_id' in notifications
