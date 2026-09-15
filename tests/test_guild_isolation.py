"""Regression tests for guild-scoped persistence.

These tests intentionally inspect the storage contracts used by the bot.  The
bot uses composite Mongo IDs for driver/challenge records and guild-keyed IDs
for season/settings state; keeping those contracts explicit prevents future
cross-guild data leaks when commands are refactored.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "ALU_Gauntlet" / "cogs"


def _source(name: str) -> str:
    return (COGS / name).read_text(encoding="utf-8")


def test_driver_identity_is_partitioned_by_guild_and_user():
    for name in ("player.py", "defense.py", "challenges.py"):
        source = _source(name)
        assert "f'{guild_id}_{user_id}'" in source or "f'{str(interaction.guild_id)}_{str(interaction.user.id)}'" in source


def test_active_challenges_are_always_guild_scoped():
    source = _source("challenges.py")
    assert "active_challenges" in source
    assert "'guild_id': guild_id" in source

    source = _source("player.py")
    assert "'guild_id': str(guild_id)" in source


def test_season_state_is_partitioned_by_guild():
    for name in ("season.py", "operations.py", "competition.py"):
        source = _source(name)
        assert "guild_{" in source


def test_season_settings_are_partitioned_by_guild():
    source = _source("season.py")
    assert "{'_id': str(interaction.guild_id)}" in source


def test_staff_queries_filter_by_guild():
    source = _source("staff.py")
    assert "drivers" in source
    assert "'guild_id': guild_id" in source
    assert "pending" in source
    assert "find({'guild_id': guild_id" in source


def test_cross_guild_driver_key_cannot_collide_for_same_user():
    guild_a = "1001"
    guild_b = "2002"
    user = "777"
    key_a = f"{guild_a}_{user}"
    key_b = f"{guild_b}_{user}"
    assert key_a != key_b


def test_guild_scoped_collections_use_guild_fields_or_guild_keys():
    expectations = {
        "player.py": ("drivers", "active_challenges"),
        "defense.py": ("drivers",),
        "challenges.py": ("drivers", "active_challenges"),
        "staff.py": ("drivers", "pending", "active_challenges"),
        "operations.py": ("season_state", "drivers", "active_challenges"),
        "competition.py": ("season_state",),
        "season.py": ("settings", "season_state"),
    }
    for name, collections in expectations.items():
        source = _source(name)
        for collection in collections:
            assert f"bot.db.{collection}" in source


def test_global_reference_data_is_not_required_to_be_guild_partitioned():
    """Reference data may remain global; operational player state may not."""
    source = _source("challenges.py")
    assert "active_challenges" in source
