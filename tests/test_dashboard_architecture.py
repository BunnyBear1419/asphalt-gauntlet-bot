"""Static regression tests for the dashboard-first command/UI architecture."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ALU_Gauntlet"
CORE = PACKAGE / "core" / "core.py"


def _source() -> str:
    return CORE.read_text(encoding="utf-8")


def _top_commands() -> dict[str, tuple[Path, str]]:
    found: dict[str, tuple[Path, str]] = {}
    for path in (PACKAGE / "cogs").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                text = ast.unparse(decorator)
                match = re.search(r'app_commands\.command\(name=[\'\"]([^\'\"]+)', text)
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
                match = re.search(r'(\w+)_group\.command\(name=[\'\"]([^\'\"]+)', text)
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
        "dbcheck", "backup", "diagnostics", "launchcheck", "setimage", "setup", "timezone", "delete_id",
        "identity", "sync",
    }

    source = _source()
    assert 'required_commands = {"dashboard", "staff"}' in source
    assert 'COMMAND_ARCHITECTURE_VERSION = 11' in source


def test_every_non_public_top_level_command_is_explicitly_hidden():
    commands = set(_top_commands())
    public = {"dashboard", "staff"}
    hidden_match = re.search(r'HIDDEN_PLAYER_COMMANDS = \{(.*?)\n\}', _source(), re.S)
    hidden_staff_match = re.search(r'HIDDEN_STAFF_COMMANDS = \{(.*?)\n\}', _source(), re.S)
    assert hidden_match and hidden_staff_match
    hidden = set(re.findall(r'"([a-zA-Z0-9_]+)"', hidden_match.group(1))) | set(re.findall(r'"([a-zA-Z0-9_]+)"', hidden_staff_match.group(1)))
    assert commands - public == (hidden - {"season", "admin"})
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
    # Player navigation is exactly five buttons; Discord allows five buttons per row.
    player_nav = source[source.index("class DashboardView"):source.index("async def send_dashboard")]
    assert player_nav.count('row=2') == 5
    # Staff navigation uses three row-2 buttons; the separate Next Task button is also row 2, for four total.
    staff_nav = source[source.index("class StaffDashboardView"):source.index("class StaffCategorySelect")]
    assert staff_nav.count('row=2') == 3
    next_task = source[source.index("class StaffNextTaskButton"):source.index("class StaffDashboardView")]
    assert next_task.count('row=2') == 1


def test_dashboard_refresh_and_nested_home_edit_in_place():
    source = _source()
    assert 'await send_dashboard(interaction, edit=True)' in source
    assert 'await send_admin_dashboard(interaction, edit=True)' in source
    assert 'await self.refresh_current(interaction)' in source
    assert source.count("async def refresh_current") == 2


def test_all_player_dms_use_the_single_notification_helper():
    source = _source()
    assert source.count("async def send_player_dm") == 1
    assert "app_commands.command(name='notifications'" not in (PACKAGE / "cogs" / "player.py").read_text(encoding="utf-8")
    # Direct user/member DM sends should not bypass delivery logging/preference handling.
    assert ".send(embed=dm_embed)" not in source
    assert ".send(embed=dm_success)" not in source
    assert "defender_user.send" not in source
    assert "await send_player_dm(" in source
    assert 'respect_reminder_preference=True' in source


def test_no_obsolete_dashboard_aliases_or_unreachable_duplicate_actions():
    source = _source()
    assert "register_wizard" not in source
    assert "submitmatch_direct" in source
    assert "register_wizard" not in source
    duplicate_clear = 'await interaction.response.send_message(embed=discord.Embed(title="🧹 CLEAR HISTORY"'
    assert source.count(duplicate_clear) == 1


def test_launch_readiness_uses_current_command_architecture_version():
    source = _source()
    assert 'Guild command cleanup is not verified for architecture v5' not in source
    assert 'COMMAND_ARCHITECTURE_VERSION}' in source


def test_component_error_handler_matches_discord_view_signature():
    source = _source()
    assert 'async def _view_error_handler(view, interaction: discord.Interaction, error: Exception, item):' in source


def test_player_staff_button_replaces_dashboard_in_place():
    source = _source()
    start = source.index('async def open_staff(interaction):')
    block = source[start:source.index('back.callback = go_back', start)]
    assert 'await send_admin_dashboard(interaction, edit=True)' in block


def test_whatnext_recognizes_processing_matches():
    source = _source()
    player = (PACKAGE / 'cogs' / 'player.py').read_text(encoding='utf-8')
    assert '"status": {"$in": ["active", "processing"]}' in player or "'status': {'$in': ['active', 'processing']}" in player


def test_registration_wizard_uses_one_canonical_submission_path():
    source = _source()
    assert "async def submit_registration_application(" in source
    assert 'await submit_registration_application(original, state["game_id"], state["pi"], attachment, choice)' in source
    assert 'invoke_hidden_command(original, "register", state["game_id"]' not in source


def test_review_message_reconciliation_searches_embed_text():
    source = _source()
    block = source[source.index("async def find_recent_bot_message"):source.index("async def send_admin_alert")]
    assert 'getattr(message, "embeds"' in block
    assert 'getattr(getattr(embed, "footer"' in block
    assert "marker in text" in block


def test_manual_full_sync_records_current_command_architecture_version():
    admin = (PACKAGE / "cogs" / "administration.py").read_text(encoding="utf-8")
    system = (PACKAGE / "cogs" / "system.py").read_text(encoding="utf-8")
    for source in (admin, system):
        assert "command_architecture_version" in source
        assert "COMMAND_ARCHITECTURE_VERSION" in source


def test_public_dashboards_are_guild_only():
    player = (PACKAGE / "cogs" / "player.py").read_text(encoding="utf-8")
    staff = (PACKAGE / "cogs" / "staff.py").read_text(encoding="utf-8")
    assert "@app_commands.guild_only()\n    @app_commands.command(name='dashboard'" in player
    assert "@app_commands.guild_only()\n    @app_commands.command(name='staff'" in staff


def test_notification_panel_initial_state_is_truthful():
    source = _source()
    assert "def __init__(self, owner_id: int, enabled: bool = True)" in source
    assert "self.on.disabled = self.enabled" in source
    assert "self.off.disabled = not self.enabled" in source
    assert "NotificationsView(interaction.user.id, current)" in source


def test_dm_proof_sessions_cannot_be_ambiguous_across_guilds():
    source = _source()
    assert "Keep exactly one live proof" in source
    assert "for existing_key, existing_session in list(pending_proof_sessions.items())" in source
    assert "pending_proof_sessions.pop(existing_key, None)" in source


def test_dashboard_matchmaking_enforces_cooldown_even_when_hidden_callback_bypasses_discord_decorator():
    source = _source()
    assert 'last_challenge_started_at' in source
    assert 'COOLDOWN:' in source
    assert 'Matchmaking cooldown' in source


def test_transactional_decisions_surface_dm_delivery_failures_to_staff():
    source = _source()
    assert "Defense was approved successfully, but the player's DM could not be delivered" in source
    assert "Defense rejection was saved, but the player's DM could not be delivered" in source
    assert "Registration was approved successfully, but the applicant's DM could not be delivered" in source
    assert "The applicant could not be reached by DM" in source


def test_profile_and_stats_are_one_canonical_player_action():
    source = _source()
    operations = (PACKAGE / "cogs" / "operations.py").read_text(encoding="utf-8")
    player = (PACKAGE / "cogs" / "player.py").read_text(encoding="utf-8")
    hidden = re.search(r'HIDDEN_PLAYER_COMMANDS = \{(.*?)\n\}', source, re.S).group(1)
    assert '"📈 My Stats"' not in source
    assert '"stats"' not in hidden
    assert '@app_commands.command(name="stats"' not in operations
    assert 'Profile & Stats' in source
    assert 'Career Performance' in player


def test_transactional_dm_failures_alert_staff_and_are_logged():
    source = _source()
    assert 'alert_staff_on_failure: bool = False' in source
    assert 'PLAYER DM DELIVERY FAILED' in source
    assert 'alert_staff_on_failure=True' in source
    assert 'failure_context="Reference approval notice"' in source


def test_match_completion_dm_failure_is_reported_without_changing_settlement():
    source = (PACKAGE / "cogs" / "challenges.py").read_text(encoding="utf-8")
    assert 'failure_context="Match completion notice"' in source
    assert 'the match was settled successfully' in source.lower()


def test_nested_staff_ui_rechecks_current_authorization():
    source = _source()
    assert 'async def require_staff_interaction' in source
    for marker in ('class StaffSeasonAutoView', 'class PlayerChangesView', 'class TimezoneSelectView', 'class AdminImageTypeView', 'class ClearHistorySelectView', 'class SeasonResetChoiceView'):
        pos=source.index(marker); end=source.find('\nclass ',pos+6); block=source[pos:end if end!=-1 else len(source)]
        assert 'require_staff_interaction(interaction)' in block
    for marker in ('class AdminSetPIModal','class SeasonScheduleModal','class SetupChannelsModal','class SetupRolesModal','class IdentityModal','class StaffMemberTargetModal','class RegistrationDeclineModal'):
        pos=source.index(marker); end=source.find('\nclass ',pos+6); block=source[pos:end if end!=-1 else len(source)]
        assert 'require_staff_interaction(interaction)' in block


def test_root_entrypoint_delegates_to_single_canonical_runner():
    main=(ROOT/'main.py').read_text(encoding='utf-8'); package=(PACKAGE/'main.py').read_text(encoding='utf-8')
    assert 'from ALU_Gauntlet.main import runner' in main
    assert 'async def runner' in package
    assert 'EXTENSIONS' in package


def test_on_ready_cleanup_records_current_command_architecture_version():
    source = _source()
    marker = 'async def on_ready():'
    block = source[source.index(marker):source.index('async def on_error', source.index(marker))]
    assert '"guild_overrides_cleaned": True' in block
    assert '"command_architecture_version": COMMAND_ARCHITECTURE_VERSION' in block


def test_transactional_notification_failures_alert_staff_consistently():
    source = _source()
    for context in (
        'Defense rejection notice',
        'Registration rejection notice',
        'Reference rejection notice',
    ):
        assert f'failure_context="{context}"' in source
        assert 'alert_staff_on_failure=True' in source


def test_registration_approval_notification_uses_actual_saved_elo():
    source = _source()
    block = source[source.index('class VerificationView'):source.index('class ChallengeDropdown')]
    assert 'approved_profile = await bot.db.drivers.find_one' in block
    assert 'approved_elo = int((approved_profile or {}).get("elo", 1000))' in block
    assert 'name="📈 Current ELO"' in block
    assert 'name="Assigned Base ELO"' not in block


def test_player_dm_helper_rejects_empty_notifications():
    source = _source()
    block = source[source.index('async def send_player_dm'):source.index('@tasks.loop(hours=6)', source.index('async def send_player_dm'))]
    assert 'if content is None and embed is None:' in block
    assert 'PLAYER_DM_INVALID' in block


def test_module_level_discord_handlers_are_explicitly_registered():
    source = _source()
    assert "bot.event(on_message)" in source
    assert "bot.event(on_ready)" in source
    assert "bot.event(on_guild_join)" in source
    assert "bot.event(on_error)" in source
    assert "bot.tree.on_error = on_app_command_error" in source
    # Guard against the exact failure mode this test is designed to prevent:
    # registration must occur after all referenced handlers are defined.
    assert source.index("async def on_error(") < source.index("bot.event(on_error)")
    assert source.index("async def on_app_command_error(") < source.index("bot.tree.on_error = on_app_command_error")


def test_match_reconciliation_restores_post_settlement_lap_time_writes():
    source = _source()
    assert '"season_number": current_season' in source
    assert 'async def _reconcile_match_lap_times(match: dict):' in source
    block = source[source.index('async def reconcile_processing_challenges'):source.index('async def get_current_season_number')]
    assert 'await _reconcile_match_lap_times(match)' in block
    assert 'source="match_attack"' in source


def test_v18_setup_roles_are_named_and_image_upload_is_staff_channel_based():
    source = _source()
    assert 'label="Staff role name"' in source
    assert 'label="Player role name"' in source
    assert 'ensure_named_server_role' in source
    assert 'pending_staff_image_sessions = {}' in source
    assert 'handle_pending_staff_image_message' in source
    assert 'source_channel_id' in source
    assert 'Upload {name}' in source


def test_v18_season_disable_is_danger_and_health_diagnostics_is_canonical_data_action():
    source = _source()
    assert '@discord.ui.button(label="🔴 Disable", style=discord.ButtonStyle.danger)' in source
    data_block = source[source.index('"data": ['):source.index('"setup": [')]
    assert data_block.count('"diagnostics"') == 1
    system_block = source[source.index('"system": ['):source.index('class StaffCategorySelect')]
    assert system_block.count('"diagnostics"') == 0
