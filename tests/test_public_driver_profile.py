from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
PAGE = ROOT / "ALU_Gauntlet" / "web" / "static" / "public-profile.html"
SCRIPT = ROOT / "ALU_Gauntlet" / "web" / "static" / "public-profile.js"

def test_public_driver_profile_contract():
    server = SERVER.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'add_get("/profile", self.profile_page)' in server
    assert 'add_get("/api/players/{user_id}", self.player_detail)' in server
    assert 'public-profile.html' in server
    assert 'public_player = {' in server
    assert '"rsl_coins"' not in server[server.index('public_player = {'):server.index('return web.json_response({"player": public_player})')]
    assert '"timezone"' not in server[server.index('public_player = {'):server.index('return web.json_response({"player": public_player})')]

    assert 'PUBLIC DRIVER PROFILE' in page
    assert 'Private settings, timezone, tickets, coin balance, and account controls are not shown' in page
    assert '/api/players/' in script
    assert 'xp_total' in script


def test_player_directory_routes_to_public_profile():
    app = (ROOT / "ALU_Gauntlet" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'window.location.href="/profile?user_id="' in app
    assert 'TIMEZONE</small>' not in app


def test_public_profile_links_are_reused_across_player_surfaces():
    leaderboard = (ROOT / "ALU_Gauntlet" / "web" / "static" / "gauntlet-leaderboard.html").read_text(encoding="utf-8")
    matches = (ROOT / "ALU_Gauntlet" / "web" / "static" / "tournament-matches.js").read_text(encoding="utf-8")
    clubs = (ROOT / "ALU_Gauntlet" / "web" / "static" / "clubs.js").read_text(encoding="utf-8")

    assert 'p.user_id||p.id' in leaderboard
    assert '/profile?user_id=' in leaderboard
    assert '/profile?user_id=' in matches
    assert 'data-player-profile' in clubs
    assert 'window.location.href="/profile?user_id="' in clubs
    assert 'openPlayerProfile(b.dataset.playerProfile)' not in clubs


def test_tournament_results_link_individual_drivers():
    results = (ROOT / "ALU_Gauntlet" / "web" / "static" / "tournament-results.html").read_text(encoding="utf-8")
    assert 'x.entrant_id' in results
    assert 't.champion_id' in results
    assert 'm.player_slots?.[0]' in results
    assert '/profile?user_id=' in results
