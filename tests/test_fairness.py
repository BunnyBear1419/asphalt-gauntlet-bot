from ALU_Gauntlet.core.fairness import fair_match_snapshot, score_bucket


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
