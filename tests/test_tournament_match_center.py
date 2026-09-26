"""Regression checks for the live tournament match center."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ALU_Gauntlet" / "web" / "static" / "tournament-matches.html"
SCRIPT = ROOT / "ALU_Gauntlet" / "web" / "static" / "tournament-matches.js"


def test_tournament_match_center_uses_dedicated_client():
    page = PAGE.read_text(encoding="utf-8")
    assert "/static/tournament-matches.js?v=20260926-matchcenter1" in page


def test_tournament_match_center_renders_live_bracket_states():
    script = SCRIPT.read_text(encoding="utf-8")
    for marker in ("PENDING REVIEW", "VERIFIED", "READY", "Grand Final", "Submit Result"):
        assert marker in script


def test_tournament_match_center_consumes_tournament_and_result_apis():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "/api/tournaments/" in script
    assert "/api/tournaments/result" in script
    assert "/api/me" in script


def test_tournament_match_center_supports_winners_losers_and_grand_final():
    script = SCRIPT.read_text(encoding="utf-8")
    assert '"rounds","winners","losers"' in script
    assert "grand_final" in script
    assert "grand_final_reset" in script
