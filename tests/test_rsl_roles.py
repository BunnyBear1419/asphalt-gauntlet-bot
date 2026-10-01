"""Regression tests for RSL XP and seasonal role policy."""
from ALU_Gauntlet.core.rsl_roles import (
    MEDIA_UNLOCK_LEVEL,
    SEASONAL_ROLES,
    build_gauntlet_season_roles,
    build_tournament_season_roles,
    media_unlocked,
    permanent_achievement_roles,
    reconcile_seasonal_roles,
    build_tournament_season_roles,
    xp_rank,
)


def test_xp_rank_thresholds_and_media_unlock():
    assert xp_rank(1) is None
    assert xp_rank(5) == "Bronze"
    assert xp_rank(10) == "Silver"
    assert xp_rank(25) == "Gold"
    assert xp_rank(50) == "Platinum"
    assert xp_rank(75) == "Champion"
    assert xp_rank(100) == "Legend"
    assert MEDIA_UNLOCK_LEVEL == 10
    assert not media_unlocked(9)
    assert media_unlocked(10)


def test_gauntlet_seasonal_roles_follow_current_season_stats():
    roles = build_gauntlet_season_roles(
        division_winners={1: "101", 2: "102", 6: "106"},
        champion_user_id="101",
        player_stats=[
            {"user_id": "101", "wins": 8, "gauntlet_points": 120,
             "defense_wins": 2, "challenge_wins": 6, "improvement": 5, "win_streak": 4},
            {"user_id": "202", "wins": 10, "gauntlet_points": 140,
             "defense_wins": 5, "challenge_wins": 4, "improvement": 12, "win_streak": 7},
        ],
        overall_activity_stats=[
            {"user_id": "101", "overall_activity_score": 40},
            {"user_id": "202", "overall_activity_score": 55},
        ],
    )
    assert roles["Division 1 Winner"] == ["101"]
    assert roles["Division 2 Winner"] == ["102"]
    assert roles["Top Active"] == ["202"]
    assert roles["Top Wins"] == ["202"]
    assert roles["Top Player"] == ["202"]
    assert roles["Top Defender"] == ["202"]
    assert roles["Most Improved"] == ["202"]
    assert roles["Win Streak"] == ["202"]
    assert roles["Season Champion"] == ["101"]


def test_statistical_ties_share_the_role():
    roles = build_gauntlet_season_roles(
        division_winners={},
        player_stats=[
            {"user_id": "1", "wins": 10},
            {"user_id": "2", "wins": 10},
        ],
    )
    assert roles["Top Wins"] == ["1", "2"]


def test_tournament_roles_support_current_season_results():
    roles = build_tournament_season_roles(
        tournament_champion="10",
        runner_up="20",
        third_place="30",
        finalists=["10", "20", "30", "40"],
        mvp="10",
        leader_user_id="20",
        all_star_users=["10", "40"],
        player_stats=[
            {"user_id": "10", "tournament_wins": 3},
            {"user_id": "40", "tournament_wins": 5},
        ],
    )
    assert roles["Tournament Champion"] == ["10"]
    assert roles["Tournament Runner-Up"] == ["20"]
    assert roles["Tournament 3rd Place"] == ["30"]
    assert roles["Tournament Finalist"] == ["10", "20", "30", "40"]
    assert roles["Top Tournament Wins"] == ["40"]


def test_new_season_removes_old_seasonal_winner_roles():
    current = {
        "old": {"Division 1 Winner", "Top Active", "Tournament Champion"},
        "new": {"Top Wins"},
    }
    desired = {
        "Division 1 Winner": ["new"],
        "Top Active": ["new"],
        "Top Wins": ["new"],
        "Tournament Champion": ["new"],
    }
    changes = reconcile_seasonal_roles(current_roles=current, desired_roles=desired)
    assert changes["old"]["remove"] == [
        "Division 1 Winner", "Top Active", "Tournament Champion"
    ]
    assert changes["new"]["add"] == [
        "Division 1 Winner", "Top Active", "Tournament Champion"
    ]
    assert "Top Wins" not in changes["new"]["add"]
    assert set(SEASONAL_ROLES) >= {"Division 1 Winner", "Tournament Champion"}


def test_permanent_achievements_never_appear_in_seasonal_removals():
    current = {"old": {"Tournament Participant", "Tournament Champion"}}
    desired = {"Tournament Champion": ["new"]}
    changes = reconcile_seasonal_roles(current_roles=current, desired_roles=desired)
    assert changes["old"]["remove"] == ["Tournament Champion"]
    assert "Tournament Participant" not in changes["old"]["remove"]
    assert permanent_achievement_roles(
        tournament_participant=True,
        tournament_veteran=True,
        grand_champion=True,
    ) == ["Tournament Participant", "Tournament Veteran", "Grand Champion"]

def test_discord_role_sync_is_wired_to_season_lifecycle():
    sync = __import__("pathlib").Path("ALU_Gauntlet/core/rsl_role_sync.py").read_text(encoding="utf-8")
    season = __import__("pathlib").Path("ALU_Gauntlet/cogs/season.py").read_text(encoding="utf-8")
    assert "sync_gauntlet_season_roles" in sync
    assert "clear_gauntlet_season_roles" in sync
    assert "sync_xp_rank_role" in sync
    assert "sync_gauntlet_season_roles(" in season
    assert "clear_gauntlet_season_roles(" in season
    assert "activity_level(" in season
    assert "existing_ids = {role.id for role in member.roles}" in sync
    assert "managed[name].id in existing_ids" in sync
    assert "managed[current].id not in existing_ids" in sync


def test_tournament_role_builder_tracks_finalists_and_replacement_roles():
    roles = build_tournament_season_roles(
        tournament_champion="10",
        runner_up="20",
        third_place="30",
        finalists=["10", "20", "30", "40"],
    )
    assert roles["Tournament Champion"] == ["10"]
    assert roles["Tournament Runner-Up"] == ["20"]
    assert roles["Tournament 3rd Place"] == ["30"]
    assert roles["Tournament Finalist"] == ["10", "20", "30", "40"]


def test_xp_role_reconciliation_task_is_durable():
    source = __import__("pathlib").Path("ALU_Gauntlet/cogs/rsl_xp.py").read_text(encoding="utf-8")
    assert "@tasks.loop(minutes=10)" in source
    assert "role_reconcile_tick.start()" in source
    assert "rsl_xp" in source
    assert "await self._sync_level(guild.id, user_id, member, settings)" in source
