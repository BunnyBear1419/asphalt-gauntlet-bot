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
