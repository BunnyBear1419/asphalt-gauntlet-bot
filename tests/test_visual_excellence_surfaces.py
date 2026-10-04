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


def test_competition_surface_polish():
    for token in ("RSL 10/10 surface polish",".tournament-card:hover",".match-card:hover",".club-card:hover",".public-profile-card:hover",".defense-summary",".leader-row:hover",".tournament-detail .bracket-round",".clubs-center-main .club-card-large",".public-club-profile .public-club-hero",".public-club-profile .public-club-stat-grid",".tournament-detail .tournament-competitor:hover",".tournament-detail .tournament-champion"):
        assert token in css


def test_gauntlet_six_division_command_center():
    html=(ROOT/"ALU_Gauntlet/web/static/gauntlet-leaderboard.html").read_text(encoding="utf-8")
    for token in (
        "RSL GAUNTLET COMMAND",
        "Six-Division Competitive Ladder",
        'id="rsl-gauntlet-ladder"',
        'id="rsl-gauntlet-drivers"',
        'id="rsl-gauntlet-top-elo"',
        'id="rsl-gauntlet-top-wins"',
        '"Division 1","Division 2","Division 3","Division 4","Division 5","Division 6"',
    ):
        assert token in html
    for token in (
        "RSL GAUNTLET COMMAND CENTER — SIX-DIVISION LADDER",
        ".rsl-gauntlet-command",
        ".rsl-gauntlet-command-stats",
        ".rsl-gauntlet-command .rsl-ladder-step.current",
        "@media(max-width:600px)",
        "@media(prefers-reduced-motion:reduce)",
    ):
        assert token in css
