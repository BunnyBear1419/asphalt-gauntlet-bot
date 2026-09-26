from ALU_Gauntlet.cogs.economy_moderation import classify_violation

def test_moderation_needs_clear_or_repeated_signal():
    assert classify_violation("hello") is None
    assert classify_violation("shit") is None
    assert classify_violation("fuck shit bitch asshole") == "swearing"
    assert classify_violation("same", repeat_count=2) is None
    assert classify_violation("same", repeat_count=3) == "spam"

def test_moderation_detects_advertising_and_strong_unwanted_links():
    assert classify_violation("buy my server https://example.com") == "advertising"
    assert classify_violation("https://bit.ly/example") == "unwanted_link"
    assert classify_violation("https://example.com/race-guide") is None


def test_moderation_daily_cap_is_reserved_atomically_before_ledger_debit():
    from pathlib import Path
    source = Path("ALU_Gauntlet/cogs/economy_moderation.py").read_text(encoding="utf-8")
    assert 'transaction_id = f"{guild_id}:{user_id}:moderation:{message.id}"' in source
    assert 'rsl_economy_transactions.find_one' in source
    assert '"moderation_penalty_total": {' in source
    assert '"$lte": MAX_AUTOMATED_MODERATION_PENALTY_PER_DAY - penalty' in source
    assert '"$inc": {"moderation_penalty_total": penalty}' in source
    assert 'if ledger.get("ok"):' in source
    assert '"$inc": {"moderation_penalty_total": -penalty}' in source
