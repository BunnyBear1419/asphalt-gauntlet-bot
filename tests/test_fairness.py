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
