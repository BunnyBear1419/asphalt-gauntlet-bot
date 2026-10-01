from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "ALU_Gauntlet" / "web"


def test_ticket_controls_are_bound_to_admin_api():
    page = (WEB / "static" / "admin.html").read_text(encoding="utf-8")
    core = (WEB / "routes" / "core.py").read_text(encoding="utf-8")
    for marker in ('id="ticket-refresh"', 'id="ticket-transcript"', 'id="ticket-save"', 'id="ticket-post-panel"'):
        assert marker in page
    for path in (
        "/api/admin/tickets",
        "/api/admin/tickets/action",
        "/api/admin/tickets/transcript",
        "/api/admin/tickets/settings",
        "/api/admin/tickets/panel",
    ):
        assert path in core


def test_calendar_actions_are_bound_to_registered_routes():
    script = (WEB / "static" / "calendar.js").read_text(encoding="utf-8")
    core = (WEB / "routes" / "core.py").read_text(encoding="utf-8")
    for path in ("/api/calendar", "/api/reminders", "/api/reminders/", "/api/notifications/event"):
        assert path in script
        assert path in core
    for marker in ("calendar-add-reminder", "calendar-prev", "calendar-next", "calendar-today", "save-reminder", "delete-reminder"):
        assert marker in (WEB / "static" / "calendar.html").read_text(encoding="utf-8") or marker in script


def test_profile_navigation_targets_exist():
    core = (WEB / "routes" / "core.py").read_text(encoding="utf-8")
    player = (WEB / "static" / "player.html").read_text(encoding="utf-8")
    profile = (WEB / "static" / "profile.html").read_text(encoding="utf-8")
    for path in ("/profile", "/player/settings", "/clubs", "/calendar", "/tournaments", "/rules"):
        assert path in core
        assert path in player or path in profile
