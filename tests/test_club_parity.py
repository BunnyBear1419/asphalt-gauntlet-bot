from pathlib import Path
from web_source import web_source

ROOT = Path(__file__).resolve().parents[1]
PLAYER = (ROOT / "ALU_Gauntlet" / "cogs" / "player.py").read_text(encoding="utf-8")
SERVER = web_source()
CLUBS_JS = (ROOT / "ALU_Gauntlet" / "web" / "static" / "clubs.js").read_text(encoding="utf-8")
CLUB_JS = (ROOT / "ALU_Gauntlet" / "web" / "static" / "club.js").read_text(encoding="utf-8")


def test_discord_dashboard_exposes_club_center_without_new_slash_command():
    assert "class ClubCenterButton" in PLAYER
    assert "view.add_item(ClubCenterButton())" in PLAYER
    assert "class ClubCenterView" in PLAYER
    assert "class CreateClubModal" in PLAYER
    assert "class EditClubModal" in PLAYER
    assert "class ClubPickerSelect" in PLAYER
    assert "@app_commands.command(name='club'" not in PLAYER
    assert '@app_commands.command(name="club"' not in PLAYER


def test_discord_club_center_matches_shared_club_contract():
    for marker in (
        '"member_count": 1',
        '"member_count": {"$lt": 20}',
        "leader_id",
        "tournament_wins",
        "tournament_losses",
        "Club Picture URL",
        "About the Club",
        "Club Discord Link",
        "Club Links",
        "promote",
        "demote",
        "kick",
        "Leave Club",
    ):
        assert marker in PLAYER


def test_website_club_leave_and_member_controls_are_registered():
    assert 'add_post("/api/clubs", self.create_club)' in SERVER
    assert 'add_post("/api/clubs/update", self.update_club)' in SERVER
    assert 'add_post("/api/clubs/join", self.join_club)' in SERVER
    assert 'add_post("/api/clubs/leave", self.leave_club)' in SERVER
    assert 'add_post("/api/clubs/member", self.manage_club_member)' in SERVER
    assert "async def leave_club" in SERVER
    assert "Club leaders must transfer leadership before leaving." in SERVER
    assert 'data-action="promote"' in CLUBS_JS
    assert 'data-action="demote"' in CLUBS_JS
    assert 'data-action="kick"' in CLUBS_JS
    assert 'api("/api/clubs/leave"' in CLUBS_JS
    assert '/api/clubs/leave' in CLUB_JS


def test_club_cap_and_shared_fields_remain_explicit():
    assert '"member_count": 1' in SERVER
    assert '{"member_count": {"$lt": 20}}' in SERVER
    assert '"image": ""' in SERVER
    assert '"leader_id": str(user.user_id)' in SERVER
    assert '"about":' in SERVER
    assert '"tournament_wins"' in SERVER or "tournament_wins" in CLUB_JS


def test_clubs_page_create_flow_has_working_client_bindings():
    source = CLUBS_JS
    assert '$("#open-create").onclick=()=>$("#create-panel").hidden=false' in source or 'addEventListener("click"' in source
    assert '$("#club-form").onsubmit=async e=>' in source
    assert 'function publicClubProfile(c){' in source
    assert 'const recent=Array.isArray(c.recent_tournament_results)' in source
    assert '</section>+' not in source
