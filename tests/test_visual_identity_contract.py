from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_visual_identity_assets_and_home_contract():
    css = read("ALU_Gauntlet/web/static/app.css")
    index = read("ALU_Gauntlet/web/static/index.html")
    for asset in (
        "ALU_Gauntlet/web/static/assets/rsl/visuals/rsl-car-silhouette.svg",
        "ALU_Gauntlet/web/static/assets/rsl/visuals/rsl-track-map.svg",
        "ALU_Gauntlet/web/static/assets/rsl/visuals/rsl-division-badge.svg",
    ):
        assert (ROOT / asset).exists()
    for token in (
        ".rsl-visual-card",
        ".rsl-car-visual",
        ".rsl-track-visual",
        ".rsl-division-visual",
        ".rsl-bracket-live",
        ".rsl-xp-bar",
        "@media(prefers-reduced-motion:reduce)",
    ):
        assert token in css
    for token in (
        "rsl-visual-grid",
        "rsl-car-silhouette.svg",
        "rsl-track-map.svg",
        "rsl-division-badge.svg",
        "Cars, Builds &amp; Defense",
        "Track Intel",
        "6 DIVISIONS",
    ):
        assert token in index
