from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "ALU_Gauntlet" / "web" / "static"
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"


def test_rsl_documentation_sections_exist():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    help_page = (STATIC / "help.html").read_text(encoding="utf-8")
    legal = (STATIC / "legal.html").read_text(encoding="utf-8")
    rules = (STATIC / "rules.html").read_text(encoding="utf-8")
    server = SERVER.read_text(encoding="utf-8")

    assert "ABOUT US" in index
    assert "WHAT RSL PROVIDES" in index
    assert "/rules" in index
    assert "HELP CENTER" in help_page
    assert "Frequently Asked Questions" in help_page
    assert "Tickets, Refreshes &amp; Daily Reset" in help_page
    assert "User Content &amp; Tournament Media" in legal
    assert "/rules" in legal
    assert "RULES CENTER" in rules
    assert "Gauntlet Rules" in rules
    assert "Tournament Rules" in rules
    assert "Fair Play &amp; Exploits" in rules
    assert 'add_get("/rules", self.rules_page)' in server
    assert "Rules" in server
    assert '<a href="/rules">Rules</a><span aria-hidden="true">|</span>\n       <a href="/help">Help Center</a>' not in server
    assert '<a href="/calendar">' in server
    assert "calendar_markup + rules_markup + companion_markup" in server
    assert "r'<a\\\\b[^>]*href=" not in server
    assert "r'<a\\b[^>]*href=[\"\\\']/rules" in server
    assert rules.count('<a href="/rules">') == 1
