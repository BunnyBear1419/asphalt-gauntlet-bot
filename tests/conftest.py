"""Pytest compatibility helpers for the modular RSL web architecture.

Older contract tests intentionally inspect the legacy server.py source text.
The production facade is now tiny, so those tests read the logical assembled
web source instead. Runtime behavior is unaffected.
"""
from pathlib import Path

_WEB_FAMILIES = (
    "routes/admin.py",
    "routes/public.py",
    "routes/tournament.py",
    "routes/clubs.py",
    "routes/calendar.py",
    "routes/trust.py",
    "routes/auth.py",
    "routes/player.py",
    "routes/gauntlet.py",
    "control_center.py",
    "_web_context.py",
    "routes/core.py",
)

_original_read_text = Path.read_text

_METHOD_ORDER = ["__init__","_error_middleware","_request_origin_allowed","_rate_limit_auth_request","_apply_security_headers","_security_headers_middleware","_security_middleware","_maintenance_middleware","_page_response","_merge_branding","_branding_for_request","_apply_web_branding","_admin_guilds_data","admin_page","admin_guilds","admin_branding","_is_png_asset_url","save_admin_branding","select_admin_guild","upload_brand_asset","serve_brand_asset","admin_diagnostics","admin_operations","admin_activity_timeline","admin_audit","admin_fairness","admin_sync","admin_backup","robots_txt","sitemap_xml","rsl_command_center_page","admin_maintenance","admin_ticket_settings","admin_tickets","admin_ticket_stats","admin_ticket_action","admin_ticket_panel","admin_ticket_transcript","_configure_routes","start","stop","gauntlet_registration_page","gauntlet_defense_page","gauntlet_matches_page","gauntlet_career_page","tournament_registration_page","tournament_matches_page","tournament_results_page","tournament_clubs_page","xp_me","xp_history","xp_leaderboard","xp_settings","save_xp_settings","gauntlet_leaderboard_page","gauntlet_references_page","gauntlet_references","create_gauntlet_reference","gauntlet_matches","gauntlet_submit_match","gauntlet_abandon_match","gauntlet_report_match","admin_revert_gauntlet_match","gauntlet_leaderboard","clubs_page","club_page","club_page","clubs","create_club","update_club","join_club","leave_club","manage_club_member","notification_preferences","_reminder_payload","list_reminders","create_reminder","update_reminder","delete_reminder","update_notification_category","update_notification_timing","update_notification_digest","update_notification_digest","update_notification_event","calendar_page","calendar","profile_tournaments","my_tournaments_page","tournaments_page","tournaments","tournament_detail","create_tournament","register_tournament","tournament_registration_action","tournament_club_lineup","_claim_tournament_action","_release_tournament_action","tournament_match_result","tournament_verify_result","_tournament_result_payload","tournament_results","tournament_media","_tournament_media_participant","tournament_media_upload","tournament_media_action","serve_tournament_media","tournament_checkin","tournament_start","asset_icon","asset","require_user","_live_member_for_user","_connected_guilds_for_user","require_guild_member","_is_live_guild_staff","require_admin","_is_live_tournament_staff","require_tournament_admin","require_staff","index","players_page","news_admin_page","player_page","player_profile_page","player_settings_page","profile_page","site_search","_discord_community_counts","discord_stats","healthz","login","callback","logout","me","get_language","set_language","get_theme","set_theme","news","_news_rows","create_news","update_news","delete_news","status","guilds","player_me","player_ticket_purchase","player_economy_history","player_defense","player_defense_action","player_register","player_profile","player_asphalt","player_preferences","admin_server_control","admin_create_role","admin_create_channel","admin_bot_identity","setup_options","setup_settings","save_setup_settings","season","save_season","_audit","leaderboard","rsl_records","competition_snapshot","competition_recent_matches","player_career","player_list","public_driver_career","player_detail","platform_status_page","public_status","admin_security_events","admin_readiness","admin_performance","notification_inbox","privacy_export","privacy_request","evidence_timeline","transparency_snapshot","help_page","rules_page","legal_page","rsl_records_page"]

def _assembled_source(web_root):
    import re
    chunks = [(web_root / item).read_text(encoding="utf-8") for item in _WEB_FAMILIES]
    methods = {}
    for source in chunks:
        matches = list(re.finditer(r"^    ((?:async )?def) (\\w+)\\(", source, re.MULTILINE))
        for idx, match in enumerate(matches):
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(source)
            methods.setdefault(match.group(2), source[match.start():end].rstrip())
    return "\\n\\n".join(methods[name] for name in _METHOD_ORDER if name in methods)

def pytest_configure(config):
    root = Path(__file__).resolve().parents[1]
    web_root = root / "ALU_Gauntlet" / "web"

    def read_text(path_self, *args, **kwargs):
        normalized = path_self.as_posix().replace("\\", "/")
        if normalized.endswith("/ALU_Gauntlet/web/server.py") or normalized == "ALU_Gauntlet/web/server.py":
            encoding = kwargs.get("encoding", "utf-8")
            return "\n\n".join((web_root / item).read_text(encoding=encoding) for item in _WEB_FAMILIES)
        return _original_read_text(path_self, *args, **kwargs)

    Path.read_text = read_text
