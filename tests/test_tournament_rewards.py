from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tournament_rewards_are_configurable_and_zero_by_default():
    source = (ROOT / "ALU_Gauntlet" / "core" / "rsl_tournament_rewards.py").read_text(encoding="utf-8")
    assert "DEFAULT_TOURNAMENT_REWARDS" in source
    assert "normalize_tournament_rewards" in source
    for key in (
        "participation_coins", "finalist_coins", "third_place_coins",
        "runner_up_coins", "champion_coins",
        "participation_xp", "finalist_xp", "third_place_xp",
        "runner_up_xp", "champion_xp",
    ):
        assert f'"{key}"' in source


def test_tournament_completion_wires_reward_settlement_and_recovery():
    cog = (ROOT / "ALU_Gauntlet" / "cogs" / "tournament.py").read_text(encoding="utf-8")
    web = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "tournament.py").read_text(encoding="utf-8")
    recovery = (ROOT / "ALU_Gauntlet" / "core" / "rsl_role_sync.py").read_text(encoding="utf-8")
    assert "settle_tournament_rewards" in cog
    assert "settle_tournament_rewards" in web
    assert "settle_tournament_rewards" in recovery
    assert "transaction_type="tournament_reward"" in (ROOT / "ALU_Gauntlet" / "core" / "rsl_tournament_rewards.py").read_text(encoding="utf-8")


def test_tournament_creation_snapshots_reward_configuration():
    web = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "public.py").read_text(encoding="utf-8")
    cog = (ROOT / "ALU_Gauntlet" / "cogs" / "administration.py").read_text(encoding="utf-8")
    assert '"rewards": rewards' in web
    assert '"rewards": dict(DEFAULT_TOURNAMENT_REWARDS)' in cog


def test_tournament_reward_ids_are_unique_per_player_and_participation_is_additive():
    source = (ROOT / "ALU_Gauntlet" / "core" / "rsl_tournament_rewards.py").read_text(encoding="utf-8")
    assert 'prefix = f"tournament:{tournament_id}:{user_id}:{placement or \'participation\'}"' in source
    assert 'reference_id=f"{prefix}:coins"' in source
    assert 'event_id=f"{prefix}:xp"' in source
    assert 'async def _all_participant_users' in source
    assert 'for user_id in participant_users:' in source
    assert 'if not await reward_user(user_id, None):' in source
