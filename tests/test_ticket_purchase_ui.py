from pathlib import Path

def test_challenge_offers_extra_ticket_purchase_without_new_public_command():
    text = Path("ALU_Gauntlet/cogs/challenges.py").read_text(encoding="utf-8")
    assert "BuyTicketView" in text
    assert "Unused tickets do not carry over" in text


def test_web_ticket_purchase_api_and_profile_contracts():
    server = Path("ALU_Gauntlet/web/server.py").read_text(encoding="utf-8")
    profile = Path("ALU_Gauntlet/web/static/profile.html").read_text(encoding="utf-8")
    script = Path("ALU_Gauntlet/web/static/player.js").read_text(encoding="utf-8")
    assert 'add_post("/api/player/tickets/purchase", self.player_ticket_purchase)' in server
    assert "async def player_ticket_purchase" in server
    assert "await self.require_guild_member(request)" in server
    assert "purchase_daily_ticket(" in server
    assert '"tickets": ticket_state' in server
    player = Path("ALU_Gauntlet/web/static/player.html").read_text(encoding="utf-8")
    assert 'id="gauntlet-buy-ticket"' in player
    assert 'id="gauntlet-tickets"' in player
    assert 'id="gauntlet-next-ticket-cost"' in player
    assert '/api/player/tickets/purchase?guild_id=' in script
    assert 'unused tickets do not carry over' in player
