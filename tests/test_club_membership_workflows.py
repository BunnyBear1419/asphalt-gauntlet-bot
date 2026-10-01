from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLUBS = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "clubs.py").read_text(encoding="utf-8")
CORE = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "core.py").read_text(encoding="utf-8")
MAIN = (ROOT / "ALU_Gauntlet" / "main.py").read_text(encoding="utf-8")
JS = (ROOT / "ALU_Gauntlet" / "web" / "static" / "clubs.js").read_text(encoding="utf-8")
PLAYER = (ROOT / "ALU_Gauntlet" / "cogs" / "player.py").read_text(encoding="utf-8")


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
    assert "Only the club leader or an Officer can invite drivers." in CLUBS
    assert "Only the club leader or an Officer can manage join requests." in CLUBS
    assert "expires_at" in CLUBS
    assert "DuplicateKeyError" in CLUBS


def test_officer_role_and_manager_permissions_are_enforced():
    assert 'value = "officer" if action == "promote" else "member"' in CLUBS
    assert 'actor_role not in {"leader", "officer"}' in CLUBS
    assert 'Only the club leader can promote or demote Officers.' in CLUBS
    assert 'Only the club leader or an Officer can invite drivers.' in CLUBS
    assert 'Only the club leader or an Officer can manage join requests.' in CLUBS
    assert 'target_role == "officer" and actor_role != "leader"' in CLUBS
    assert 'roleLabel=r=>r==="leader"?"Leader":r==="officer"?"Officer":"Member"' in JS
    assert 'officer&&canManage&&targetRole==="member"' in JS
    assert 'self.owner_role != "leader"' in PLAYER
    assert 'Only the club leader or an Officer can manage members.' in PLAYER


def test_staff_can_recover_club_leadership():
    admin = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "admin.py").read_text(encoding="utf-8")
    core = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "core.py").read_text(encoding="utf-8")
    page = (ROOT / "ALU_Gauntlet" / "web" / "static" / "admin.html").read_text(encoding="utf-8")
    assert "async def admin_club_leadership" in admin
    assert "async def admin_club_leadership_action" in admin
    assert 'await self.require_admin(request)' in admin
    assert '"leader_id": target_id' in admin
    assert '"role": "officer"' in admin
    assert 'Staff transferred club leadership:' in admin
    assert 'add_get("/api/admin/clubs/leadership", self.admin_club_leadership)' in core
    assert 'add_post("/api/admin/clubs/leadership", self.admin_club_leadership_action)' in core
    assert 'id="club-leadership-transfer"' in page
    assert '"/api/admin/clubs/leadership"+q()' in page
    assert 'The current leader will become an Officer.' in page


def test_leader_can_transfer_or_delete_club():
    clubs = Path("ALU_Gauntlet/web/routes/clubs.py").read_text(encoding="utf-8")
    core = Path("ALU_Gauntlet/web/routes/core.py").read_text(encoding="utf-8")
    js = Path("ALU_Gauntlet/web/static/clubs.js").read_text(encoding="utf-8")
    assert "async def transfer_club_leadership" in clubs
    assert "Only the current club leader can transfer leadership." in clubs
    assert '"role": "officer"' in clubs
    assert '"updated_at": now' in clubs
    assert '"role": "leader"' in clubs
    assert "async def delete_club" in clubs
    assert "Only the club leader can delete the club." in clubs
    assert "tournament history or registrations" in clubs
    assert 'self.app.router.add_post("/api/clubs/transfer-leadership", self.transfer_club_leadership)' in core
    assert 'self.app.router.add_post("/api/clubs/delete", self.delete_club)' in core
    assert 'id="transfer-club-leader"' in js
    assert 'id="delete-club"' in js
    assert "/api/clubs/transfer-leadership" in js
    assert "/api/clubs/delete" in js
