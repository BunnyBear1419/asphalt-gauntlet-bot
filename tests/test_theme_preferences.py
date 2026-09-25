from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
SERVER=ROOT/"ALU_Gauntlet"/"web"/"server.py"
STATIC=ROOT/"ALU_Gauntlet"/"web"/"static"

def test_theme_runtime_files_and_server_parse():
    ast.parse(SERVER.read_text(encoding="utf-8"), filename=str(SERVER))
    assert (STATIC/"theme.js").is_file()
    source=SERVER.read_text(encoding="utf-8")
    assert '"/api/theme"' in source
    assert "THEMES" in source
    assert "get_theme" in source
    assert "set_theme" in source
    assert "rsl_theme" in source

def test_profile_exposes_theme_setting():
    source=(STATIC/"player.html").read_text(encoding="utf-8")
    assert 'id="profile-theme"' in source
    assert 'value="dark"' in source
    assert 'value="light"' in source
    for value in ("ocean","purple","crimson","emerald","sunset","graphite"):
        assert f'value="{value}"' in source

def test_theme_controller_persists_and_applies_theme():
    source=(STATIC/"theme.js").read_text(encoding="utf-8")
    assert 'localStorage.getItem(KEY)' in source
    assert 'localStorage.setItem(KEY,t)' in source
    assert 'document.documentElement.setAttribute("data-theme",t)' in source
    assert '"/api/theme"' in source

def test_light_theme_css_exists():
    source=(STATIC/"app.css").read_text(encoding="utf-8")
    assert 'html[data-theme="light"]' in source
    assert "RSL MULTI-THEME SYSTEM" in source
    for theme_name in ("ocean","purple","crimson","emerald","sunset","graphite"):
        assert f'html[data-theme="{theme_name}"]' in source

def test_cross_page_theme_contract_covers_all_themes():
    source=SERVER.read_text(encoding="utf-8")
    themes=("dark","light","ocean","purple","crimson","emerald","sunset","graphite")
    assert 'id="rsl-cross-page-theme-audit"' in source
    assert "theme_audit_css" in source
    for theme_name in themes:
        assert f'html[data-theme="{theme_name}"]' in source
    assert '/static/theme.js?v=20260924-theme5' in source


def test_all_static_html_pages_are_theme_renderable():
    pages=sorted(STATIC.glob("*.html"))
    assert pages, "No static HTML pages found."
    source=SERVER.read_text(encoding="utf-8")
    assert 'body = body.replace("</body>", theme_audit_css + "\n</body>", 1)' in source
    for page in pages:
        assert page.suffix == ".html"
