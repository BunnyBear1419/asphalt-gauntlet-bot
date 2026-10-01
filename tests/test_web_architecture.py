from pathlib import Path
ROOT=Path(__file__).parents[1]; WEB=ROOT/"ALU_Gauntlet"/"web"

def _raw(path):
    with path.open("r", encoding="utf-8") as handle:
        return handle.read()

def test_server_is_compatibility_facade():
    src=_raw(WEB/"server.py")
    assert len(src.splitlines()) < 20
    assert "from .control_center import WebControlCenter" in src

def test_control_center_is_composed_from_route_families():
    src=_raw(WEB/"control_center.py")
    for name in ("CoreRoutesMixin","AdminRoutesMixin","GauntletRoutesMixin","TournamentRoutesMixin","ClubsRoutesMixin","CalendarRoutesMixin","TrustRoutesMixin","AuthRoutesMixin","PlayerRoutesMixin","PublicRoutesMixin"):
        assert name in src

def test_route_families_exist():
    for name in ("core","admin","gauntlet","tournament","clubs","calendar","trust","auth","player","public"):
        assert (WEB/"routes"/f"{name}.py").exists()


def test_registered_routes_have_a_mixin_handler():
    import ast
    core = ast.parse(_raw(WEB / "routes" / "core.py"))
    registered = set()
    for node in ast.walk(core):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not node.func.attr.startswith("add_") or len(node.args) < 2:
            continue
        target = node.args[1]
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
            registered.add(target.attr)
    handlers = set()
    for path in (WEB / "routes").glob("*.py"):
        tree = ast.parse(_raw(path))
        handlers.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    missing = sorted(registered - handlers)
    assert not missing, f"Route registrations reference missing WebControlCenter handlers: {missing}"


def test_core_middleware_decorators_are_not_duplicated():
    src = _raw(WEB / "routes" / "core.py")
    assert "@web.middleware\\n\\n@web.middleware" not in src
