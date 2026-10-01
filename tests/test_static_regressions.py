from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_web_mutation_routes_use_shared_json_object_parser():
    routes = ROOT.joinpath("ALU_Gauntlet", "web", "routes")
    offenders = []
    for path in routes.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "await request.json()" in source:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_club_handlers_have_one_authoritative_web_owner():
    clubs = read("ALU_Gauntlet/web/routes/clubs.py")
    public = read("ALU_Gauntlet/web/routes/public.py")
    for name in ("create_club", "join_club", "leave_club", "update_club", "manage_club_member"):
        assert len(re.findall(rf"async def {name}\\(", clubs)) == 1
        assert not re.search(rf"async def {name}\\(", public)


def test_known_discord_economy_nameerror_typo_is_absent():
    source = read("ALU_Gauntlet/cogs/player.py")
    assert "ASPH_THEME_COLOR" not in source


def test_setup_role_constants_are_explicitly_imported():
    source = read("ALU_Gauntlet/web/routes/public.py")
    assert "from ..core.rsl_roles import XP_LEVEL_ROLES, GAUNTLET_SEASONAL_ROLES, TOURNAMENT_SEASONAL_ROLES, PERMANENT_ACHIEVEMENT_ROLES" in source


def test_oauth_state_is_cookie_bound():
    source = read("ALU_Gauntlet/web/routes/auth.py")
    assert 'set_cookie("rsl_oauth_state", state' in source
    assert "consume_state" in source


def test_release_marker_rejects_non_sha_values():
    source = read("ALU_Gauntlet/release.py")
    assert r"[0-9a-fA-F]{40}" in source
    assert 'return "unknown"' in source


def test_deploy_has_undefined_name_and_validated_rollback_gates():
    source = read(".github/workflows/deploy.yml")
    assert "ruff check ALU_Gauntlet tests --select F821" in source
    assert '^[0-9a-fA-F]{40}$' in source
    assert "PREVIOUS_SHA" in source
