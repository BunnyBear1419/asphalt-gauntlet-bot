from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_coin_ledger_uses_a_single_mongodb_transaction_for_balance_and_ledger():
    source = (ROOT / "ALU_Gauntlet" / "core" / "rsl_economy_ledger.py").read_text(encoding="utf-8")
    assert "start_session()" in source
    assert "start_transaction()" in source
    assert "insert_one(document, session=session)" in source
    assert 'update_one(\n                    query,' in source
    assert 'status": "completed"' in source
    assert "Compatibility fallback" in source


def test_activity_reward_rollback_is_bound_to_its_own_message_claim():
    source = (ROOT / "ALU_Gauntlet" / "cogs" / "activity_rewards.py").read_text(encoding="utf-8")
    assert '"activity_reward_claims": {"$ne": str(message.id)}' in source
    assert '"$addToSet": {"activity_reward_claims": str(message.id)}' in source
    assert '"activity_reward_claims": str(message.id)' in source
    assert '"$pull": {"activity_reward_claims": str(message.id)}' in source


def test_activity_reward_claims_reset_with_the_daily_reward_window():
    source = (ROOT / "ALU_Gauntlet" / "cogs" / "activity_rewards.py").read_text(encoding="utf-8")
    assert '"activity_reward_claims": []' in source
    assert '"activity_reward_date": today' in source
    assert '"activity_reward_count": 0' in source

def test_ticket_purchase_settles_ticket_and_coin_debit_in_one_transaction():
    source = (ROOT / "ALU_Gauntlet" / "core" / "rsl_economy.py").read_text(encoding="utf-8")
    assert "async def purchase_daily_ticket" in source
    assert "async with await client.start_session() as session:" in source
    assert "async with session.start_transaction():" in source
    assert '"gauntlet_tickets": 1' in source
    assert '"rsl_coins": -cost' in source
    assert 'insert_one(document, session=session)' in source
    assert 'reference_id = f"ticket:{today}:{purchased + 1}"' in source
    assert 'transaction_id = f"{guild_id}:{user_id}:{reference_id}"' in source


def test_ticket_purchase_resets_daily_state_inside_the_same_transaction():
    source = (ROOT / "ALU_Gauntlet" / "core" / "rsl_economy.py").read_text(encoding="utf-8")
    transaction_section = source.split("async with session.start_transaction():", 1)[1]
    assert '"gauntlet_ticket_date": today' in transaction_section
    assert '"gauntlet_purchased_tickets": 0' in transaction_section
    assert '"gauntlet_tickets": FREE_DAILY_TICKETS' in transaction_section

