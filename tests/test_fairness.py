from ALU_Gauntlet.core.fairness import fair_match_snapshot, normalize_elo, score_bucket
from ALU_Gauntlet.web.players import PlayerService


def test_score_bucket_is_perspective_aware():
    assert score_bucket(5, True) == "5-0"
    assert score_bucket(5, False) == "0-5"
    assert score_bucket(4, True) == "4-1"
    assert score_bucket(4, False) == "1-4"
    assert score_bucket(3, True) == "3-2"
    assert score_bucket(3, False) == "2-3"


def test_fair_match_snapshot_reports_gaps_without_prediction():
    row = fair_match_snapshot(
        {"elo": 1000, "garage_pi": 12000},
        {"elo": 1085, "garage_pi": 12400},
    )
    assert row["elo_gap"] == 85
    assert row["pi_gap"] == 400
    assert "win" not in row["summary"].lower()
    assert "prediction" not in row["summary"].lower()


def test_score_buckets_cover_all_five_race_outcomes():
    assert {score_bucket(i, True) for i in range(6)} == {"5-0", "4-1", "3-2", "2-3", "1-4", "0-5"}


def test_repeat_opponent_protection_and_fair_match_contract_are_wired():
    from pathlib import Path
    source = Path("ALU_Gauntlet/cogs/challenges.py").read_text(encoding="utf-8")
    assert "gauntlet_recent_opponents" in source
    assert "fair_match_snapshot" in source
    assert "rotation_pool = available_candidates or candidates" in source


def test_staff_fairness_review_is_advisory():
    from pathlib import Path
    source = Path("ALU_Gauntlet/core/fairness.py").read_text(encoding="utf-8")
    assert "advisory_only" in source
    assert "automatic" not in source.lower() or "automatically accuse" in source.lower()



def test_elo_normalization_rejects_non_finite_and_bad_values():
    assert normalize_elo(1200) == 1200
    assert normalize_elo("1350.9") == 1350
    assert normalize_elo(None) == 1000
    assert normalize_elo("NaN") == 1000
    assert normalize_elo(float("inf")) == 1000
    assert normalize_elo(float("-inf")) == 1000


def test_player_serialization_never_exposes_non_finite_elo():
    row = PlayerService._safe({"_id": "g_u", "guild_id": "g", "user_id": "u", "elo": float("nan")})
    assert row["elo"] == 1000


def test_fair_match_snapshot_normalizes_invalid_elo():
    row = fair_match_snapshot({"elo": float("nan")}, {"elo": float("inf")})
    assert row["challenger_elo"] == 1000
    assert row["opponent_elo"] == 1000
    assert row["elo_gap"] == 0
