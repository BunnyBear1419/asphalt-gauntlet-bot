from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYER = (ROOT / "ALU_Gauntlet" / "cogs" / "player.py").read_text(encoding="utf-8")
TICKET = (ROOT / "ALU_Gauntlet" / "cogs" / "ticket_economy.py").read_text(encoding="utf-8")

def test_discord_dashboard_exposes_shared_ticket_economy():
    assert "TicketEconomyButton" in PLAYER
    assert "view.add_item(TicketEconomyButton())" in PLAYER
    assert "BuyTicketView(bot, guild_id, user_id, get_guild_local_date)" in PLAYER
    assert "purchase_daily_ticket" in TICKET

def test_ticket_economy_preserves_daily_expiry_and_five_paid_cap():
    assert "Unused tickets expire at the next daily reset." in TICKET
    assert "\"purchase_limit\":" in TICKET
    assert "/5" in TICKET
