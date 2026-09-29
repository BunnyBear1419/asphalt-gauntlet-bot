from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_match_assistant_is_loaded_and_uses_deadline_windows():
    main = (ROOT / "ALU_Gauntlet" / "main.py").read_text(encoding="utf-8")
    cog = (ROOT / "ALU_Gauntlet" / "cogs" / "match_assistant.py").read_text(encoding="utf-8")
    assert "ALU_Gauntlet.cogs.match_assistant" in main
    assert "active_challenges" in cog
    assert "expires_at" in cog
    assert "24 * 3600" in cog
    assert "6 * 3600" in cog
    assert "3600" in cog
    assert "notification_deliveries" in cog
    assert "Open Match Center" in cog


def test_support_is_not_duplicated_as_a_web_ticket_system():
    rules = (ROOT / "ALU_Gauntlet" / "web" / "static" / "rules.html").read_text(encoding="utf-8")
    help_page = (ROOT / "ALU_Gauntlet" / "web" / "static" / "help.html").read_text(encoding="utf-8")
    assert "official RSL support process" in rules
    assert "RSL DISCORD" in rules
    assert "official RSL staff/support process" in help_page


def test_command_center_record_sorting_is_valid_javascript_shape():
    script = (ROOT / "ALU_Gauntlet" / "web" / "static" / "rsl-command-center.js").read_text(encoding="utf-8")
    assert "byWins=[...players].sort" in script
    assert "byStreak=[...players].sort" in script
    assert "||0)]," not in script
