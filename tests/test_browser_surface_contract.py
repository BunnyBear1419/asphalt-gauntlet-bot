from pathlib import Path
ROOT=Path(__file__).parents[1]; STATIC=ROOT/"ALU_Gauntlet"/"web"/"static"
def read(name): return (STATIC/name).read_text(encoding="utf-8")
def test_club_create_surface():
    page,script=read("clubs.html"),read("clubs.js")
    assert 'id="open-create"' in page and 'id="club-form"' in page
    assert '$("#open-create").onclick' in script and '$("#club-form").onsubmit' in script
    assert '"/api/clubs"' in script and 'method:"POST"' in script
def test_player_settings_surface():
    page,script=read("player.html"),read("player.js")
    assert 'href="/profile"' in page and 'href="/player/settings"' in page
    assert 'id="save-profile"' in page and '"/api/player/profile?guild_id="' in script
def test_admin_surface():
    page=read("admin.html")
    for token in ('id="section-server-control"','id="create-server-channel"','id="create-server-role"','id="save-bot-identity"','loadServerControl','/api/admin/server-control/'):
        assert token in page
def test_navigation_and_support_targets():
    page=read("clubs.html")+read("player.html")+read("admin.html")
    assert 'href="/clubs"' in page and 'href="/rules"' in page
    assert "https://discord.gg/q46RQxu2fm" in page or "https://discord.gg/fmFk8Ejf2H" in page
