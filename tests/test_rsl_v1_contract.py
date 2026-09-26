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
        "/api/profile/tournaments",
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
        "/api/calendar",
        "custom-reminder",
    ):
        assert marker in calendar
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
    assert 'calendar_markup + companion_markup' in source
    assert 'id="rsl-search-trigger"' in source
    assert 'id="rsl-profile-nav"' in source
    assert '<a href="/calendar">' in source
    assert 'href="/gauntlet/career"' in source
    assert 'href="/my-tournaments"' in source
    assert 'href="/club"' in source
