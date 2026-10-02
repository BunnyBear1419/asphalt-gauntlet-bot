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

def test_admin_navigation_contract_has_matching_sections_and_safe_internal_targets():
    import re

    page = read("admin.html")
    nav_sections = set(re.findall(r'data-section="([^"]+)"', page))
    panel_sections = set(re.findall(r'id="section-([^"]+)"', page))
    assert nav_sections == panel_sections
    assert len(nav_sections) >= 10

    for href in re.findall(r'<a[^>]+href="([^"]+)"', page):
        if href.startswith("/"):
            assert "javascript:" not in href.lower()

    assert 'id="setup-link" href="/admin#section-settings"' in page
    assert 'id="news-link" href="/news-admin"' in page


def test_admin_section_switcher_supports_hash_navigation():
    page = read("admin.html")
    assert 'location.hash' in page
    assert 'replace(/^section-/,"")' in page
    assert 'classList.toggle("active"' in page

def test_admin_and_player_route_contracts():
    server = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "core.py").read_text(encoding="utf-8")
    for marker in (
        'add_get("/admin", self.admin_page)',
        'add_get("/players", self.players_page)',
        'add_get("/news-admin", self.news_admin_page)',
        'add_get("/rsl-center", self.rsl_command_center_page)',
        'add_get("/player", self.player_page)',
        'add_get("/player/profile", self.player_profile_page)',
        'add_get("/player/settings", self.player_settings_page)',
        'add_get("/profile", self.profile_page)',
        'add_get("/my-tournaments", self.my_tournaments_page)',
    ):
        assert marker in server


def test_admin_system_controls_have_runtime_handlers():
    page = read("admin.html")
    required = (
        'id="run-diagnostics"',
        'id="force-sync"',
        'id="backup-link"',
        'id="safe-mode-toggle"',
        'id="load-reliability"',
        'id="create-recovery-checkpoint"',
        'id="run-integrity"',
        'id="load-evidence"',
        'id="season-preview"',
        'id="season-finalize"',
        'id="load-releases"',
        'id="audit-search"',
        'id="audit-source"',
    )
    for marker in required:
        assert marker in page
    for marker in (
        'api("/api/admin/diagnostics',
        'api("/api/admin/sync',
        'api("/api/admin/maintenance',
        'api("/api/admin/operations',
        'api("/api/admin/audit',
    ):
        assert marker in page
