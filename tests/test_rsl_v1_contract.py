"""Broad regression contract for the Racing Syndicate League v1 web/Discord surface.

These checks intentionally stay source-level: CI can run them without Discord, MongoDB,
or a personal browser session while still catching accidental removal of core routes,
permissions, navigation, and cross-feature integration.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
MAIN = ROOT / "ALU_Gauntlet" / "main.py"
NOTIFICATIONS = ROOT / "ALU_Gauntlet" / "cogs" / "notifications.py"
PLAYER = ROOT / "ALU_Gauntlet" / "web" / "static" / "player.html"
PLAYER_JS = ROOT / "ALU_Gauntlet" / "web" / "static" / "player.js"
CLUBS = ROOT / "ALU_Gauntlet" / "web" / "static" / "clubs.js"
TOURNAMENTS = ROOT / "ALU_Gauntlet" / "web" / "static" / "tournaments.js"
RESULTS = ROOT / "ALU_Gauntlet" / "web" / "static" / "tournament-results.html"


def read(path):
    return path.read_text(encoding="utf-8")


def test_v1_core_routes_remain_registered():
    source = read(SERVER)
    routes = (
        'add_get("/api/player/me"',
        'add_get("/api/profile/tournaments"',
        'add_get("/api/calendar"',
        'add_get("/api/leaderboard"',
        'add_get("/api/gauntlet/leaderboard"',
        'add_get("/api/gauntlet/matches"',
        'add_post("/api/gauntlet/matches/submit"',
        'add_get("/api/clubs"',
        'add_post("/api/clubs"',
        'add_post("/api/clubs/update"',
        'add_post("/api/clubs/join"',
        'add_post("/api/clubs/member"',
        'add_get("/api/notifications"',
        'add_put("/api/notifications/category"',
        'add_put("/api/notifications/timing"',
        'add_get("/api/language"',
        'add_post("/api/language"',
    )
    missing = [route for route in routes if route not in source]
    assert not missing, missing


def test_v1_player_profile_covers_identity_and_competitive_fields():
    page = read(PLAYER)
    script = read(PLAYER_JS)
    for marker in (
        "Asphalt Account Connection",
        "Discord Notifications",
        "Timezone",
        "My Career",
        "Club Career",
        "GAME NAME",
        "GAME ID",
    ):
        assert marker in page
    for marker in (
        "/api/player/me?guild_id=",
        "/api/player/profile",
        "/api/player/preferences",
        "/api/player/career?guild_id=",
        "/api/notifications",
        "/api/notifications/category",
        "/api/notifications/timing",
    ):
        assert marker in script


def test_v1_club_surface_covers_roster_profile_and_leadership():
    script = read(CLUBS)
    for marker in (
        "/api/clubs",
        "/api/clubs/join",
        "/api/clubs/update",
        "/api/clubs/member",
        "Promote",
        "Kick",
        "member_count",
        "tournament_record",
        "recent_tournament_results",
        "Club Profile",
    ):
        assert marker in script


def test_v1_calendar_and_discord_notification_contract_is_complete():
    calendar = read(ROOT / "ALU_Gauntlet" / "web" / "static" / "calendar.html")
    script = read(NOTIFICATIONS)
    for marker in (
        "RSL EVENT SCHEDULE",
        "Gauntlet seasons and tournaments stay on one live schedule",
        "Create Personal Reminder",
        "My Reminders",
    ):
        assert marker in calendar
    calendar_script = read(ROOT / "ALU_Gauntlet" / "web" / "static" / "calendar.js")
    assert "/api/calendar" in calendar_script
    for marker in (
        "_calendar_events",
        "season-start-",
        "season-end-",
        '"type": "tournament"',
        "registration",
        "notification_deliveries",
        "lead_days",
        "user.send",
    ):
        assert marker in script


def test_v1_tournament_archive_remains_connected_to_player_and_media():
    tournaments = read(TOURNAMENTS)
    results = read(RESULTS)
    for marker in (
        "mediaGalleryHtml",
        "/api/tournaments/media",
        "result_submission_mode",
        "/api/tournaments/start",
    ):
        assert marker in tournaments
    for marker in (
        "TOURNAMENT CHAMPION",
        "Final Standings",
        "Round-by-Round Results",
        "Tournament Media",
        "Open Live Bracket",
    ):
        assert marker in results


def test_v1_security_contract_covers_auth_permissions_and_upload_bounds():
    source = read(SERVER)
    for marker in (
        "async def require_user",
        "async def require_admin",
        "async def require_guild_member",
        "Only the club leader can edit the club.",
        "Only the club leader can manage members.",
        "Only tournament participants or tournament staff can upload media.",
        "This tournament is configured for Admin Only result submission.",
        "max_size = 12 * 1024 * 1024",
        'Cache-Control":"private, max-age=3600',
        'X-Content-Type-Options":"nosniff',
    ):
        assert marker in source


def test_v1_database_safeguards_cover_clubs_tournaments_and_notifications():
    source = read(MAIN)
    required = (
        "uniq_club_membership_per_guild",
        "uniq_club_name_per_guild",
        "uniq_tournament_action_lock",
        "uniq_active_tournament_player_registration",
        "uniq_active_tournament_club_registration",
        "idx_tournament_media_gallery",
        "uniq_notification_delivery",
    )
    missing = [marker for marker in required if marker not in source]
    assert not missing, missing


def test_v1_shared_shell_keeps_calendar_search_profile_and_companion_ordered():
    source = read(SERVER)
    assert 'calendar_markup + rules_markup + companion_markup' in source
    assert 'id="rsl-search-trigger"' in source
    assert 'id="rsl-profile-nav"' in source
    assert '<a href="/calendar">' in source
    assert 'href="/gauntlet/career"' in source
    assert 'href="/my-tournaments"' in source
    assert 'href="/club"' in source


def test_v1_gauntlet_preserves_six_rsl_divisions_and_alu_ticket_rotation():
    challenges = read(ROOT / "ALU_Gauntlet" / "cogs" / "challenges.py")
    core = read(ROOT / "ALU_Gauntlet" / "core" / "core.py")
    league = read(ROOT / "tests" / "test_core_league.py")
    for marker in (
        "gauntlet_ticket_date",
        "gauntlet_tickets': FREE_DAILY_TICKETS",
        "gauntlet_opponent_refresh_at",
        "4 * 60 * 60",
        "recent_blocked = {str(x.get('user_id')) for x in (user_profile.get('gauntlet_recent_opponents') or [])",
        "rotation_pool = available_candidates or candidates",
        "random.sample(rotation_pool, min(len(rotation_pool), 3))",
        "six-division performance tier",
    ):
        assert marker in challenges
    for marker in (
        '"gauntlet_tickets": {"$gt": 0}',
        '{"$inc": {"gauntlet_tickets": -1}}',
    ):
        assert marker in core
    assert "Searching/matching is free; the ticket is consumed atomically" in challenges
    for marker in (
        "Division 1 — Bronze Tier",
        "Division 2 — Silver Tier",
        "Division 3 — Gold Tier",
        "Division 4 — Platinum Tier",
        "Division 5 — Champ Tier",
        "Division 6 — Legend Tier",
    ):
        assert marker in league


def test_v1_registration_uses_top_five_car_ratings_for_garage_pi():
    core = read(ROOT / "ALU_Gauntlet" / "core" / "core.py")
    server = read(ROOT / "ALU_Gauntlet" / "web" / "server.py")
    player_html = read(ROOT / "ALU_Gauntlet" / "web" / "static" / "player.html")
    player_js = read(ROOT / "ALU_Gauntlet" / "web" / "static" / "player.js")
    for marker in (
        "top_five_car_ranks: list[int] | None = None",
        "garage_pi = sum(top_five_car_ranks)",
        '"top_five_car_ranks": top_five_car_ranks or []',
        '"top_five_car_ranks": top_five_car_ranks',
    ):
        assert marker in core
    for marker in (
        "Exactly five top-car performance ratings are required.",
        "top_five_car_ranks=top_five_car_ranks",
    ):
        assert marker in server
    for marker in (
        "registration-rank-1",
        "registration-rank-5",
        "top_five_car_ranks:topFive",
    ):
        assert marker in player_html + player_js


def test_v1_xp_is_consolidated_into_admin_and_player_profile():
    admin = read(ROOT / "ALU_Gauntlet" / "web" / "static" / "admin.html")
    profile = read(ROOT / "ALU_Gauntlet" / "web" / "static" / "profile.html")
    profile_js = read(ROOT / "ALU_Gauntlet" / "web" / "static" / "profile.js")
    core = read(ROOT / "ALU_Gauntlet" / "core" / "rsl_xp.py")
    server = read(SERVER)
    for marker in ("XP &amp; Progression", "xp-curve", "xp-role-rewards", "xp-admin-save", "/api/xp/settings"):
        assert marker in admin
    for marker in ("XP &amp; Progression", "xp-level", "xp-total", "xp-rank", "xp-weekly", "xp-monthly", "xp-voice-time", "xp-reactions"):
        assert marker in profile
    for marker in ("/api/xp/me", "/api/xp/leaderboard", "xp-level", "needed_xp"):
        assert marker in profile_js
    for marker in ("xp_is_allowed", "excluded_role_ids", "excluded_channel_ids", "allowed_channel_ids", "role_rewards", "async def xp_history"):
        assert marker in core
    assert 'add_get("/api/xp/history", self.xp_history)' in server
    assert 'add_get("/xp", self.xp_page)' not in server
    assert 'XP &amp; Rankings' not in server

def test_v1_xp_remains_separate_from_competitive_scoring():
    xp = read(ROOT / "ALU_Gauntlet" / "core" / "rsl_xp.py")
    cog = read(ROOT / "ALU_Gauntlet" / "cogs" / "rsl_xp.py")
    assert "independent XP layer" in cog
    assert "rsl_xp_events" in xp
    assert "gauntlet_points" not in xp


def test_xp_cooldowns_use_configured_reaction_and_voice_intervals():
    cog = read(ROOT / "ALU_Gauntlet" / "cogs" / "rsl_xp.py")
    for marker in (
        "reaction_cooldown = int(settings.get(\"reaction_cooldown\", 300)",
        "rsl_xp_last_reaction",
        "voice_cooldown = max(1, int(settings.get(\"voice_cooldown\", 180)",
        "rsl_xp_last_voice_bucket",
        "metadata={\"voice_seconds\": voice_cooldown}",
    ):
        assert marker in cog


def test_xp_level_up_controls_and_leader_role_are_wired():
    cog = read(ROOT / "ALU_Gauntlet" / "cogs" / "rsl_xp.py")
    page = read(ROOT / "ALU_Gauntlet" / "web" / "static" / "xp-rankings.html")
    js = read(ROOT / "ALU_Gauntlet" / "web" / "static" / "xp-rankings.js")
    for marker in ("_announce_level", "_sync_leader_role", "level_up_message", "leader_role_id"):
        assert marker in cog
    for marker in ("xp-level-channel", "xp-level-message", "xp-leader-role", "xp-leader-period"):
        assert marker in page
        assert marker in js
