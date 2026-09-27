"""Regression coverage for the web control-center surface."""
from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/"ALU_Gauntlet"/"web"
STATIC=WEB/"static"

def test_web_runtime_files_exist():
    for name in ("server.py","auth.py","players.py"):
        assert (WEB/name).is_file(), name
    for name in ("index.html","player.html","players.html","setup.html","app.css","app.js","player.js" ,"setup.js"):
        assert (STATIC/name).is_file(), name

def test_web_python_modules_parse():
    for path in (WEB/"server.py",WEB/"auth.py",WEB/"players.py"):
        ast.parse(path.read_text(encoding="utf-8"),filename=str(path))

def test_web_routes_are_guild_scoped():
    source=(WEB/"server.py").read_text(encoding="utf-8")
    for marker in ("player_me","player_preferences","setup_options","setup_settings","save_setup_settings","season"):
        assert marker in source
    assert "No connected Discord server is available for this account." in source
    assert "Administrator access is required for this server." in source

def test_web_ui_is_simplified_control_center():
    source=(STATIC/"index.html").read_text(encoding="utf-8")
    assert "ABOUT US" in source
    assert "NEWS &amp; ANNOUNCEMENTS" in source
    assert "HELP CENTER" in source
    assert 'class="top-nav"' in source
    assert 'href="/gauntlet/registration"' in source
    assert "JOIN GAUNTLET" in source
    assert 'href="/help"' in source
    assert 'class="sidebar"' not in source

def test_player_page_uses_same_dashboard_visual_system():
    source=(STATIC/"player.html").read_text(encoding="utf-8")
    for marker in ("class=\"alu-dashboard\"","class=\"top-nav\"","class=\"hero-banner\"","class=\"dashboard-grid\"","id=\"matches\"","id=\"preferences\""):
        assert marker in source
    assert 'class="sidebar"' not in source
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


def test_dashboard_image_assets_are_served_with_image_mime_types():
    source=(WEB/"server.py").read_text(encoding="utf-8")
    assert 'self.app.router.add_get("/assets/{filename}", self.asset)' in source
    assert 'mimetypes.guess_type(path.name)[0]' in source
    assets=WEB/"static"/"assets"
    expected={"rsl-shield.png","rsl-top-logo.png","rsl-footer-mark.png"}
    assert expected.issubset({p.name for p in assets.iterdir()})


def test_dashboard_uses_browser_safe_raster_artwork():
    source=(STATIC/"app.css").read_text(encoding="utf-8")
    assets=STATIC/"assets"
    expected={"hero.jpg","welcome.jpg","gauntlet.jpg","garage.jpg","competition.jpg","profile-settings.jpg","garage-car.jpg","promo-banner.jpg"}
    assert expected.issubset({p.name for p in assets.iterdir()})
    for name in expected:
        assert f"/assets/{name}" in source


def test_web_setup_exposes_tournament_roles_and_channels():
    server=(WEB/"server.py").read_text(encoding="utf-8")
    setup=(STATIC/"setup.js").read_text(encoding="utf-8")
    for marker in ("tournament_main_channel_id","tournament_log_channel_id","tournament_bracket_channel_id","tournament_admin_channel_id","tournament_announcement_channel_id","tournament_admin_role_id","tournament_player_announcement_role_id"):
        assert marker in server and marker in setup

def test_web_setup_uses_rsl_setup_labels():
    setup=(STATIC/"setup.js").read_text(encoding="utf-8")
    for label in ("Player Gauntlet Channel","Match Results Channel","Gauntlet Staff Channel","Gauntlet Logs Channel","Gauntlet Announcement Channel","Tournament Announcement Channel","Tournament Logs Channel","Player Tournament Channel","Tournament Admin Channel","Gauntlet Admin Role","Tournament Admin Role","Gauntlet Driver Role","Tournament Driver Role"):
        assert label in setup


def test_achievement_role_names_are_configurable_from_server_setup():
    server=(WEB/"server.py").read_text(encoding="utf-8")
    setup=(STATIC/"setup.js").read_text(encoding="utf-8")
    role_sync=(ROOT/"ALU_Gauntlet/core/rsl_role_sync.py").read_text(encoding="utf-8")
    for marker in ("achievement_role_names","achievement_role_ids","XP_LEVEL_ROLES","GAUNTLET_SEASONAL_ROLES","TOURNAMENT_SEASONAL_ROLES","PERMANENT_ACHIEVEMENT_ROLES"):
        assert marker in server
    for marker in ("Achievement Role Names","XP Achievement Roles","Gauntlet Achievement Roles","Tournament Achievement Roles","data-role-name","achievement_role_names"):
        assert marker in setup
    assert "role.edit(name=display_name" in role_sync
