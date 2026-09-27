from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_gauntlet_quit_recovery_is_available_on_discord_and_web():
    player = (ROOT / "ALU_Gauntlet/cogs/player.py").read_text(encoding="utf-8")
    server = (ROOT / "ALU_Gauntlet/web/server.py").read_text(encoding="utf-8")
    page = (ROOT / "ALU_Gauntlet/web/static/gauntlet-matches.html").read_text(encoding="utf-8")

    assert "class AbandonGauntletButton" in player
    assert "abandon_active_challenge(guild_id, user_id, \"quit\")" in player
    assert "view.add_item(AbandonGauntletButton())" in player

    assert 'add_post("/api/gauntlet/matches/abandon", self.gauntlet_abandon_match)' in server
    assert "async def gauntlet_abandon_match" in server
    assert 'abandon_active_challenge(str(guild_id), uid, "quit")' in server

    assert 'data-quit-id' in page
    assert '/api/gauntlet/matches/abandon' in page
    assert "consumed ticket will not be restored" in page


def test_web_submission_uses_reservation_aware_recovery():
    server = (ROOT / "ALU_Gauntlet/web/server.py").read_text(encoding="utf-8")
    assert "reconcile_processing_challenges" in server
    assert 'reservation = await self.bot.db.matches.find_one' in server
    assert 'if reservation:\n                await reconcile_processing_challenges(str(guild_id))' in server
    assert 'else:\n                await release_active_challenge(active["_id"])' in server

def test_match_report_and_safe_revert_are_available_on_the_web():
    core = (ROOT / "ALU_Gauntlet/core/core.py").read_text(encoding="utf-8")
    server = (ROOT / "ALU_Gauntlet/web/server.py").read_text(encoding="utf-8")

    assert "async def revert_match_settlement" in core
    assert '"challenger_elo_before"' in core
    assert '"defender_elo_before"' in core
    assert '"PLAYER_STATE_CHANGED"' in core
    assert '"LATER_MATCH_EXISTS"' in core
    assert "lap_time_history" in core

    assert 'add_post("/api/gauntlet/matches/report", self.gauntlet_report_match)' in server
    assert 'add_post("/api/admin/gauntlet/matches/revert", self.admin_revert_gauntlet_match)' in server
    assert "async def gauntlet_report_match" in server
    assert "async def admin_revert_gauntlet_match" in server
    assert "revert_match_settlement" in server

def test_web_recovery_ui_exposes_report_and_admin_revert_controls():
    matches = (ROOT / "ALU_Gauntlet/web/static/gauntlet-matches.html").read_text(encoding="utf-8")
    admin = (ROOT / "ALU_Gauntlet/web/static/admin.html").read_text(encoding="utf-8")
    assert 'data-report-id' in matches
    assert '/api/gauntlet/matches/report' in matches
    assert 'recovery-match-id' in admin
    assert 'recovery-revert' in admin
    assert '/api/admin/gauntlet/matches/revert' in admin
