from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]
FIXES = ROOT / "ALU_Gauntlet" / "core" / "ui_fixes.py"
MAIN = ROOT / "ALU_Gauntlet" / "main.py"


def _source():
    return FIXES.read_text(encoding="utf-8")


def _function_source(name):
    source = _source()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"missing function: {name}")


def test_ui_fixes_are_installed_before_bot_start():
    source = MAIN.read_text(encoding="utf-8")
    assert "from .core.ui_fixes import install_ui_fixes" in source
    assert "install_ui_fixes()" in source


def test_dashboard_registration_action_is_routed_to_register_command():
    source = _function_source("_dashboard_run_action")
    assert 'action == "register"' in source
    assert 'invoke_hidden_command(interaction, "register")' in source


def test_defense_modal_submission_never_opens_a_second_modal_directly():
    source = _function_source("_defense_times_submit")
    assert "interaction.response.send_message" in source
    assert "interaction.response.send_modal" not in source
    assert "DefenseCarsLauncherView" in source


def test_car_modal_submission_never_opens_rank_modal_directly():
    source = _function_source("_defense_cars_submit")
    assert "interaction.response.send_message" in source
    assert "interaction.response.send_modal" not in source
    assert "DefenseRanksLauncherView" in source


def test_rank_modal_is_opened_from_a_button_interaction():
    source = _function_source("continue_to_ranks")
    assert "interaction.response.send_modal(DefenseRanksModal(self.state))" in source


def test_leaderboard_bridge_uses_the_select_component_values():
    source = _function_source("_patched_top_view_init")
    assert 'getattr(item, "custom_id", None) != "top_leaderboard_select"' in source
    assert 'getattr(_item, "values", [])' in source
    assert "self.values = list" in source
