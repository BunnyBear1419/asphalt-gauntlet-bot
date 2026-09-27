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
