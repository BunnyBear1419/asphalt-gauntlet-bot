import sys
from pathlib import Path
import asyncio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ALU_Gauntlet.core import core


def _project_source():
    package = ROOT / "ALU_Gauntlet"
    files = [
        ROOT / "main.py",
        package / "core" / "core.py",
        *sorted((package / "cogs").glob("*.py")),
    ]
    return "\n".join(p.read_text(encoding="utf-8") for p in files if p.is_file())


def test_division_boundaries():
    cases = [
        (0, "Division 1 — Bronze Tier"),
        (8000, "Division 1 — Bronze Tier"),
        (8001, "Division 2 — Silver Tier"),
        (11500, "Division 2 — Silver Tier"),
        (11501, "Division 3 — Gold Tier"),
        (15000, "Division 3 — Gold Tier"),
        (15001, "Division 4 — Platinum Tier"),
        (18500, "Division 4 — Platinum Tier"),
        (18501, "Division 5 — Champ Tier"),
        (22000, "Division 5 — Champ Tier"),
        (22001, "Division 6 — Legend Tier"),
        (50000, "Division 6 — Legend Tier"),
    ]
    for pi, expected in cases:
        assert expected in core.get_division_for_pi(pi)["name"]


def test_division_mongo_ranges_match_boundaries():
    for division in core.PI_DIVISIONS:
        query = core.division_mongo_query(division)
        assert query["$gte"] == division["min"]
        if division["max"] is None:
            assert "$lt" not in query
        else:
            assert query["$lt"] == division["max"]


def test_lap_time_round_trip():
    for value in [1, 999, 1000, 61523, 359999, 5999999]:
        assert core.parse_lap_time(core.format_lap_time(value)) == value


def test_lap_time_rejects_invalid_values():
    invalid = ["", "0:00.000", "1:2.345", "01:02.34", "1:60.000", "abc", "1:02.0000"]
    for value in invalid:
        assert core.parse_lap_time(value) == -1


def test_five_course_defense_validation():
    assert not core.has_5_course_defense({})
    assert not core.has_5_course_defense({"defense_locked": {"courses": []}})
    assert not core.has_5_course_defense({"defense_locked": {"courses": [1, 2, 3, 4]}})
    valid_courses = [
        {
            "track": core.ALU_TRACKS[i],
            "car": core.ALU_CARS[i],
            "ms": 60000 + i,
            "car_rank": 1,
        }
        for i in range(5)
    ]
    assert core.has_5_course_defense({"defense_locked": {"courses": valid_courses}})


def test_elo_is_bounded_and_streak_bonus_caps():
    winner, loser, bonus = core.calculate_elo_change(1000, 1000, winner_streak=100)
    assert winner >= 100
    assert loser >= 100
    assert bonus == 20


def test_elo_favors_upset_less_than_expected_win():
    equal_winner, equal_loser, _ = core.calculate_elo_change(1000, 1000)
    underdog_winner, underdog_loser, _ = core.calculate_elo_change(800, 1200)
    assert equal_winner > 1000
    assert equal_loser < 1000
    assert underdog_winner > 800
    assert underdog_loser < 1200


def test_elo_streak_bonus_only_starts_at_two():
    _, _, bonus0 = core.calculate_elo_change(1000, 1000, winner_streak=0)
    _, _, bonus1 = core.calculate_elo_change(1000, 1000, winner_streak=1)
    _, _, bonus2 = core.calculate_elo_change(1000, 1000, winner_streak=2)
    assert bonus0 == 0
    assert bonus1 == 0
    assert bonus2 == 4


class FakeResult:
    def __init__(self, modified_count):
        self.modified_count = modified_count


class FakeCollection:
    def __init__(self):
        self.docs = {}

    @staticmethod
    def _matches(doc, query):
        for key, expected in query.items():
            if key == "_id":
                continue
            actual = doc.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
                if "$eq" in expected and actual != expected["$eq"]:
                    return False
            elif actual != expected:
                return False
        return True

    async def find_one(self, query):
        doc = self.docs.get(query.get("_id"))
        if doc is None or not self._matches(doc, query):
            return None
        return dict(doc)

    async def update_one(self, query, update):
        doc = self.docs.get(query.get("_id"))
        if doc is None or not self._matches(doc, query):
            return FakeResult(0)
        for key, value in update.get("$set", {}).items():
            doc[key] = value
        for key in update.get("$unset", {}):
            doc.pop(key, None)
        return FakeResult(1)


class FakeDB:
    def __init__(self):
        self.active_challenges = FakeCollection()


def test_active_challenge_claim_and_release(monkeypatch):
    async def run():
        fake_db = FakeDB()
        monkeypatch.setattr(core.bot, "db", fake_db)
        fake_db.active_challenges.docs["guild_user"] = {
            "_id": "guild_user",
            "guild_id": "guild",
            "status": "active",
            "challenger_id": "user",
            "expires_at": __import__("time").time() + 3600,
        }

        claimed = await core.claim_active_challenge("guild", "user")
        assert claimed["status"] == "processing"
        assert fake_db.active_challenges.docs["guild_user"]["status"] == "processing"

        second_claim = await core.claim_active_challenge("guild", "user")
        assert second_claim is None

        await core.release_active_challenge("guild_user")
        assert fake_db.active_challenges.docs["guild_user"]["status"] == "active"

    asyncio.run(run())


def test_stale_processing_challenge_is_recovered(monkeypatch):
    async def run():
        fake_db = FakeDB()
        monkeypatch.setattr(core.bot, "db", fake_db)
        fake_db.active_challenges.docs["guild_user"] = {
            "_id": "guild_user",
            "guild_id": "guild",
            "status": "processing",
            "challenger_id": "user",
            "processing_at": 0,
            "expires_at": __import__("time").time() + 3600,
        }

        claimed = await core.claim_active_challenge("guild", "user")
        assert claimed["status"] == "processing"
        assert "processing_at" in claimed
        assert fake_db.active_challenges.docs["guild_user"]["status"] == "processing"

    asyncio.run(run())


def test_season_schedule_automatically_starts_and_ends():
    source = _project_source()
    assert "starts_at" in source and "ends_at" in source
    assert 'if (not bool(state.get("season_active", False)) and starts_at' in source
    assert 'now >= starts_at and now < ends_at' in source
    assert 'await announce_season_start(guild_id, season_number, reason="scheduled")' in source
    assert 'if bool(state.get("season_active", False)) and ends_at and now >= ends_at' in source


def test_seasonauto_controls_only_scheduled_end_rollover():
    source = _project_source()
    assert '@season_group.command(name=\'auto\'' in source
    assert 'app_commands.Choice(name="Enable automatic season rollover", value="on")' in source
    assert 'app_commands.Choice(name="Disable automatic season rollover", value="off")' in source
    assert 'await trigger_global_season_end(guild_id=guild_id, start_next_season=auto_rollover)' in source
    assert '"automatic_season_end": False' in source


def test_seasonstart_early_preserves_scheduled_end():
    source = _project_source()
    assert '@season_group.command(name=\'start\'' in source
    assert '"scheduled end time remains unchanged"' in source
    assert '"season_active": True' in source


def test_manual_seasonend_never_auto_rolls_next_season():
    source = _project_source()
    assert 'trigger_global_season_end(guild_id=self.guild_id,forced_interaction=interaction, start_next_season=False)' in source
    assert 'the next season will not roll over automatically' in source


def test_automatic_rollover_announces_new_season_and_preserves_schedule_duration():
    source = _project_source()
    assert 'season_duration = previous_end - previous_start' in source
    assert 'await announce_season_start(guild_id, next_season, reason="rollover")' in source
    assert '"ends_at": now + season_duration' in source


def test_help_menu_is_organized_into_player_and_admin_categories():
    # Test the actual Discord Select options instead of relying on source-code
    # quote style or where the HelpView class lives in the Cogs split.
    help_select = getattr(core, "HelpCategorySelect", None)
    assert help_select is not None, "HelpCategorySelect is missing from the production bot"

    view = help_select(is_admin=True)
    values = {option.value for option in view.options}

    expected_player = {
        "getting_started",
        "defense",
        "racing",
        "rankings",
        "account",
    }
    expected_admin = {
        "admin_setup",
        "admin_seasons",
        "admin_players",
        "admin_tools",
    }

    assert expected_player <= values
    assert expected_admin <= values

    # The dashboard-first UX should not advertise hidden slash shortcuts.
    source = _project_source()
    for command in ("/whatnext", "/submitmatch", "/missingdefense"):
        assert command not in source
    assert "/dashboard" in source
    assert "/staff" in source


def test_player_reminder_dms_are_72h_and_opt_out():
    source = _project_source()
    assert "72 * 60 * 60" in source
    assert 'respect_reminder_preference=True' in source
    assert 'dm_notifications_enabled' in source


def test_notifications_panel_controls_reminder_dms():
    source = _project_source()
    assert "class NotificationsView" in source
    assert "dm_notifications_enabled" in source
    assert "Automated reminder DMs are disabled." in source
    assert "Transactional notices" in source
    assert "app_commands.command(name='notifications'" not in source


def test_dashboard_command_surface_is_exactly_dashboard_and_staff():
    import ast

    package = ROOT / "ALU_Gauntlet"
    root_commands = set()
    group_commands = set()
    group_names = set()
    group_variables = set()
    for path in (package / "cogs").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Track both the Python variable (e.g. ``season_group``) and the
        # registered Discord group name (e.g. ``season``).  Prefix commands
        # such as ``@commands.command`` are deliberately excluded from this
        # slash-command surface audit.
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "Group"
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        group_variables.add(target.id)
                for kw in node.value.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        group_names.add(kw.value.value)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "command"):
                        continue
                    # Only app_commands decorators are part of the slash
                    # command surface.  This prevents ``@commands.command``
                    # (the recovery-only !forcesync command) from leaking
                    # into the slash-command audit.
                    if isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "commands":
                        continue
                    name = next((kw.value.value for kw in decorator.keywords if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)), None)
                    if not name:
                        continue
                    if isinstance(decorator.func.value, ast.Name) and decorator.func.value.id in group_variables:
                        group_commands.add(name)
                    else:
                        root_commands.add(name)

    hidden = set(core.HIDDEN_PLAYER_COMMANDS) | set(core.HIDDEN_STAFF_COMMANDS)
    public_root = root_commands - hidden
    public_groups = group_names - hidden
    assert public_root == {"dashboard", "staff"}
    assert public_groups == set()
    assert group_commands >= {"start", "status", "end", "history", "setpi", "removeracer"}
    assert "submitmatch" not in hidden


def test_dashboard_navigation_controls_have_no_duplicate_row_items():
    player = core.DashboardView("1", "2", False)
    staff = core.StaffDashboardView("1")

    for view in (player, staff):
        custom_ids = [getattr(item, "custom_id", None) for item in view.children if getattr(item, "custom_id", None)]
        assert len(custom_ids) == len(set(custom_ids))
        row_counts = {}
        for item in view.children:
            row = getattr(item, "row", None)
            if row is not None:
                row_counts[row] = row_counts.get(row, 0) + 1
        assert all(count <= 5 for count in row_counts.values())


def test_dashboard_uses_bound_command_bridge_for_hidden_cog_commands():
    source = _project_source()
    assert "invoke_hidden_command" in source
    assert "invoke_hidden_group_command" in source
    assert 'getattr(cmd, "binding", None)' in source
    assert '"_hidden_groups"' in source
