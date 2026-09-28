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
