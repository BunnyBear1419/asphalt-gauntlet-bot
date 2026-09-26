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
