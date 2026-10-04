from pathlib import Path
ROOT=Path(__file__).parents[1]; STATIC=ROOT/"ALU_Gauntlet"/"web"/"static"
def read(name): return (STATIC/name).read_text(encoding="utf-8")
def test_club_create_surface():
    page,script=read("clubs.html"),read("clubs.js")
    assert 'id="open-create"' in page and 'id="club-form"' in page
    assert ('$("#open-create").onclick' in script or 'addEventListener("click"' in script) and '$("#club-form").onsubmit' in script
    assert '"/api/clubs"' in script and 'method:"POST"' in script
    assert '/static/clubs.js?v=20261004-rsl-clubs2' in page
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
    nav_sections = re.findall(r'<button[^>]+data-section="([^"]+)"', page)
    panel_sections = re.findall(r'id="section-([^"]+)"', page)
    assert sorted(nav_sections) == sorted(panel_sections)
    assert len(nav_sections) >= 10
    assert len(nav_sections) == len(set(nav_sections))
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
    page=read("admin.html")
    required = (
        'id="run-diagnostics"','id="force-sync"','id="backup-link"','id="safe-mode-toggle"',
        'id="load-reliability"','id="create-recovery-checkpoint"','id="run-integrity"',
        'id="load-evidence"','id="season-preview"','id="season-finalize"','id="load-releases"','id="audit-search"','id="audit-source"',
    )
    for marker in required: assert marker in page
    for marker in ('api("/api/admin/diagnostics','api("/api/admin/sync','api("/api/admin/operations','api("/api/admin/audit'):
        assert marker in page
def test_admin_system_recovery_controls_have_unique_navigation_targets():
    import re
    page = read("admin.html")
    nav_sections = re.findall(r'<button[^>]+data-section="([^"]+)"', page)
    assert nav_sections.count("settings") == 1
    for target in ("system","server-control","settings","tickets","fairness"):
        assert nav_sections.count(target) == 1
def test_player_markup_has_balanced_style_blocks():
    page=read("player.html")
    assert page.count("<style>") == page.count("</style>")
    assert "</style><style>" in page
    assert "</style></style>" not in page
def test_club_create_control_is_explicit_and_server_bound():
    page,script=read("clubs.html"),read("clubs.js")
    assert 'type="button" class="primary-action" id="open-create"' in page
    assert 'aria-controls="create-panel"' in page
    assert 'addEventListener("click"' in script
    assert 'data.guild_id=data.guild_id||$("#club-guild")?.value||""' in script and 'id="club-guild"' in page
def test_clubs_page_style_block_is_closed():
    page=read("clubs.html")
    assert page.count("<style>") == page.count("</style>")
    assert "</style></head>" in page
def test_safe_mode_control_refreshes_after_toggle():
    page=read("admin.html")
    assert 'await loadOpsStatus();' in page
    assert 'setStatus("safe-mode-status",enabled?"Competition safe mode enabled.":"Competition mutations are live.",true);' in page
def test_shared_shell_uses_one_current_theme_cache_key():
    core=(ROOT/"ALU_Gauntlet"/"web"/"routes"/"core.py").read_text(encoding="utf-8")
    assert "rsl-theme2site20" not in core
    assert core.count("rsl-theme2") >= 2
def test_admin_system_buttons_have_client_handlers():
    page=read("admin.html")
    for token in ("run-diagnostics","force-sync","create-server-role","create-server-channel","save-bot-identity","safe-mode-toggle","run-integrity","load-evidence","load-reliability","create-recovery-checkpoint","season-preview","season-finalize","load-releases"):
        assert token in page
    assert 'addEventListener("click"' in page
def test_player_settings_has_final_theme_override():
    page=read("player.html")
    assert "FINAL PLAYER SETTINGS THEME OVERRIDE" in page
    assert "var(--rsl-box)" in page
    assert "#profile-settings input" in page
def test_admin_setup_links_preserve_selected_guild_context():
    page=read("admin.html")
    assert 'id="setup-link" href="/admin#section-settings"' in page
    assert 'id="system-setup-link" href="/admin#section-settings"' in page
    assert 'data-route="/admin#section-settings"' not in page
    assert 'onclick="window.location.assign(this.dataset.route); return false;"' not in page
    assert 'systemSetupLink.href="/admin?guild_id="+encodeURIComponent(guildId)+"#settings"' in page

def test_player_settings_navigation_targets_are_real_routes():
    page=read("player.html")
    assert 'href="/profile"' in page
    assert 'href="/player/settings"' in page
    assert 'href="/player/settings#profile-links-area"' in page
    assert 'data-rsl-player-mode="{mode}"' in (ROOT/"ALU_Gauntlet"/"web"/"routes"/"core.py").read_text(encoding="utf-8")
    assert '/static/player.js?v=20261002-rsl-player2' in page


def test_auth_page_uses_current_theme_cache_key():
    page=(ROOT/"ALU_Gauntlet"/"web"/"routes"/"auth.py").read_text(encoding="utf-8")
    assert "rsl-theme2site20" not in page
    assert "/static/app.css?v=20261002-rsl-theme2" in page


def test_tournaments_page_uses_current_theme_cache_key():
    page=read("tournaments.html")
    assert "/static/app.css?v=20261002-rsl-theme2" in page
    assert "rsl-theme2s-home-boxes" not in page


def test_player_theme_style_blocks_are_not_nested():
    page=read("player.html")
    assert "<style>\n/* FINAL PLAYER THEME SURFACE AUDIT" in page
    assert "\n</style>\n<style>\n/* FINAL PLAYER THEME SURFACE AUDIT" in page
    assert "\n</style>\n</style>\n</head>" not in page


def test_admin_dashboard_guild_links_have_progressive_navigation_fallbacks():
    page=read("admin.html")
    assert '<a class="admin-tool admin-guild-link" href="/admin#settings" data-path="/admin" data-section="settings">'.replace("    ","") in page
    assert '<a class="admin-tool admin-guild-link" href="/gauntlet/leaderboard" data-path="/gauntlet/leaderboard">'.replace("    ","") in page
    assert '<a class="admin-tool admin-guild-link" href="/tournaments" data-path="/tournaments">'.replace("    ","") in page
    assert 'a.href=a.dataset.path+"?guild_id="+encodeURIComponent(guildId)' in page
