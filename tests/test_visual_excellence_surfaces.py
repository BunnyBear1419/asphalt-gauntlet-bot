from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
css=(ROOT/"ALU_Gauntlet/web/static/app.css").read_text(encoding="utf-8")

def test_visual_excellence_surface_pack():
    for token in (
        "RSL 10/10 SURFACE PACK",
        ".public-profile-hero",
        ".clubs-center-hero",
        ".calendar-board",
        ".tournament-center-page .match-card",
        ".rsl-competitive-chip",
        ".rsl-score-hero",
    ):
        assert token in css

def test_visual_excellence_has_accessible_motion_fallback():
    assert "@media(prefers-reduced-motion:reduce)" in css
