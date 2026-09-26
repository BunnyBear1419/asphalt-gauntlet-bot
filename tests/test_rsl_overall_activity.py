# Final RSL audit coverage: cross-mode Top Active scoring.\nfrom ALU_Gauntlet.core.rsl_activity import overall_activity_score, with_overall_activity_score


def test_overall_activity_aggregates_cross_rsl_sources():
    record = {
        "gauntlet_matches": 2, "tournament_matches": 3, "rsl_events": 2,
        "media_posts": 4, "defenses": 1, "challenges": 2, "approved_activity": 5,
    }
    assert overall_activity_score(record) == 53
    assert with_overall_activity_score(record)["overall_activity_score"] == 53


def test_overall_activity_ignores_invalid_or_negative_counts():
    assert overall_activity_score({"gauntlet_matches": -10, "media_posts": "bad"}) == 0
