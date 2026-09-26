"""Regression checks for the completed Tournament Center and media archive."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
TOURNAMENTS = ROOT / "ALU_Gauntlet" / "web" / "static" / "tournaments.js"
RESULTS = ROOT / "ALU_Gauntlet" / "web" / "static" / "tournament-results.html"
PLAYER = ROOT / "ALU_Gauntlet" / "web" / "static" / "player.js"
COG = ROOT / "ALU_Gauntlet" / "cogs" / "tournament.py"

def test_tournament_completion_apis_are_registered():
    text = SERVER.read_text(encoding="utf-8")
    assert 'add_get("/api/tournaments/results"' in text
    assert 'add_get("/api/tournaments/{tournament_id}/media"' in text
    assert 'add_post("/api/tournaments/media"' in text
    assert 'add_post("/api/tournaments/media/action"' in text
    assert 'add_get("/assets/tournament-media/{media_id}"' in text

def test_results_include_standings_history_and_media():
    text = SERVER.read_text(encoding="utf-8")
    assert "async def _tournament_result_payload" in text
    assert '"standings": rows' in text
    assert '"matches": [{"id"' in text
    assert 'tournament_media.count_documents' in text

def test_tournament_media_requires_approval_for_players():
    text = SERVER.read_text(encoding="utf-8")
    assert 'status = "approved" if staff else "pending"' in text
    assert "Only tournament participants or tournament staff can upload media." in text
    assert "Tournament Media Pending Approval" in text

def test_discord_media_moderation_is_persistent():
    text = COG.read_text(encoding="utf-8")
    assert "class TournamentMediaModerationView" in text
    assert "rsl_media_approve:" in text
    assert "rsl_media_reject:" in text
    assert 'bot.add_view(TournamentMediaModerationView' in text

def test_results_page_and_tournament_center_expose_media():
    results = RESULTS.read_text(encoding="utf-8")
    tournaments = TOURNAMENTS.read_text(encoding="utf-8")
    assert "Tournament Media" in results
    assert "/api/tournaments/results" in results
    assert "/api/tournaments/" in results
    assert "mediaGalleryHtml" in tournaments
    assert "/api/tournaments/media" in tournaments
    assert "media-action" in tournaments

def test_competitive_profile_links_to_tournament_results():
    text = PLAYER.read_text(encoding="utf-8")
    assert "/tournaments/results?tournament_id=" in text
    assert "career-championships" in text
