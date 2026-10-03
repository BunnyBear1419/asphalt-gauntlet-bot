from pathlib import Path
from web_source import web_source

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
ADMIN = ROOT / "ALU_Gauntlet" / "web" / "static" / "admin.html"
PROFILE = ROOT / "ALU_Gauntlet" / "web" / "static" / "public-profile.html"
PROFILE_JS = ROOT / "ALU_Gauntlet" / "web" / "static" / "public-profile.js"
CSS = ROOT / "ALU_Gauntlet" / "web" / "static" / "app.css"


def test_remaining_operations_extend_existing_surfaces():
    server = web_source()
    admin = ADMIN.read_text(encoding="utf-8")
    assert "async def admin_operations" in server
    assert '"/api/admin/operations"' in server
    assert 'action == "season_finalize"' in server
    assert 'action == "evidence"' in server
    assert 'action == "releases"' in server
    assert "Driver record invariants" in server
    assert "Match settlement invariants" in server
    assert "Evidence/review queues" in server
    assert "safe-mode-toggle" in admin
    assert "/api/admin/operations" in admin
    assert "/api/admin/competition-safe-mode" in admin
    assert 'action == "maintenance"' in server
    assert "season-finalize" in admin
    assert "load-evidence" in admin
    assert "load-releases" in admin


def test_player_activity_is_merged_into_public_profile():
    server = web_source()
    profile = PROFILE.read_text(encoding="utf-8")
    script = PROFILE_JS.read_text(encoding="utf-8")
    assert '"/api/players/{user_id}/activity"' in server
    assert "async def admin_activity_timeline" in server
    assert "Player Activity Timeline" in profile
    assert '"/api/players/"+encodeURIComponent(effectiveId)+"/activity"' in script


def test_shared_accessibility_and_mobile_polish():
    css = CSS.read_text(encoding="utf-8")
    assert "RSL shared accessibility/mobile polish" in css
    assert "focus-visible" in css
    assert "prefers-reduced-motion" in css
