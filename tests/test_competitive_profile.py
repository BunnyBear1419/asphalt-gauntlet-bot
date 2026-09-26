"""Regression checks for the RSL competitive profile direction."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
PLAYER = ROOT / "ALU_Gauntlet" / "web" / "static" / "player.html"
PLAYER_JS = ROOT / "ALU_Gauntlet" / "web" / "static" / "player.js"
HELP = ROOT / "ALU_Gauntlet" / "web" / "static" / "help.html"
TOURNAMENTS = ROOT / "ALU_Gauntlet" / "web" / "static" / "tournaments.html"
PROFILE = ROOT / "ALU_Gauntlet" / "web" / "static" / "profile.html"


def test_competitive_apis_are_registered():
    server = SERVER.read_text(encoding="utf-8")
    assert 'add_get("/api/competition/snapshot"' in server
    assert 'add_get("/api/competition/recent-matches"' in server
    assert 'add_get("/api/player/career"' in server


def test_player_dashboard_is_not_a_garage_tracker():
    page = PLAYER.read_text(encoding="utf-8")
    assert "Competitive Snapshot" in page
    assert "My Garage" not in page
    assert "Garage PI</span>" not in page


def test_player_dashboard_consumes_competitive_snapshot():
    script = PLAYER_JS.read_text(encoding="utf-8")
    assert '/api/competition/snapshot?guild_id=' in script
    for marker in ("snapshot-elo", "snapshot-record", "snapshot-streak", "snapshot-defense", "snapshot-season"):
        assert marker in script


def test_competitive_profile_labels_are_consistent_across_site():
    assert "My Garage" not in HELP.read_text(encoding="utf-8")
    assert "My Garage" not in TOURNAMENTS.read_text(encoding="utf-8")
    assert "My Garage" not in PROFILE.read_text(encoding="utf-8")
    help_page = HELP.read_text(encoding="utf-8")
    tournaments_page = TOURNAMENTS.read_text(encoding="utf-8")
    profile_page = PROFILE.read_text(encoding="utf-8")
    assert "OPEN COMPETITIVE PROFILE" in help_page
    assert "Open Competitive Profile" in tournaments_page
    assert "Competitive Profile" in profile_page
