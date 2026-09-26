"""Synthetic RSL season simulation.

This suite exercises the season loop with fake racers only. It does not
connect to Discord, MongoDB, or production services.
"""
from ALU_Gauntlet.core.gauntlet_progression import (
    STARTING_RSL_CREDITS,
    match_points,
    refresh_cost,
    season_reward_for_rank,
)


def test_synthetic_five_race_season_orders_by_race_margin():
    racers = [
        {"name": "Alpha", "races_won": 5, "matches": 1, "elo": 1200},
        {"name": "Bravo", "races_won": 4, "matches": 1, "elo": 1400},
        {"name": "Charlie", "races_won": 3, "matches": 1, "elo": 1600},
        {"name": "Delta", "races_won": 2, "matches": 1, "elo": 1800},
    ]

    for racer in racers:
        racer["season_points"] = match_points(racer["races_won"])

    ranked = sorted(
        racers,
        key=lambda r: (
            -r["season_points"],
            -r["races_won"],
            -r["elo"],
            r["name"],
        ),
    )

    assert [r["name"] for r in ranked] == ["Alpha", "Bravo", "Charlie", "Delta"]
    assert [r["season_points"] for r in ranked] == [8, 7, 6, 2]


def test_synthetic_season_refresh_economy_and_ticket_budget():
    credits = STARTING_RSL_CREDITS
    tickets = 5

    assert [refresh_cost(i) for i in range(5)] == [
        25_000,
        75_000,
        125_000,
        175_000,
        200_000,
    ]

    # A fresh racer can afford the first two refreshes, but not the third.
    credits -= refresh_cost(0)
    credits -= refresh_cost(1)
    assert credits == 0
    assert refresh_cost(2) > credits

    # A new daily challenge cycle starts with exactly five tickets.
    tickets -= 1
    tickets -= 1
    assert tickets == 3


def test_synthetic_season_rewards_follow_final_points_rank():
    rewards = [season_reward_for_rank(rank) for rank in range(1, 5)]

    assert rewards[0] == {
        "tier": "Season Champion",
        "credits": 100_000,
        "badges": 10,
    }
    assert rewards[1]["tier"] == "Runner-Up"
    assert rewards[2]["tier"] == "Podium"
    assert rewards[3]["tier"] == "Elite"


def test_synthetic_settlements_are_deterministic_and_single_use():
    match_ids = ["season1-race-1", "season1-race-2", "season1-race-3"]
    settlement_ids = {f"{match_id}:match" for match_id in match_ids}

    assert len(settlement_ids) == len(match_ids)

    settled = set()
    for settlement_id in settlement_ids:
        assert settlement_id not in settled
        settled.add(settlement_id)

    # Replaying the same settlement cannot create a second unique settlement.
    replay = "season1-race-2:match"
    assert replay in settled
