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


def test_theme_layer_is_last_and_has_accessibility_contract():
    css = CSS.read_text(encoding="utf-8")
    marker = "RSL PRODUCTION UI HARDENING"
    assert marker in css
    tail = css[css.rfind(marker):]
    assert "prefers-reduced-motion:reduce" in tail
    assert "focus-visible" in tail
    assert "var(--rsl-final-panel)" in tail


def test_no_universal_theme_selector_can_reset_every_theme_to_midnight_blue():
    server = SERVER.read_text(encoding="utf-8")
    assert 'html[data-theme]{--rsl-audit-bg:#020817' not in server
    assert 'html[data-theme]{--rsl-audit-bg:#071427' not in server


def test_discord_brand_exception_remains_explicit():
    server = SERVER.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "#5865F2" in server or "#5865f2" in server or "#5865F2" in css or "#5865f2" in css


def test_midnight_theme_keeps_the_intended_default_palette():
    server = SERVER.read_text(encoding="utf-8")
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
    server = SERVER.read_text(encoding="utf-8")
    start = server.find(".rsl-cookie-settings{")
    assert start >= 0
    rule = server[start:server.find("}", start) + 1]
    assert "font-size:14px" in rule
    assert "line-height:1.25" in rule
    assert "font-weight:700" in rule


def test_cookie_footer_controls_share_the_same_utility_row():
    server = SERVER.read_text(encoding="utf-8")
    assert ".rsl-footer-utility-row{" in server
    assert ".rsl-footer-utility-row .rsl-language-switcher" in server
    assert ".rsl-footer-theme-control{" in server
