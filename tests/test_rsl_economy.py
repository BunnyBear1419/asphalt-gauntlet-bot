from ALU_Gauntlet.core.rsl_economy import (
    MAX_AUTOMATED_MODERATION_PENALTY_PER_DAY,
    MAX_AUTOMATED_MODERATION_PENALTY_PER_INCIDENT,
    can_afford,
    moderation_penalty,
    next_ticket_purchase,
)


def test_ticket_purchase_requires_real_balance_and_stops_at_five():
    assert next_ticket_purchase(0, 9_999)["next_cost"] == 10_000
    assert not next_ticket_purchase(0, 9_999)["can_afford"]
    assert next_ticket_purchase(0, 10_000)["can_afford"]
    assert next_ticket_purchase(5, 1_000_000)["next_cost"] == 0
    assert not next_ticket_purchase(5, 1_000_000)["can_afford"]


def test_moderation_penalties_are_bounded_and_reason_specific():
    assert moderation_penalty("spam") == 500
    assert moderation_penalty("swearing") == 250
    assert moderation_penalty("advertising") == 2_500
    assert moderation_penalty("unwanted_link") == 2_500
    assert moderation_penalty("unknown") == 0
    assert MAX_AUTOMATED_MODERATION_PENALTY_PER_INCIDENT == 2_500
    assert MAX_AUTOMATED_MODERATION_PENALTY_PER_DAY == 10_000


def test_coin_balance_cannot_go_negative_for_affordability_checks():
    assert can_afford(0, 1) is False
    assert can_afford(-500, 0) is True
    assert can_afford(25_000, 25_000) is True


def test_purchase_transaction_source_is_atomic_and_daily_reset_is_non_bankable():
    from pathlib import Path
    source = Path("ALU_Gauntlet/core/rsl_economy.py").read_text(encoding="utf-8")
    assert '"gauntlet_purchased_tickets": 0' in source
    assert '"gauntlet_tickets": FREE_DAILY_TICKETS' in source
    assert '"rsl_coins": {"$gte": cost}' in source
    assert '"gauntlet_tickets": {"$lt": MAX_DAILY_TICKETS}' in source
    assert '"rsl_coins": -cost' in source
