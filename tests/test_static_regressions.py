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
    assert '"status": "completed", "rsl_bonus_checked": {"$ne": True}' in assistant
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


def test_gauntlet_role_reconciliation_is_durable():
    sync = read("ALU_Gauntlet/core/rsl_role_sync.py")
    season = read("ALU_Gauntlet/cogs/season.py")
    assert "gauntlet_role_snapshot" in sync
    assert "reconcile_gauntlet_season_roles" in sync
    assert "gauntlet_role_snapshot" in season
    assert "role_reconcile_scheduler.start()" in season
    assert "@tasks.loop(minutes=10)" in season


def test_bonus_recovery_requires_persistent_postcondition():
    source = read("ALU_Gauntlet/core/rsl_recovery.py")
    assert 'refreshed = await db.matches.find_one(' in source
    assert 'refreshed.get("rsl_bonus_checked") is True' in source
    assert '"bonus_failed"' in source


def test_nontransactional_coin_recovery_has_atomic_driver_marker():
    source = read("ALU_Gauntlet/core/rsl_economy_ledger.py")
    assert "hashlib.sha256(transaction_id.encode" in source
    assert "rsl_coin_ledger_markers" in source
    assert "reconcile_pending_coin_transactions" in source


def test_startup_recovers_pending_coin_ledger_rows():
    main = read("ALU_Gauntlet/main.py")
    assert "reconcile_pending_coin_transactions" in main
    assert "await reconcile_pending_coin_transactions(" in main


def test_web_gauntlet_failure_path_imports_shared_recovery():
    source = read("ALU_Gauntlet/web/routes/gauntlet.py")
    assert "from ...core.rsl_recovery import reconcile_processing_challenges" in source


def test_csp_report_only_allows_google_integrations():
    source = read("ALU_Gauntlet/web/routes/core.py")
    assert 'Content-Security-Policy"' in source
    assert "Content-Security-Policy-Report-Only" not in source
    assert "https://www.googletagmanager.com" in source
    assert "https://translate.google.com" in source
    assert "https://translate.googleapis.com" in source
    assert "https://www.gstatic.com" in source


def test_team_tournament_roles_resolve_club_entrants_to_lineup_users():
    source = read("ALU_Gauntlet/core/rsl_tournament_rewards.py")
    cog = read("ALU_Gauntlet/cogs/tournament.py")
    web = read("ALU_Gauntlet/web/routes/tournament.py")
    assert "async def tournament_role_recipients" in source
    assert "async def sync_completed_tournament_roles" in source
    assert "sync_completed_tournament_roles" in cog
    assert "sync_completed_tournament_roles" in web
    assert "sync_completed_tournament_roles" in cog
    assert "sync_completed_tournament_roles" in web


def test_xp_duplicate_is_checked_before_transaction_and_caught_safely():
    source = read("ALU_Gauntlet/core/rsl_xp.py")
    assert 'existing_event = await db.rsl_xp_events.find_one' in source
    assert "from pymongo.errors import DuplicateKeyError" in source
    assert "except DuplicateKeyError:" in source


def test_recovery_only_scans_completed_challenges_missing_bonus_check():
    source = read("ALU_Gauntlet/core/rsl_recovery.py")
    assert '"status": "completed", "rsl_bonus_checked": {"$ne": True}' in source
    assert "rsl_bonus_checked" in source


def test_active_challenge_index_creation_is_guarded():
    source = read("ALU_Gauntlet/main.py")
    assert "duplicate_cursor = db.active_challenges.aggregate" in source
    assert "Skipping active Gauntlet uniqueness index" in source
    assert "Unable to create active Gauntlet uniqueness index" in source


def test_diagnostics_are_not_player_allowlisted():
    source = read("ALU_Gauntlet/core/rsl_ai_assistant.py")
    assert "show_diagnostics" not in source
    assert '"diagnostics"' not in source.split("READ_ONLY_TOPICS", 1)[1].split(")", 1)[0]


def test_media_limits_use_conflict_and_safe_image_bounds():
    source = read("ALU_Gauntlet/web/routes/tournament.py")
    assert 'raise web.HTTPConflict' in source
    assert "image.width > 4096 or image.height > 4096" in source
    assert "Image.DecompressionBombError" in source


def test_shared_recovery_has_single_definition():
    source = read("ALU_Gauntlet/core/rsl_recovery.py")
    assert source.count("async def reconcile_processing_challenges(") == 1


def test_audit_hardening_revision_marker():
    assert True


def test_web_gauntlet_failure_path_imports_shared_recovery_helper():
    source = read("ALU_Gauntlet/web/routes/gauntlet.py")
    assert "from ...core.rsl_recovery import reconcile_processing_challenges" in source
    assert "reconcile_processing_challenges(self.bot.db, str(guild_id))" in source


def test_tournament_completion_role_sync_is_shared():
    rewards = read("ALU_Gauntlet/core/rsl_tournament_rewards.py")
    cog = read("ALU_Gauntlet/cogs/tournament.py")
    web = read("ALU_Gauntlet/web/routes/tournament.py")
    assert "async def sync_completed_tournament_roles" in rewards
    assert "from ..core.rsl_tournament_rewards import sync_completed_tournament_roles" in cog
    assert "from ...core.rsl_tournament_rewards import sync_completed_tournament_roles" in web
    assert "tournament_role_recipients" in rewards


def test_recovery_batches_deterministic_match_reservations():
    source = read("ALU_Gauntlet/core/rsl_recovery.py")
    assert '"_id": {"$in": [f"{challenge_id}:match"' in source
    assert "reservations = {}" in source


def test_xp_role_reconciliation_is_pending_only():
    cog = read("ALU_Gauntlet/cogs/rsl_xp.py")
    xp = read("ALU_Gauntlet/core/rsl_xp.py")
    main = read("ALU_Gauntlet/main.py")
    assert "rsl_xp_role_sync_pending" in cog
    assert "rsl_xp_role_sync_pending" in xp
    assert '"rsl_xp_role_sync_pending": {"$ne": False}' in cog
    assert "rsl_xp_role_sync_pending" in main


def test_gauntlet_settlement_is_atomic_and_deterministic_across_discord_and_web():
    source = read("ALU_Gauntlet/core/core.py")
    cog = read("ALU_Gauntlet/cogs/challenges.py")
    web = read("ALU_Gauntlet/web/routes/gauntlet.py")
    assert 'match_id = settlement_id or f"{guild_id}_{challenger_id}_{opponent_id}_{int(time.time())}"' in source
    assert '"settlement_status": "pending"' in source
    assert 'async with bot.mongo_client.start_session() as session:' in source
    assert 'async with session.start_transaction():' in source
    assert 'settlement_status": "completed"' in source
    assert '"season_points_challenger": courses_beat + (3 if challenger_won else 0)' in source
    assert '"season_points_defender": (5 - courses_beat) + (3 if not challenger_won else 0)' in source
    assert 'settlement_id=f"{active[\'_id\']}:match"' in cog
    assert 'settlement_id=f"{active[\'_id\']}:match"' in web


def test_gauntlet_settlement_retry_refuses_uncertain_driver_state():
    source = read("ALU_Gauntlet/core/core.py")
    assert 'existing_match.get("settlement_status") in (None, "completed")' in source
    assert 'logging.warning("Found incomplete match settlement %s with uncertain DB state; refusing duplicate scoring.", match_id)' in source
    assert 'p1_now.get("elo") == existing_match.get("challenger_elo_after")' in source
    assert 'p2_now.get("elo") == existing_match.get("defender_elo_after")' in source


def test_gauntlet_xp_and_coin_rewards_are_separate_from_match_settlement():
    source = read("ALU_Gauntlet/core/core.py")
    start = source.index("async def process_match_result(")
    end = source.index("class MatchResultPostView", start)
    settlement = source[start:end]
    assert "apply_coin_transaction(" not in settlement
    assert "award_xp(" not in settlement



def test_player_career_uses_selected_live_guild_for_tournament_history():
    source = read("ALU_Gauntlet/web/routes/player.py")
    start = source.index("async def player_career")
    end = source.index("async def player_list", start)
    block = source[start:end]
    assert '"guild_id": str(guild_id)' in block
    assert 'list(guild_ids)' not in block


def test_public_driver_career_uses_selected_live_guild_for_tournament_history():
    source = read("ALU_Gauntlet/web/routes/public.py")
    start = source.index("async def public_driver_career")
    end = source.index("async def ", start + len("async def public_driver_career"))
    block = source[start:end]
    assert '"guild_id": str(guild_id)' in block
    assert '_live_guild_ids_for_user(user)' not in block


def test_recovery_runs_have_bounded_retention():
    recovery = read("ALU_Gauntlet/core/rsl_recovery.py")
    main = read("ALU_Gauntlet/main.py")
    assert '"expires_at": datetime.now(timezone.utc) + timedelta(days=7)' in recovery
    assert 'name="ttl_rsl_recovery_runs"' in main
    assert 'partialFilterExpression={"kind": "recovery_run"}' in main


def test_gated_brand_assets_are_not_publicly_cached():
    source = read("ALU_Gauntlet/web/routes/admin.py")
    start = source.index("async def serve_brand_asset")
    end = source.index("async def admin_csp_diagnostics", start)
    block = source[start:end]
    assert '"Cache-Control": "private, max-age=3600"' in block
    assert 'headers={"Cache-Control":"private, max-age=3600"}' in block


def test_theme_cookie_is_persisted_for_first_paint_restoration():
    theme = read("ALU_Gauntlet/web/static/theme.js")
    core = read("ALU_Gauntlet/web/routes/core.py")
    assert 'document.cookie="rsl_theme="+encodeURIComponent(t)' in theme
    assert 'rsl_theme=([^;]+)' in theme
    assert 'rsl_theme=([^;]+)' in core


def test_clubs_defines_its_discord_stats_loader():
    source = read("ALU_Gauntlet/web/static/clubs.js")
    assert "async function loadPageDiscordStats()" in source
    assert 'fetch("/api/discord-stats"' in source


def test_player_settings_section_links_leave_settings_route():
    source = read("ALU_Gauntlet/web/static/player.html")
    assert 'href="/player#overview"' in source
    assert 'href="/player#gauntlet"' in source
    assert 'href="/player#defense"' in source
    assert 'href="/player#registration"' in source
    assert 'href="/player/settings">Profile &amp; Settings</a>' in source
    assert 'href="/player#career"' in source
    assert 'content:"Changes are saved to your RSL account."' not in source


def test_companion_links_target_shohans_companion():
    index = read("ALU_Gauntlet/web/static/index.html")
    profile = read("ALU_Gauntlet/web/static/profile.html")
    assert 'href="https://alu.shohanlab.com/"' in index
    assert 'href="https://alu.shohanlab.com/"' in profile or 'https://alu.shohanlab.com/' in profile


def test_competition_safe_mode_has_dedicated_api_route():
    core = read("ALU_Gauntlet/web/routes/core.py")
    admin = read("ALU_Gauntlet/web/routes/admin.py")
    page = read("ALU_Gauntlet/web/static/admin.html")
    assert '"/api/admin/competition-safe-mode"' in core
    assert "async def admin_competition_safe_mode" in admin
    assert '"/api/admin/competition-safe-mode"+q()' in page


def test_players_page_uses_shared_rsl_surface_tokens():
    source = read("ALU_Gauntlet/web/static/players.html")
    assert "RSL Players directory — shared page shell" in source
    assert "var(--rsl-box)" in source
    assert "var(--rsl-box-line)" in source


def test_reference_hub_exposes_player_notes_submission_and_leaderboard():
    page = read("ALU_Gauntlet/web/static/gauntlet-references.html")
    routes = read("ALU_Gauntlet/web/routes/core.py")
    gauntlet = read("ALU_Gauntlet/web/routes/gauntlet.py")
    admin = read("ALU_Gauntlet/web/routes/admin.py")
    main = read("ALU_Gauntlet/main.py")
    assert "Contributor Leaderboard" in page
    assert "/api/gauntlet/references/submit" in page
    assert "/api/gauntlet/references/"+'"+encodeURIComponent(id)+"/notes' in page
    assert "/api/gauntlet/references/submit" in routes
    assert "async def gauntlet_reference_submit" in gauntlet
    assert "async def gauntlet_reference_notes" in gauntlet
    assert "async def gauntlet_reference_leaderboard" in gauntlet
    assert "async def admin_reference_review" in admin
    assert "gauntlet_reference_notes" in main


def test_reference_hub_timestamp_notes_seek_and_staff_queue():
    page = read("ALU_Gauntlet/web/static/gauntlet-references.html")
    admin = read("ALU_Gauntlet/web/routes/admin.py")
    core = read("ALU_Gauntlet/web/routes/core.py")
    assert "enablejsapi=1" in page
    assert "function seekVideo(" in page
    assert "data-seek-ref" in page
    assert "seekTo" in page
    assert '"/api/admin/gauntlet/references/review"' in core
    assert "async def admin_reference_review_queue" in admin
    assert 'status": {"$in": ["pending", "approving"]}' in admin
    assert 'gauntlet_references.delete_one' in admin
    assert 'stale_before = now - (10 * 60)' in admin
    assert '"status": "approving"' in admin
    assert '"$set": {"status": "pending", "recovered_at": now}' in admin
    assert '"$unset": {"review_started_by": "", "review_started_at": ""}' in admin

def test_reference_hub_has_video_reference_leaderboard():
    page = read("ALU_Gauntlet/web/static/gauntlet-references.html")
    gauntlet = read("ALU_Gauntlet/web/routes/gauntlet.py")
    assert "Video Leaderboard" in page
    assert "mode=videos" in page
    assert "async function loadContributors()" in page
    assert 'mode == "videos"' in gauntlet
    assert '"seconds": seconds' in gauntlet
    assert "rows[:50]" in gauntlet
