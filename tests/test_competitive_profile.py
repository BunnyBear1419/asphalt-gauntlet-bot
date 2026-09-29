"""Regression checks for the RSL competitive profile direction."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
PLAYER = ROOT / "ALU_Gauntlet" / "web" / "static" / "player.html"
PLAYER_JS = ROOT / "ALU_Gauntlet" / "web" / "static" / "player.js"
STATIC = ROOT / "ALU_Gauntlet" / "web" / "static"
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


def test_player_profile_and_settings_are_separate_routes():
    server=SERVER.read_text(encoding="utf-8")
    assert 'add_get("/player/profile", self.player_profile_page)' in server
    assert 'add_get("/player/settings", self.player_settings_page)' in server
    assert 'Location": "/player/profile"' in server
    player=PLAYER.read_text(encoding="utf-8")
    assert 'data-rsl-player-mode="{mode}"' in server
    assert 'My Profile' in player
    assert 'My Settings' in player
    assert 'href="/player/settings"' in player


def test_challenge_submission_requires_five_individual_proofs():
    challenges=(ROOT/"ALU_Gauntlet"/"cogs"/"challenges.py").read_text(encoding="utf-8")
    server=SERVER.read_text(encoding="utf-8")
    matches=(ROOT/"ALU_Gauntlet"/"web"/"static"/"gauntlet-matches.html").read_text(encoding="utf-8")
    for marker in ("proof1", "proof2", "proof3", "proof4", "proof5", "discord.Attachment", "challenger_proof_urls", "race_proofs"):
        assert marker in challenges
    assert "proof_url" in server
    assert "proof_url" in matches
    assert "challenger_proof_urls" in server
    assert "race_proofs" in server
    assert 'JSON.stringify({courses:rows})' in matches
    assert 'JSON.stringify({courses:rows,proof:' not in matches


def test_my_profile_is_public_view_and_my_settings_owns_profile_editing():
    server=SERVER.read_text(encoding="utf-8")
    player=PLAYER.read_text(encoding="utf-8")
    public=(STATIC/"public-profile.html").read_text(encoding="utf-8")
    public_js=(STATIC/"public-profile.js").read_text(encoding="utf-8")
    assert 'return web.Response(status=302, headers={"Location": f"/profile?user_id={user.user_id}"})' in server
    assert 'rsl_display_name' in server and 'rsl_avatar_url' in server
    assert 'rsl_display_name' in player and 'rsl_avatar_url' in player
    assert 'href="/profile"' in player
    assert 'href="/player/settings"' in player
    assert 'Edit My Settings' in public
    assert 'p.user_id' in public_js


def test_rsl_identity_does_not_modify_discord_identity():
    server=SERVER.read_text(encoding="utf-8")
    assert 'rsl_display_name' in server
    assert 'rsl_avatar_url' in server
    assert 'member.edit' not in server[server.index('async def player_profile'):server.index('async def player_asphalt')]


def test_rsl_avatar_and_public_profile_scripts_are_validated():
    player_js = PLAYER_JS.read_text(encoding="utf-8")
    public_js = (STATIC / "public-profile.js").read_text(encoding="utf-8")
    assert 'const discordAvatar=prefs.rsl_avatar_url || (' in player_js
    assert 'img.src=discordAvatar' in player_js
    assert '\\n' not in public_js
    assert 'const effectiveId=requestedId==="me"' in public_js
