from pathlib import Path

from ALU_Gauntlet.core.rsl_activity import (
    CHAT_CREDITS,
    CHAT_XP,
    DAILY_CHAT_REWARD_CAP,
    activity_level,
    chat_reward_available,
    xp_for_level,
    xp_to_next_level,
)


def test_activity_levels_and_xp_thresholds_are_deterministic():
    assert activity_level(0) == 1
    assert xp_for_level(2) == 250
    assert activity_level(249) == 1
    assert activity_level(250) == 2
    assert xp_to_next_level(250) == 750


def test_chat_rewards_have_cooldown_and_daily_cap():
    assert CHAT_CREDITS == 100
    assert CHAT_XP == 10
    assert DAILY_CHAT_REWARD_CAP == 30
    assert chat_reward_available(last_reward_at=None, reward_date=None, today="2026-09-26", reward_count=0, now=1000)
    assert not chat_reward_available(last_reward_at=1000, reward_date="2026-09-26", today="2026-09-26", reward_count=1, now=1099)
    assert chat_reward_available(last_reward_at=1000, reward_date="2026-09-26", today="2026-09-26", reward_count=1, now=1120)
    assert not chat_reward_available(last_reward_at=1000, reward_date="2026-09-26", today="2026-09-26", reward_count=30, now=5000)
    assert chat_reward_available(last_reward_at=1000, reward_date="2026-09-25", today="2026-09-26", reward_count=30, now=1001)


def test_activity_cog_uses_rsl_coin_and_xp_fields():
    source = Path("ALU_Gauntlet/cogs/activity_rewards.py").read_text(encoding="utf-8")
    assert "rsl_coins" in source
    assert "activity_xp" in source
    assert "message.author.bot" in source


def test_profiles_surface_rsl_coins_and_activity_level():
    from pathlib import Path
    profile_html = Path("ALU_Gauntlet/web/static/profile.html").read_text(encoding="utf-8")
    profile_js = Path("ALU_Gauntlet/web/static/profile.js").read_text(encoding="utf-8")
    discord_profile = Path("ALU_Gauntlet/cogs/player.py").read_text(encoding="utf-8")
    assert 'id="rsl-coins"' in profile_html
    assert 'id="activity-level"' in profile_html
    assert 'p.rsl_coins' in profile_js
    assert 'p.activity_xp' in profile_js
    assert "RSL Economy & Activity" in discord_profile
    assert "activity_level(activity_xp)" in discord_profile
