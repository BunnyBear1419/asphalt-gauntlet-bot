from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / "ALU_Gauntlet" / "core" / "setup_wizard.py"
ADMIN = ROOT / "ALU_Gauntlet" / "cogs" / "administration.py"


def _source(path):
    return path.read_text(encoding="utf-8")


def _tree(path):
    return ast.parse(_source(path))


def _function_source(path, name):
    source = _source(path)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"missing function: {name}")


def _class_source(path, name):
    source = _source(path)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"missing class: {name}")


def test_setup_wizard_has_one_canonical_configuration_schema():
    source = _source(WIZARD)
    tree = _tree(WIZARD)
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SETUP_FIELDS" for target in node.targets)
    )
    fields = [elt.value for elt in assignment.value.elts]
    assert fields == [
        "registration_channel_id",
        "review_channel_id",
        "log_channel_id",
        "announcement_channel_id",
        "match_results_channel_id",
        "admin_role_id",
        "player_role_id",
        "timezone",
    ]
    assert "CHANNEL_FIELDS" in source
    assert "ROLE_FIELDS" in source


def test_setup_uses_native_channel_and_role_pickers():
    source = _source(WIZARD)
    assert "discord.ui.ChannelSelect" in source
    assert "channel_types=[discord.ChannelType.text]" in source
    assert "discord.ui.RoleSelect" in source
    assert "Select a text channel" in source
    assert "Select a server role" in source


def test_setup_timezone_is_a_paged_native_dropdown():
    source = _class_source(WIZARD, "TimezoneWizardView")
    assert "discord.ui.Select" in source
    assert "TIMEZONE_CHOICES[self.page * 25:(self.page + 1) * 25]" in source
    assert "label[:100]" in source
    assert "Previous" in source
    assert "Next" in source


def test_setup_is_guild_and_user_scoped():
    source = _class_source(WIZARD, "SetupWizard")
    assert "self.guild_id = str(interaction.guild_id)" in source
    assert "self.owner_id = interaction.user.id" in source
    owns = _function_source(WIZARD, "owns")
    assert "interaction.guild_id" in owns
    assert "interaction.user.id == self.owner_id" in owns


def test_setup_ui_never_requires_manual_ids_or_timezone_text():
    main = _function_source(WIZARD, "build_main_embed")
    assert "No channel IDs, role IDs, or timezone strings need to be entered manually." in main
    assert "Channel IDs" in main
    assert "Role IDs" in main
    assert "timezone strings" in main
    assert "registration_channel_id" not in main
    assert "admin_role_id" not in main


def test_setup_review_uses_discord_mentions_instead_of_raw_ids():
    source = _function_source(WIZARD, "build_review_embed")
    assert ".mention" in source
    assert "registration_channel_id" in source
    assert "admin_role_id" in source
    assert "no raw Discord IDs are exposed" in source
    assert "timezone" in source


def test_setup_validates_bot_channel_permissions():
    source = _function_source(WIZARD, "_channel_changed")
    assert "permissions_for(me)" in source
    assert "permissions.view_channel" in source
    assert "permissions.send_messages" in source
    assert "I can't use that channel" in source


def test_setup_rejects_everyone_and_managed_roles():
    source = _function_source(WIZARD, "_role_changed")
    assert "role.is_default()" in source
    assert "role.managed" in source
    assert "not @everyone or a managed role" in source


def test_setup_does_not_save_until_review_save():
    main = _class_source(WIZARD, "SetupWizardView")
    review = _class_source(WIZARD, "SetupReviewView")
    assert "update_one" not in main
    assert "update_one" in review
    assert "await interaction.response.defer()" in review
    assert "SETUP_FIELDS" in review


def test_setup_cancel_does_not_write_configuration():
    source = _function_source(WIZARD, "cancel")
    assert "interaction.response.edit_message" in source
    assert "update_one" not in source
    assert "view=None" in source


def test_setup_loads_existing_configuration_without_requiring_manual_reentry():
    source = _function_source(WIZARD, "launch_setup_wizard")
    assert "bot.db.settings.find_one" in source
    assert "SETUP_FIELDS" in source
    assert "wizard.values[key] = existing[key]" in source


def test_setup_save_initializes_guild_scoped_season_state():
    source = _function_source(WIZARD, "save")
    assert 'f"guild_{guild_id}"' in source
    assert "season_state.find_one" in source
    assert "season_state.update_one" in source
    assert "guild_id" in source


def test_setup_has_staff_authorization_on_every_interactive_path():
    source = _source(WIZARD)
    assert "require_staff_interaction" in source
    for name in (
        "channels", "roles", "timezone", "review", "cancel",
        "_target_changed", "_channel_changed", "_back", "_role_changed",
        "_select", "_previous", "_next", "save",
    ):
        function = _function_source(WIZARD, name)
        assert "_authorized" in function, f"missing authorization guard in {name}"


def test_setup_command_is_the_single_configuration_entry_point():
    source = _source(ADMIN)
    tree = _tree(ADMIN)
    setup_commands = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "setup_cmd"
    ]
    assert len(setup_commands) == 1
    setup = _function_source(ADMIN, "setup_cmd")
    assert "launch_setup_wizard(interaction)" in setup
    assert "no IDs to enter" in source
    assert "@app_commands.command(name='timezone'" not in source
    assert "@app_commands.command(name=\"timezone\"" not in source


def test_setup_command_requires_administrator_or_configured_admin_role():
    source = _function_source(ADMIN, "setup_cmd")
    assert "guild_permissions.administrator" in source
    assert "check_admin_privileges(interaction)" in source
    assert "Access Denied" in source


def test_setup_cleans_stale_guild_local_setup_overrides_once():
    source = _function_source(ADMIN, "on_ready")
    assert "_setup_override_cleanup_done" in source
    assert "fetch_commands(guild=guild)" in source
    assert "remove_command(\"setup\", guild=guild)" in source
    assert "sync(guild=guild)" in source
    assert "bot._setup_override_cleanup_done = True" in source


def test_setup_version_bumped_for_command_architecture_change():
    source = _source(ADMIN)
    assert "COMMAND_ARCHITECTURE_VERSION = 12" in source
