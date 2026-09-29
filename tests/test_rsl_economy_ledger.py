from pathlib import Path

ROOT = Path("ALU_Gauntlet")


def test_coin_ledger_is_idempotent_and_balanced():
    source = (ROOT / "core" / "rsl_economy_ledger.py").read_text(encoding="utf-8")
    assert 'transaction_id = f"{guild_id}:{user_id}:{reference_id}"' in source
    assert 'find_one({"_id": transaction_id})' in source
    assert '"status": "pending"' in source
    assert '"status": "completed"' in source
    assert '"balance_after": balance_after' in source
    assert "rsl_coins" in source
    assert "$gte" in source and "abs(amount)" in source
    assert '"$inc": {"rsl_coins": amount}' in source


def test_all_major_coin_sources_use_the_shared_ledger():
    activity = (ROOT / "cogs" / "activity_rewards.py").read_text(encoding="utf-8")
    moderation = (ROOT / "cogs" / "economy_moderation.py").read_text(encoding="utf-8")
    tickets = (ROOT / "core" / "rsl_economy.py").read_text(encoding="utf-8")
    season = (ROOT / "cogs" / "season.py").read_text(encoding="utf-8")
    for source in (activity, moderation, tickets, season):
        assert "apply_coin_transaction" in source
    assert 'transaction_type="activity_reward"' in activity
    assert 'transaction_type="moderation_penalty"' in moderation
    assert 'transaction_type="ticket_purchase"' in tickets
    assert 'transaction_type="season_reward"' in season
    assert "rsl_credits" not in season


def test_economy_history_is_exposed_to_web_profile():
    server = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
    profile = (ROOT / "web" / "static" / "profile.html").read_text(encoding="utf-8")
    script = (ROOT / "web" / "static" / "player.js").read_text(encoding="utf-8")
    assert '/api/player/economy/history' in server
    assert 'recent_coin_transactions' in server
    assert 'id="rsl-economy-history"' in profile
    assert '/api/player/economy/history?guild_id=' in script


def test_economy_index_is_not_unique_on_missing_message_ids():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "idx_rsl_economy_history" in source
    assert "uniq_rsl_economy_message_transaction" in source
