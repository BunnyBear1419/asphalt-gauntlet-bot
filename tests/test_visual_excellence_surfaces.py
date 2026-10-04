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


def test_championship_driver_card():
    html=(ROOT/"ALU_Gauntlet/web/static/public-profile.html").read_text(encoding="utf-8")
    js=(ROOT/"ALU_Gauntlet/web/static/public-profile.js").read_text(encoding="utf-8")
    for token in ("rsl-driver-championship","Driver Championship Card","rsl-card-division","rsl-card-elo","rsl-card-record","rsl-card-winrate","rsl-card-rank"):
        assert token in html
    for token in ("rsl-card-division","rsl-card-elo","rsl-card-record","rsl-card-winrate","rsl-card-rank"):
        assert token in js
    for token in ("RSL CHAMPIONSHIP DRIVER CARD",".rsl-driver-championship",".rsl-driver-card-stats",".rsl-driver-card-badge","@media(max-width:560px)"):
        assert token in css
    
def test_final_competition_surface_regression_matrix():
    surfaces={
        "home":"ALU_Gauntlet/web/static/index.html",
        "gauntlet":"ALU_Gauntlet/web/static/gauntlet-leaderboard.html",
        "tournaments":"ALU_Gauntlet/web/static/tournaments.html",
        "clubs":"ALU_Gauntlet/web/static/clubs.html",
        "profile":"ALU_Gauntlet/web/static/public-profile.html",
        "calendar":"ALU_Gauntlet/web/static/calendar.html",
        "garage":"ALU_Gauntlet/web/static/player.html",
    }
    required_assets=(
        "/static/assets/rsl/visuals/rsl-car-silhouette.svg",
        "/static/assets/rsl/visuals/rsl-track-map.svg",
        "/static/assets/rsl/visuals/rsl-division-badge.svg",
    )
    for name,path in surfaces.items():
        html=(ROOT/path).read_text(encoding="utf-8")
        assert "app.css" in html, name
        assert any(asset in html for asset in required_assets), name

    for token in (
        "--rsl-box",
        "--rsl-box-alt",
        "--rsl-box-line",
        "--rsl-box-accent",
        "prefers-reduced-motion",
        "@media(max-width:600px)",
        ".rsl-competitive-chip",
        ".rsl-score-hero",
        ".rsl-driver-card",
        ".rsl-gauntlet-ladder",
        ".rsl-club-deck",
        ".rsl-match-lane",
    ):
        assert token in css
