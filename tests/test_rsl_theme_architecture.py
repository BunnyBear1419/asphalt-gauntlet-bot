from web_source import web_source
"""Regression contracts for the Racing Syndicate League theme architecture."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "ALU_Gauntlet" / "web" / "static" / "app.css"
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"

THEMES = ("dark", "light", "ocean", "purple", "crimson", "emerald", "sunset", "graphite")


def test_all_supported_themes_have_final_tokens():
    css = CSS.read_text(encoding="utf-8")
    for theme in THEMES:
        assert f'html[data-theme="{theme}"]' in css
    for token in (
        "--rsl-final-bg",
        "--rsl-final-panel",
        "--rsl-final-panel2",
        "--rsl-final-line",
        "--rsl-final-text",
        "--rsl-final-muted",
        "--rsl-final-accent",
    ):
        assert token in css


def test_navigation_dropdowns_close_when_pointer_leaves():
    server = web_source()
    assert 'document.querySelectorAll(".top-nav details.top-nav-dropdown")' in server
    assert 'dropdown.addEventListener("pointerenter",open)' in server
    assert 'dropdown.addEventListener("pointerleave",close)' in server
    assert 'dropdown.open=!dropdown.open' in server


def test_default_midnight_has_cross_page_audit_tokens():
    server = web_source()
    expected = (
        'html[data-theme="dark"]{--rsl-audit-bg:#020b18',
        '--rsl-audit-panel:#071427',
        '--rsl-audit-panel2:#0b1d34',
        '--rsl-audit-line:#173b64',
        '--rsl-audit-text:#dbe8f8',
        '--rsl-audit-accent:#25dfff',
    )
    for token in expected:
        assert token in server


def test_theme_layer_is_last_and_has_accessibility_contract():
    css = CSS.read_text(encoding="utf-8")
    marker = "RSL PRODUCTION UI HARDENING"
    assert marker in css
    tail = css[css.rfind(marker):]
    assert "prefers-reduced-motion:reduce" in tail
    assert "focus-visible" in tail
    assert "var(--rsl-final-panel)" in tail


def test_no_universal_theme_selector_can_reset_every_theme_to_midnight_blue():
    server = web_source()
    assert 'html[data-theme]{--rsl-audit-bg:#020817' not in server
    assert 'html[data-theme]{--rsl-audit-bg:#071427' not in server


def test_form_controls_are_theme_normalized_including_native_options():
    server = web_source()
    required = (
        "html[data-theme] input,html[data-theme] textarea,html[data-theme] select",
        'html[data-theme] select{color-scheme:dark}',
        'html[data-theme="light"] select{color-scheme:light}',
        "html[data-theme] select option,html[data-theme] select optgroup",
        "accent-color:var(--rsl-audit-accent)!important",
    )
    for token in required:
        assert token in server

def test_legacy_form_surfaces_use_theme_tokens():
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "ALU_Gauntlet/web/static/player.html",
        root / "ALU_Gauntlet/web/static/admin.html",
        root / "ALU_Gauntlet/web/static/app.css",
        root / "ALU_Gauntlet/web/static/gauntlet-matches.html",
        root / "ALU_Gauntlet/web/static/gauntlet-defense.html",
        root / "ALU_Gauntlet/web/static/gauntlet-references.html",
        root / "ALU_Gauntlet/web/static/tournaments.html",
    ]
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "background:#020b1b" not in source
        assert "background:#061326" not in source
        assert "background:#061427" not in source
        assert "background:#071225" not in source


def test_discord_brand_exception_remains_explicit():
    server = web_source()
    css = CSS.read_text(encoding="utf-8")
    assert "#5865F2" in server or "#5865f2" in server or "#5865F2" in css or "#5865f2" in css


def test_midnight_theme_keeps_the_intended_default_palette():
    server = web_source()
    expected = (
        "--rsl-final-bg:#020817",
        "--rsl-final-panel:#071427",
        "--rsl-final-panel2:#0d2139",
        "--rsl-final-line:#173b64",
        "--rsl-final-text:#dbe8f8",
        "--rsl-final-muted:#91a5c3",
        "--rsl-final-accent:#25dfff",
    )
    for token in expected:
        assert token in server


def test_cookie_settings_control_has_readable_typography():
    server = web_source()
    start = server.find(".rsl-cookie-settings{")
    assert start >= 0
    rule = server[start:server.find("}", start) + 1]
    assert "font-size:14px" in rule
    assert "line-height:1.25" in rule
    assert "font-weight:700" in rule


def test_cookie_footer_controls_share_the_same_utility_row():
    server = web_source()
    assert ".rsl-footer-utility-row{" in server
    assert ".rsl-footer-utility-row .rsl-language-switcher" in server
    assert ".rsl-footer-theme-control{" in server


def test_shared_navigation_keeps_calendar_rules_and_search_before_profile_without_companion():
    server = web_source()
    calendar = 'calendar_markup = \'<a href="/calendar">'
    assert calendar in server
    assert 'rules_markup = ' in server
    assert 'companion_markup' not in server
    assert 'calendar_markup + rules_markup + "</nav>"' in server
    assert "search_markup" in server
    assert "profile_markup" in server
    assert "The search control belongs immediately to the left of the profile control." in server

def test_navigation_reserves_space_for_search_and_profile_controls():
    css = CSS.read_text(encoding="utf-8")
    assert "FINAL NAVIGATION ACTION BAR" in css
    final_nav = css.index("FINAL NAVIGATION ACTION BAR")
    nav_block = css[final_nav:final_nav + 1800]
    assert ".top-nav>nav{\n  position:absolute!important;" in nav_block
    assert "left:190px!important" in nav_block
    assert "right:450px!important" in nav_block
    assert ".top-nav>.rsl-search-trigger{right:270px!important" in css
    assert ".top-nav>.rsl-profile-nav" in css


def test_navigation_normalizes_legacy_calendar_and_profile_markup():
    server = web_source()
    assert "Remove any legacy/static Calendar nav entry" in server
    assert "top-user-area" in server
    assert "rsl-search-trigger" in server
    assert "rsl-profile-nav" in server


def test_player_page_no_longer_exposes_legacy_setup_route_links():
    players = (ROOT / "ALU_Gauntlet" / "web" / "static" / "players.html").read_text(encoding="utf-8")
    assert 'href="/setup"' not in players
    assert 'href="/admin#section-settings"' in players
    assert 'class="alu-dashboard players-page"' in players

def test_admin_server_setup_hash_resolves_to_settings_section():
    admin = (ROOT / "ALU_Gauntlet" / "web" / "static" / "admin.html").read_text(encoding="utf-8")
    assert 'id="setup-link" href="/admin#section-settings"' in admin
    assert 'href="/admin#section-settings"' in admin
    assert 'name=String(name||"").replace(/^section-/,"");' in admin
    assert '#section-settings' in admin


def test_shared_header_does_not_inject_stray_social_icons():
    server = web_source()
    assert 'class="top-discord-link"' not in server
    assert 'class="top-cashapp-link"' not in server
    assert "rsl-footer-social" in server
    assert "rsl-footer-discord" in server
    assert "rsl-footer-cashapp" in server


def test_shared_navigation_removes_legacy_companion_and_normalizes_calendar_account_markup():
    server = web_source()
    assert 'companion_cleanup = re.compile(' in server
    assert 'href=["\\\\\\']/calendar' in server
    assert 'class="top-user-area"' in server
    assert "companion_markup" not in server
    assert "Normalize Calendar + Shohan's Companion on every page." not in server

def test_admin_internal_hash_links_use_section_navigation():
    admin = (ROOT / "ALU_Gauntlet" / "web" / "static" / "admin.html").read_text(encoding="utf-8")
    assert "document.querySelectorAll('a[href^=\"#\"]')" in admin
    assert 'showSection(target.slice(1))' in admin


def test_shohan_companion_brand_styles_are_not_part_of_rsl_theme_contract():
    css = CSS.read_text(encoding="utf-8")
    assert "--shohan-accent" not in css
    assert ".partner-banner" not in css
    assert "SHOHAN'S LAB • COMPANION" not in css

def test_discord_server_dropdown_uses_selected_theme_surface():
    css = CSS.read_text(encoding="utf-8")
    start = css.find(".rsl-site-page .server-select select")
    assert start >= 0
    rule = css[start:css.find("}", start) + 1]
    assert "background:var(--rsl-final-panel2)!important" in rule
    assert "color:var(--rsl-final-text)!important" in rule


def test_search_control_and_header_do_not_reintroduce_legacy_blue():
    css = CSS.read_text(encoding="utf-8")
    search_start = css.find(".rsl-search-trigger{")
    assert search_start >= 0
    search_rule = css[search_start:css.find("}", search_start) + 1]
    assert "border:1px solid var(--rsl-final-line)!important" in search_rule
    assert "background:var(--rsl-final-panel2)!important" in search_rule
    assert "color:var(--rsl-final-text)!important" in search_rule
    header_start = css.find(".top-nav{")
    assert header_start >= 0
    header_rule = css[header_start:css.find("}", header_start) + 1]
    assert "border-bottom:1px solid var(--rsl-final-line)" in header_rule
    assert ".rsl-search-trigger img" in css
    assert "filter:grayscale(1) brightness(1.8)!important" in css


def test_navigation_surfaces_use_final_theme_tokens():
    css = CSS.read_text(encoding="utf-8")
    start = css.find("/* FINAL THEME NAVIGATION SURFACE OVERRIDES")
    assert start >= 0
    block = css[start:]
    for token in (
        "border-right-color:var(--rsl-final-line)!important",
        "background:color-mix(in srgb,var(--rsl-final-accent) 10%,var(--rsl-final-panel))!important",
        "background:var(--rsl-final-panel)!important",
        "border-color:var(--rsl-final-line)!important",
        "color:var(--rsl-final-text)!important",
    ):
        assert token in block
    assert "background:#0a1a2d" not in block
    assert "background:#071533" not in block


def test_shared_card_and_account_surfaces_use_final_theme_tokens():
    css = CSS.read_text(encoding="utf-8")
    start = css.find("/* FINAL SHARED SURFACE THEME OVERRIDES")
    assert start >= 0
    block = css[start:]
    for token in (
        "background:var(--rsl-final-panel)!important",
        "border-color:var(--rsl-final-line)!important",
        "color:var(--rsl-final-text)!important",
        "background:color-mix(in srgb,var(--rsl-final-accent) 12%,var(--rsl-final-panel))!important",
    ):
        assert token in block
    assert "background:#0a1a2d!important" not in block
    assert "background:#09192c" not in block

def test_legacy_blue_chrome_is_theme_driven():
    server = web_source()
    required = (
        "FINAL BLUE QUARANTINE",
        "--rsl-theme-accent:var(--rsl-final-accent)",
        ".rsl-search-trigger::before",
        "-webkit-mask:url(\"/assets/icons/search.png\")",
        "html[data-theme] .feature-blue",
        "html[data-theme] .profile-avatar-large",
        'html[data-theme] [style*="#168cff"]',
    )
    for token in required:
        assert token in server
