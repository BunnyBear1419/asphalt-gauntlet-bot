from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_web_mutation_routes_use_shared_json_object_parser():
    routes = ROOT.joinpath("ALU_Gauntlet", "web", "routes")
    offenders = []
    for path in routes.glob("*.py"):
        if path.name == "core.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "await request.json()" in source:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_club_handlers_have_one_authoritative_web_owner():
    clubs = read("ALU_Gauntlet/web/routes/clubs.py")
    public = read("ALU_Gauntlet/web/routes/public.py")
    for name in ("create_club", "join_club", "leave_club", "update_club", "manage_club_member"):
        assert clubs.count(f"async def {name}(") == 1
        assert f"async def {name}(" not in public


def test_known_discord_economy_nameerror_typo_is_absent():
    source = read("ALU_Gauntlet/cogs/player.py")
    assert "ASPH_THEME_COLOR" not in source


def test_setup_role_constants_are_explicitly_imported():
    source = read("ALU_Gauntlet/web/routes/public.py")
    expected = "XP_LEVEL_ROLES, GAUNTLET_SEASONAL_ROLES, TOURNAMENT_SEASONAL_ROLES, PERMANENT_ACHIEVEMENT_ROLES"
    assert expected in source
    assert "from ...core.rsl_roles import" in source


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


def test_auth_rate_limiter_and_oauth_cookie_hardening():
    core = read("ALU_Gauntlet/web/routes/core.py")
    auth = read("ALU_Gauntlet/web/routes/auth.py")
    assert "import os" in core
    assert 'os.getenv("RSL_TRUSTED_PROXY_IPS"' in core
    assert "hmac.compare_digest(state, cookie_state)" in auth
    assert 'secure=self.auth.public_url.startswith("https://")' in auth


def test_web_sessions_use_datetime_ttl_index():
    auth = read("ALU_Gauntlet/web/auth.py")
    main = read("ALU_Gauntlet/main.py")
    assert "datetime.now(timezone.utc)" in auth
    assert 'name="ttl_web_sessions"' in main
    assert "expireAfterSeconds=0" in main


def test_web_session_cache_and_legacy_ttl_cleanup_are_type_safe():
    auth = read("ALU_Gauntlet/web/auth.py")
    main = read("ALU_Gauntlet/main.py")
    assert "self.sessions[token] = (expiry.timestamp(), user)" in auth
    assert 'delete_many({"expires_at": {"$type": "number"}})' in main
    assert "hasattr(self, "sessions")" not in auth


def test_security_hardening_contracts_fail_closed():
    hardening = read("ALU_Gauntlet/core/rsl_hardening.py")
    ai = read("ALU_Gauntlet/core/rsl_ai_assistant.py")
    core = read("ALU_Gauntlet/web/routes/core.py")
    assert 'digest.update(b"\\0")' in hardening
    assert "MatchState.SETTLED:set()" in hardening
    assert "return str(action).strip().casefold() in ALLOWED_ACTIONS" in ai
    assert "default-src 'self'" in core
    assert "object-src 'none'" in core


def test_scheduled_mongo_workflows_do_not_use_production_secret():
    for path in (
        ".github/workflows/mongodb-backup.yml",
        ".github/workflows/mongodb-backup-verify.yml",
        ".github/workflows/mongodb-restore-test.yml",
    ):
        source = read(path)
        assert "secrets.MONGO_CI_URI" in source
        assert "secrets.MONGO_URI" not in source
