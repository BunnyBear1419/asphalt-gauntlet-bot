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


def test_tournament_media_upload_is_bounded_and_private():
    text = SERVER.read_text(encoding="utf-8")
    assert "max_size = 12 * 1024 * 1024" in text
    assert "if len(data) > max_size" in text
    assert 'Cache-Control":"private, max-age=3600' in text
    assert 'X-Content-Type-Options":"nosniff' in text


def test_language_preference_is_account_scoped():
    text = SERVER.read_text(encoding="utf-8")
    assert 'add_get("/api/language", self.get_language)' in text
    assert 'add_post("/api/language", self.set_language)' in text
    assert 'web_user_preferences.find_one({"_id": str(user.user_id)})' in text
    assert '{"language": language, "updated_at": time.time()}' in text

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


def test_tournament_result_submission_modes_are_configurable_and_enforced():
    server = SERVER.read_text(encoding="utf-8")
    cog = COG.read_text(encoding="utf-8")
    tournaments = TOURNAMENTS.read_text(encoding="utf-8")
    page = (ROOT / "ALU_Gauntlet" / "web" / "static" / "tournaments.html").read_text(encoding="utf-8")
    assert '"result_submission_mode": result_submission_mode' in server
    assert 'result_mode = str(t.get("result_submission_mode") or "player_review").casefold()' in server
    assert 'This tournament is configured for Admin Only result submission.' in server
    assert 'result_mode = str(tournament.get("result_submission_mode") or "player_review").casefold()' in cog
    assert 'Admin Only result submission' in cog
    assert 'name="result_submission_mode"' in page
    assert 'value="admin_only"' in page
    assert 'result_submission_mode_label' in server
    assert 't.result_submission_mode' in tournaments


def test_admin_only_result_submission_advances_without_second_manual_review():
    cog = COG.read_text(encoding="utf-8")
    tournaments = TOURNAMENTS.read_text(encoding="utf-8")
    assert 'if result_mode == "admin_only":' in cog
    assert 'verify_match_on_discord(self.tournament_id, self.match_id, "approve", interaction.user.id)' in cog
    assert 'const verified=await api("/api/tournaments/result/verify"' in tournaments
    assert 'action:"approve"' in tournaments
    assert 'Admin result entry: the submitted winner will be recorded and the bracket advanced immediately.' in tournaments


def test_player_review_result_submission_still_requires_staff_verification():
    server = SERVER.read_text(encoding="utf-8")
    cog = COG.read_text(encoding="utf-8")
    assert 'result_status":"pending"' in server
    assert 'result_status":"pending"' in cog
    assert 'Result submitted for staff verification.' in server
    assert 'Staff verification is required before the bracket advances.' in cog


def test_tournament_center_covers_team_sizes_and_staff_workflows():
    page = (ROOT / "ALU_Gauntlet" / "web" / "static" / "tournaments.html").read_text(encoding="utf-8")
    assert 'value="2">2v2 Teams' in page
    assert 'value="3">3v3 Teams' in page
    assert 'value="4">4v4 Teams' in page
    assert 'value="player_review"' in page
    assert 'value="admin_only"' in page
    assert "Admin Only is useful for streamed or closely supervised tournaments." in page


def test_completed_tournament_archive_exposes_champion_standings_history_and_media():
    page = RESULTS.read_text(encoding="utf-8")
    assert "TOURNAMENT CHAMPION" in page
    assert "Final Standings" in page
    assert "Round-by-Round Results" in page
    assert "Tournament Media" in page
    assert "Open Live Bracket" in page


def test_media_and_result_permissions_have_server_side_guards():
    server = SERVER.read_text(encoding="utf-8")
    assert "await self.require_user(request)" in server
    assert "Only tournament participants or tournament staff can upload media." in server
    assert "if not staff and not participant:" in server or "if not staff and not participant" in server
    assert "This tournament is configured for Admin Only result submission." in server


def test_tournament_admin_documentation_exists():
    guide = (ROOT / "docs" / "TOURNAMENT_ADMIN_GUIDE.md").read_text(encoding="utf-8")
    maintenance = (ROOT / "docs" / "PRODUCTION_MAINTENANCE.md").read_text(encoding="utf-8")
    for phrase in ("Admin Only", "Player Submission + Admin Verification", "Pending Approval", "2v2", "3v3", "4v4"):
        assert phrase in guide
    for phrase in ("Discloud-first", "unique active player registration", "Calendar navigation", "CI is green"):
        assert phrase in maintenance
