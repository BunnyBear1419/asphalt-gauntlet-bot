"""Regression checks for tournament registration administration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
TOURNAMENTS = ROOT / "ALU_Gauntlet" / "web" / "static" / "tournaments.js"


def test_tournament_registration_admin_route_exists():
    server = SERVER.read_text(encoding="utf-8")
    assert 'add_post("/api/tournaments/register/action"' in server
    assert "async def tournament_registration_action" in server
    assert 'action not in {"approve", "reject"}' in server


def test_tournament_registration_deadline_is_enforced():
    server = SERVER.read_text(encoding="utf-8")
    start = server.index("async def register_tournament")
    end = server.index("async def tournament_registration_action", start)
    section = server[start:end]
    assert "registration_deadline" in section
    assert "Tournament registration has closed." in section


def test_tournament_registration_admin_action_is_audited():
    server = SERVER.read_text(encoding="utf-8")
    start = server.index("async def tournament_registration_action")
    end = server.index("async def tournament_club_lineup", start)
    section = server[start:end]
    assert '"accepted"' in section
    assert '"rejected"' in section
    assert "approved_by" in section
    assert "rejected_by" in section
    assert "await self._audit(" in section


def test_tournament_staff_ui_has_registration_review_hooks():
    script = TOURNAMENTS.read_text(encoding="utf-8")
    assert "/api/tournaments/register/action" in script
    assert "registration-action" in script
    assert "Staff Registration Review" in script
