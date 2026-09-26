from pathlib import Path

def test_challenge_offers_extra_ticket_purchase_without_new_public_command():
    text = Path("ALU_Gauntlet/cogs/challenges.py").read_text(encoding="utf-8")
    assert "BuyTicketView" in text
    assert "Unused tickets do not carry over" in text
