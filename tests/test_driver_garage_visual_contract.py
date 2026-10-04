from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "ALU_Gauntlet" / "web" / "static"


def test_driver_garage_deck_contract():
    player = (STATIC / "player.html").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    js = (STATIC / "rsl-visual-excellence.js").read_text(encoding="utf-8")

    for marker in (
        'id="garage"',
        "Race Machine Deck",
        "GARAGE PI",
        'id="rsl-garage-rank-1"',
        'id="rsl-garage-rank-5"',
        "SIX-DIVISION PATH",
        "Division 1",
        "Division 6",
        "/static/assets/rsl/visuals/rsl-car-silhouette.svg",
    ):
        assert marker in player

    for marker in (
        "RSL DRIVER GARAGE DECK",
        ".rsl-driver-garage",
        ".rsl-garage-layout",
        ".rsl-garage-slots",
        ".rsl-division-steps",
        "@media(prefers-reduced-motion:reduce)",
    ):
        assert marker in css

    for marker in ("registration-rank-", "rsl-garage-pi", "syncGarage"):
        assert marker in js


def test_driver_garage_is_responsive():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "@media(max-width:900px)" in css
    assert "@media(max-width:600px)" in css
    assert ".rsl-division-steps{grid-template-columns:repeat(2,1fr)}" in css
