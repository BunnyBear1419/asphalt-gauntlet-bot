from pathlib import Path

from ALU_Gauntlet.core.gauntlet_progression import (
    refresh_cost,
    match_points,
    season_reward_for_rank,
    FREE_DAILY_TICKETS,
    MAX_PURCHASED_TICKETS,
    MAX_DAILY_TICKETS,
    extra_ticket_cost,
    daily_ticket_state,
)


def test_rsl_refresh_costs_match_alu_style_escalation():
    assert [refresh_cost(i) for i in range(5)] == [25_000, 75_000, 125_000, 175_000, 200_000]
    assert refresh_cost(20) == 200_000


def test_daily_ticket_economy_does_not_carry_over_and_escalates_costs():
    assert FREE_DAILY_TICKETS == 5
    assert MAX_PURCHASED_TICKETS == 5
    assert MAX_DAILY_TICKETS == 10
    assert [extra_ticket_cost(i) for i in range(5)] == [10_000, 20_000, 35_000, 55_000, 80_000]
    assert extra_ticket_cost(5) == 0
    state = daily_ticket_state(3, 7)
    assert state["free_tickets"] == 5
    assert state["purchased_tickets"] == 3
    assert state["remaining_tickets"] == 7
    assert state["next_purchase_cost"] == 55_000


def test_rsl_match_points_reward_margin_and_win():
    assert [match_points(i) for i in range(6)] == [0, 1, 2, 6, 7, 8]


def test_season_rewards_are_structured_by_points_rank():
    assert season_reward_for_rank(1) == {"tier": "Season Champion", "credits": 100_000, "badges": 10}
    assert season_reward_for_rank(3)["tier"] == "Podium"
    assert season_reward_for_rank(10)["tier"] == "Elite"
    assert season_reward_for_rank(25)["tier"] == "Contender"
    assert season_reward_for_rank(101)["tier"] == "Finisher"


def test_core_contains_ticket_burn_and_deterministic_settlement_contract():
    source = Path("ALU_Gauntlet/core/core.py").read_text(encoding="utf-8")
    assert 'settlement_version": 2' in source
    assert 'settlement_id": match_id' in source
    assert 'ticket_burned": True' in source
    assert "async def abandon_active_challenge" in source
    assert "class ChallengeRefreshButton" in source


def test_paid_refresh_is_ledger_backed_and_automatic_rotation_is_not_paid_refresh():
    core = Path("ALU_Gauntlet/core/core.py").read_text(encoding="utf-8")
    challenges = Path("ALU_Gauntlet/cogs/challenges.py").read_text(encoding="utf-8")
    assert "transaction_type=\"gauntlet_refresh\"" in core
    assert "reference_id = f\"gauntlet_refresh:{today}:{next_refresh}\"" in core
    assert '"rsl_coins": 1' in core
    assert '"gauntlet_refreshes": 1' in core
    automatic_rotation = challenges.split("if len(selected_opponents) < 1:", 1)[1].split("remaining = tickets", 1)[0]
    assert "'gauntlet_refreshes':" not in automatic_rotation
    assert "RSL Credits" not in core


def test_ticket_is_consumed_only_when_an_opponent_is_selected():
    challenges = Path("ALU_Gauntlet/cogs/challenges.py").read_text(encoding="utf-8")
    core = Path("ALU_Gauntlet/core/core.py").read_text(encoding="utf-8")
    # The search UI must not debit a ticket before the opponent is selected.
    assert "ticket_claim = await bot.db.drivers.update_one" not in challenges
    assert "Searching/matching is free; the ticket is consumed atomically" in challenges
    # Production selection must debit the ticket inside the same Mongo transaction
    # that creates the active challenge.
    assert '"gauntlet_tickets": {"$gt": 0}' in core
    assert '{"$inc": {"gauntlet_tickets": -1}}' in core
    assert 'session=session' in core


def test_legacy_daily_challenge_cap_is_not_authoritative():
    core = Path("ALU_Gauntlet/core/core.py").read_text(encoding="utf-8")
    assert 'raise RuntimeError("DAILY_LIMIT")' not in core
    assert 'raise RuntimeError("NO_TICKETS")' in core
    assert '"ticket_burned": True' in core
    assert '"settlement_closed": True' in core


def test_processing_recovery_reopens_only_without_a_settlement_reservation():
    core = Path("ALU_Gauntlet/core/core.py").read_text(encoding="utf-8")
    assert 'elif not match:' in core
    assert 'time.time() - processing_at > 15 * 60' in core
    assert '"status": "active", "last_reminder": 0' in core


def test_matchmaking_does_not_persist_daily_ticket_reset_before_selection():
    source = Path("ALU_Gauntlet/cogs/challenges.py").read_text(encoding="utf-8")
    start = source.index("ticket_date = user_profile.get('gauntlet_ticket_date')")
    end = source.index("tickets = int(user_profile.get('gauntlet_tickets'", start)
    block = source[start:end]
    assert "await bot.db.drivers.update_one" not in block
    assert "authoritative reset" in block
    assert "let the selection transaction" in block
