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
