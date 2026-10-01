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
    assert 'hasattr(self, "sessions")' not in auth


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

def test_tournament_media_storage_growth_is_bounded():
    source = read("ALU_Gauntlet/web/routes/tournament.py")
    assert "max_user_media = 20" in source
    assert "max_tournament_media = 100" in source
    assert '"uploaded_by": str(user.user_id)' in source
    assert 'update["$unset"] = {"data": ""}' in source

def test_fairness_division_lookup_failure_fails_closed():
    source = read("ALU_Gauntlet/core/fairness.py")
    assert "same_division = False" in source
    assert "same_division = True" not in source

def test_rsl_role_sync_does_not_silently_swallow_discord_role_failures():
    source = read("ALU_Gauntlet/core/rsl_role_sync.py")
    assert "import logging" in source
    assert "log.exception(" in source
    assert "Failed to add seasonal RSL roles" in source


def test_match_settlement_checks_every_atomic_write_and_has_unique_replay_key():
    core = read("ALU_Gauntlet/core/core.py")
    main = read("ALU_Gauntlet/main.py")
    assert 'winner_result = await bot.db.drivers.update_one(' in core
    assert 'loser_result = await bot.db.drivers.update_one(' in core
    assert 'if getattr(winner_result, "modified_count", 0) != 1 or getattr(loser_result, "modified_count", 0) != 1' in core
    assert 'final_result = await bot.db.matches.update_one(' in core
    assert 'if getattr(final_result, "modified_count", 0) != 1' in core
    assert 'name="idx_gauntlet_settlement_id"' in main
    assert 'settlement_id' in main

def test_rsl_performance_bonus_settlement_is_atomic_and_signed():
    source = read("ALU_Gauntlet/core/match_scoring.py")
    assert "async with await client.start_session() as session:" in source
    assert "async with session.start_transaction():" in source
    assert "if getattr(winner_result, \"modified_count\", 0) != 1 or getattr(loser_result, \"modified_count\", 0) != 1" in source
    assert '"rsl_margin_bonus_applied": True' in source
    assert '"rsl_performance_bonus_applied": margin' in source
    assert "return signed_margin" in source
    assert "return signed_margin if winner_id == challenger_id else -signed_margin" not in source


def test_processing_recovery_is_explicit_and_conservative():
    recovery = read("ALU_Gauntlet/core/rsl_recovery.py")
    challenges = read("ALU_Gauntlet/cogs/challenges.py")
    web = read("ALU_Gauntlet/web/routes/gauntlet.py")
    assistant = read("ALU_Gauntlet/cogs/match_assistant.py")
    assert "PROCESSING_LEASE_SECONDS = 15 * 60" in recovery
    assert 'settlement_status == "completed"' in recovery
    assert 'status": "processing"' in recovery
    assert 'status": "active"' in recovery
    assert '"ticket_burned": True' in recovery
    assert '"settlement_closed": False' in recovery
    assert "reconcile_processing_challenges(bot.db, guild_id)" in challenges
    assert "reconcile_processing_challenges(self.bot.db, str(guild_id))" in web
    assert "await reconcile_processing_challenges(self.bot.db, str(guild_id))" in assistant
    assert 'distinct(\n            "guild_id", {"status": "completed"}\n        )' in assistant
    assert "set(processing_guild_ids) | set(completed_bonus_guild_ids)" in assistant


def test_active_gauntlet_challenge_has_database_level_concurrency_guard():
    main = read("ALU_Gauntlet/main.py")
    core = read("ALU_Gauntlet/core/core.py")
    assert 'name="uniq_active_gauntlet_challenge_per_player"' in main
    assert 'partialFilterExpression={"status": {"$in": ["active", "processing"]}}' in main
    # The selection path must still use the atomic ticket debit/create contract.
    assert '"gauntlet_tickets": {"$gt": 0}' in core
    assert '{"$inc": {"gauntlet_tickets": -1}}' in core
    assert "session=session" in core
