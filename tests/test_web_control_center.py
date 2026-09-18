"""Regression coverage for the web control-center surface."""
from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/"ALU_Gauntlet"/"web"
STATIC=WEB/"static"

def test_web_runtime_files_exist():
    for name in ("server.py","auth.py","players.py"):
        assert (WEB/name).is_file(), name
    for name in ("index.html","player.html","players.html","setup.html","app.css","app.js","player.js","setup.js","racing.svg"):
        assert (STATIC/name).is_file(), name

def test_web_python_modules_parse():
    for path in (WEB/"server.py",WEB/"auth.py",WEB/"players.py"):
        ast.parse(path.read_text(encoding="utf-8"),filename=str(path))

def test_web_routes_are_guild_scoped():
    source=(WEB/"server.py").read_text(encoding="utf-8")
    for marker in ("player_me","player_preferences","setup_options","setup_settings","save_setup_settings","season"):
        assert marker in source
    assert "guild_id is required." in source
    assert "Administrator access is required for this server." in source

def test_web_ui_is_dashboard_first():
    source=(STATIC/"index.html").read_text(encoding="utf-8")
    assert "My Garage" in source
    assert "Race Operations" in source
    assert "/setup" in source
    assert "/players" in source

def test_player_page_uses_same_dashboard_visual_system():
    source=(STATIC/"player.html").read_text(encoding="utf-8")
    for marker in ("class=\"alu-dashboard\"","class=\"top-nav\"","class=\"sidebar\"","class=\"hero-banner\"","class=\"dashboard-grid\"","id=\"matches\"","id=\"preferences\""):
        assert marker in source
    assert "/static/app.css" in source
    assert "/static/player.js" in source


def test_player_search_treats_input_as_literal_text():
    source=(WEB/"players.py").read_text(encoding="utf-8")
    assert "import re" in source
    assert "re.escape(search.strip())" in source


def test_player_api_exposes_saved_preferences():
    source=(WEB/"server.py").read_text(encoding="utf-8")
    assert '"preferences"' in source
    assert '"timezone"' in source


def test_player_dashboard_restores_saved_timezone_and_escapes_profile_text():
    source=(STATIC/"player.js").read_text(encoding="utf-8")
    assert 'prefs=d.preferences||{}' in source
    assert 'prefs.timezone' in source
    assert 'profile.textContent=' in source
    assert 'profile.innerHTML=' not in source


def test_web_registration_uses_canonical_submission_workflow():
    server=(WEB/"server.py").read_text(encoding="utf-8")
    assert 'add_post("/api/player/register", self.player_register)' in server
    assert 'submit_registration_application' in server
    assert 'require_guild_member(request)' in server
    assert 'review_channel_id' in server


def test_web_registration_ui_covers_same_player_registration_inputs():
    html=(STATIC/"player.html").read_text(encoding="utf-8")
    js=(STATIC/"player.js").read_text(encoding="utf-8")
    for marker in ("id=\"registration-game-id\"","id=\"registration-pi\"","id=\"registration-control\"","id=\"registration-proof\"","id=\"register\""):
        assert marker in html
    assert '/api/player/register?guild_id=' in js


def test_web_registration_is_member_scoped_not_staff_only():
    server=(WEB/"server.py").read_text(encoding="utf-8")
    start=server.index('    async def player_register(')
    end=server.index('    async def player_preferences(', start)
    source=server[start:end]
    assert 'require_guild_member(request)' in source
    assert 'require_admin(request)' not in source


def test_web_auth_persists_sessions_across_process_restarts():
    source=(WEB/"auth.py").read_text(encoding="utf-8")
    assert "web_sessions" in source
    assert "SESSION_TTL = 30 * 24 * 60 * 60" in source
    assert "self._session_key(token)" in source
    assert "set_session_cookie" in source


def test_web_login_and_logout_are_exposed():
    server=(WEB/"server.py").read_text(encoding="utf-8")
    for marker in ('add_get("/login", self.login)','add_get("/logout", self.logout)','/auth/callback'):
        assert marker in server
    for name in ("index.html","player.html","players.html","setup.html"):
        html=(STATIC/name).read_text(encoding="utf-8")
        assert 'href="/logout"' in html
