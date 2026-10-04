from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "ALU_Gauntlet" / "web" / "static"

def read(name):
    return (STATIC / name).read_text(encoding="utf-8")

def test_visual_excellence_layer_exists():
    css = read("app.css")
    js = read("rsl-visual-excellence.js")
    app = read("app.js")
    assert "RSL VISUAL EXCELLENCE 3.0" in css
    assert "rsl-line-sweep" in css
    assert "rsl-xp-fill" in css
    assert "rsl-live-pulse" in css
    assert "prefers-reduced-motion:reduce" in css
    assert "RSLVisualExcellence" in js
    assert "data-rsl-visual-excellence" in app
    assert "/static/rsl-visual-excellence.js" in app

def test_visual_excellence_keeps_existing_rsl_language():
    css = read("app.css")
    home = read("index.html")
    assert "--rsl-box-accent" in css
    assert "rsl-visual-grid" in home
    assert "RACING GARAGE" in home
    assert "6 DIVISIONS" in home
    assert "partner-banner" in home
