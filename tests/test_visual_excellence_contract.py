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


def test_home_command_center_uses_theme_tokens():
    home = read("index.html")
    assert "RSL THEME FIX — Driver Command Center" in home
    start = home.index("RSL THEME FIX — Driver Command Center")
    end = home.index("</style>", start)
    block = home[start:end]
    for token in (
        "var(--rsl-box)",
        "var(--rsl-box-alt)",
        "var(--rsl-box-line)",
        "var(--rsl-box-text)",
        "var(--rsl-box-muted)",
        "var(--rsl-box-accent)",
    ):
        assert token in block


def test_home_command_center_has_correct_theme_hierarchy():
    css = read("app.css")
    assert "/* Competitive Snapshot hierarchy: outer shell dark, inner stats light." in css
    assert "color-mix(in srgb,var(--rsl-box) 82%,#000)" in css
    assert "color-mix(in srgb,var(--rsl-box-alt) 82%,#fff)" in css
    assert "html[data-theme] .home-page .rsl-command-center .rsl-stat-card" in css
    assert "html[data-theme] .home-page .rsl-command-center .rsl-stat-hero" in css
