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
    assert "get_theme" in source
    assert "set_theme" in source
    assert "rsl_theme" in source

def test_profile_exposes_theme_setting():
    source=(STATIC/"player.html").read_text(encoding="utf-8")
    assert 'id="profile-theme"' in source
    assert 'value="dark"' in source
    assert 'value="light"' in source

def test_theme_controller_persists_and_applies_theme():
    source=(STATIC/"theme.js").read_text(encoding="utf-8")
    assert 'localStorage.getItem("rsl_theme")' in source
    assert 'localStorage.setItem(KEY,t)' in source
    assert 'document.documentElement.setAttribute("data-theme",t)' in source
    assert '"/api/theme"' in source

def test_light_theme_css_exists():
    source=(STATIC/"app.css").read_text(encoding="utf-8")
    assert 'html[data-theme="light"]' in source
    assert "RSL ACCOUNT THEME" in source
