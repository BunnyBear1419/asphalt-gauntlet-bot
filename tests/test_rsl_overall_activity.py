# Final RSL audit coverage: cross-mode Top Active scoring.
from ALU_Gauntlet.core.rsl_activity import overall_activity_score, with_overall_activity_score


def test_overall_activity_aggregates_cross_rsl_sources():
    record = {
        "gauntlet_matches": 2, "tournament_matches": 3, "rsl_events": 2,
        "media_posts": 4, "defenses": 1, "challenges": 2, "approved_activity": 5,
    }
    assert overall_activity_score(record) == 53
    assert with_overall_activity_score(record)["overall_activity_score"] == 53


def test_overall_activity_ignores_invalid_or_negative_counts():
    assert overall_activity_score({"gauntlet_matches": -10, "media_posts": "bad"}) == 0


def test_overall_activity_contract_has_idempotent_persistent_ingestion():
    source = __import__("pathlib").Path("ALU_Gauntlet/core/rsl_activity.py").read_text(encoding="utf-8")
    assert "async def record_activity_event" in source
    assert 'key = f"{guild_id}:{user_id}:{activity_type}:{event_id}"' in source
    assert "rsl_activity_events" in source
    assert "DuplicateKeyError" in source


def test_live_leaderboard_uses_overall_activity_not_raw_match_count():
    source = __import__("pathlib").Path("ALU_Gauntlet/web/server.py").read_text(encoding="utf-8")
    assert "collect_overall_activity_stats" in source
    assert '"overall_activity_score"' in source
    assert '"most_active": sorted(rows, key=lambda x: (-x["overall_activity_score"]' in source


def test_activity_sources_remain_separate_from_chat_xp():
    source = __import__("pathlib").Path("ALU_Gauntlet/core/rsl_activity.py").read_text(encoding="utf-8")
    collector = source.split("async def collect_overall_activity_stats", 1)[1]
    assert "activity_xp" not in collector
