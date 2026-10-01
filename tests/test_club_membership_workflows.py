from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLUBS = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "clubs.py").read_text(encoding="utf-8")
CORE = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "core.py").read_text(encoding="utf-8")
MAIN = (ROOT / "ALU_Gauntlet" / "main.py").read_text(encoding="utf-8")
JS = (ROOT / "ALU_Gauntlet" / "web" / "static" / "clubs.js").read_text(encoding="utf-8")


def test_club_membership_workflow_handlers_and_routes_exist():
    for marker in (
        "async def club_member_search",
        "async def club_invitations",
        "async def club_join_requests",
        "async def create_club_invite",
        "async def club_invitation_action",
        "async def create_club_join_request",
        "async def club_join_request_action",
        "async def club_action_status",
    ):
        assert marker in CLUBS
    for path in (
        "/api/clubs/member-search",
        "/api/clubs/invitations",
        "/api/clubs/requests",
        "/api/clubs/actions",
        "/api/clubs/invite",
        "/api/clubs/invite/action",
        "/api/clubs/request",
        "/api/clubs/request/action",
    ):
        assert path in CORE


def test_club_membership_indexes_prevent_duplicate_pending_actions():
    assert "uniq_pending_club_invitation" in MAIN
    assert "uniq_pending_club_join_request" in MAIN
    assert 'partialFilterExpression={"status": "pending"}' in MAIN
    assert '["club_id", 1), ("invitee_id", 1)' in MAIN or '[("club_id", 1), ("invitee_id", 1)]' in MAIN
    assert '[("club_id", 1), ("user_id", 1)]' in MAIN


def test_club_ui_exposes_both_membership_flows():
    assert "request-club" in JS
    assert "manage-club" in JS
    assert "/api/clubs/request" in JS
    assert "/api/clubs/invite" in JS
    assert "/api/clubs/invite/action" in JS
    assert "/api/clubs/request/action" in JS
    assert "/api/clubs/member-search" in JS
    assert "showInvitations()" in JS


def test_club_membership_safeguards_are_present():
    assert "That club is full." in CLUBS
    assert "You are already in a club in this server." in CLUBS
    assert "Only the club leader can invite drivers." in CLUBS
    assert "Only the club leader can manage join requests." in CLUBS
    assert "expires_at" in CLUBS
    assert "DuplicateKeyError" in CLUBS
