from pathlib import Path
ROOT=Path(__file__).parents[1]; WEB=ROOT/"ALU_Gauntlet"/"web"
def test_server_is_compatibility_facade():
    src=(WEB/"server.py").read_text(encoding="utf-8"); assert len(src.splitlines()) < 20; assert "from .control_center import WebControlCenter" in src
def test_control_center_is_composed_from_route_families():
    src=(WEB/"control_center.py").read_text(encoding="utf-8")
    for name in ("CoreRoutesMixin","AdminRoutesMixin","GauntletRoutesMixin","TournamentRoutesMixin","ClubsRoutesMixin","CalendarRoutesMixin","TrustRoutesMixin","AuthRoutesMixin","PlayerRoutesMixin","PublicRoutesMixin"): assert name in src
def test_route_families_exist():
    for name in ("core","admin","gauntlet","tournament","clubs","calendar","trust","auth","player","public"): assert (WEB/"routes"/f"{name}.py").exists()
