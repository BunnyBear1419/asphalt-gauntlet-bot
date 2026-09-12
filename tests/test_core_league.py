import sys
from pathlib import Path
import asyncio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main


def test_division_boundaries():
    cases = [
        (0, "Division 1 — Bronze Tier"),
        (8000, "Division 1 — Bronze Tier"),
        (8001, "Division 2 — Silver Tier"),
        (11500, "Division 2 — Silver Tier"),
        (11501, "Division 3 — Gold Tier"),
        (15000, "Division 3 — Gold Tier"),
        (15001, "Division 4 — Platinum Tier"),
        (18500, "Division 4 — Platinum Tier"),
        (18501, "Division 5 — Champ Tier"),
        (22000, "Division 5 — Champ Tier"),
        (22001, "Division 6 — Legend Tier"),
        (50000, "Division 6 — Legend Tier"),
    ]
    for pi, expected in cases:
        assert expected in main.get_division_for_pi(pi)["name"]


def test_division_mongo_ranges_match_boundaries():
    for division in main.PI_DIVISIONS:
        query = main.division_mongo_query(division)
        assert query["$gte"] == division["min"]
        if division["max"] is None:
            assert "$lt" not in query
        else:
            assert query["$lt"] == division["max"]


def test_lap_time_round_trip():
    for value in [1, 999, 1000, 61523, 359999, 5999999]:
        assert main.parse_lap_time(main.format_lap_time(value)) == value
    assert main.parse_lap_time("0:00.000") == -1


def test_lap_time_rejects_invalid_values():
    invalid = ["", "1:2.345", "01:02.34", "1:60.000", "abc", "1:02.0000"]
    for value in invalid:
        assert main.parse_lap_time(value) == -1


def test_five_course_defense_validation():
    assert not main.has_5_course_defense({})
    assert not main.has_5_course_defense({"defense_locked": {"courses": []}})
    assert not main.has_5_course_defense({"defense_locked": {"courses": [1, 2, 3, 4]}})
    valid_courses = [
        {
            "track": main.ALU_TRACKS[i],
            "car": main.ALU_CARS[i],
            "ms": 60000 + i,
            "car_rank": 1,
        }
        for i in range(5)
    ]
    assert main.has_5_course_defense({"defense_locked": {"courses": valid_courses}})


def test_elo_is_bounded_and_streak_bonus_caps():
    winner, loser, bonus = main.calculate_elo_change(1000, 1000, winner_streak=100)
    assert winner >= 100
    assert loser >= 100
    assert bonus == 20


def test_elo_favors_upset_less_than_expected_win():
    equal_winner, equal_loser, _ = main.calculate_elo_change(1000, 1000)
    underdog_winner, underdog_loser, _ = main.calculate_elo_change(800, 1200)
    assert equal_winner > 1000
    assert equal_loser < 1000
    assert underdog_winner > 800
    assert underdog_loser < 1200


def test_elo_streak_bonus_only_starts_at_two():
    _, _, bonus0 = main.calculate_elo_change(1000, 1000, winner_streak=0)
    _, _, bonus1 = main.calculate_elo_change(1000, 1000, winner_streak=1)
    _, _, bonus2 = main.calculate_elo_change(1000, 1000, winner_streak=2)
    assert bonus0 == 0
    assert bonus1 == 0
    assert bonus2 == 4


class FakeResult:
    def __init__(self, modified_count):
        self.modified_count = modified_count


class FakeCollection:
    def __init__(self):
        self.docs = {}

    @staticmethod
    def _matches(doc, query):
        for key, expected in query.items():
            if key == "_id":
                continue
            actual = doc.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
                if "$eq" in expected and actual != expected["$eq"]:
                    return False
            elif actual != expected:
                return False
        return True

    async def find_one(self, query):
        doc = self.docs.get(query.get("_id"))
        if doc is None or not self._matches(doc, query):
            return None
        return dict(doc)

    async def update_one(self, query, update):
        doc = self.docs.get(query.get("_id"))
        if doc is None or not self._matches(doc, query):
            return FakeResult(0)
        for key, value in update.get("$set", {}).items():
            doc[key] = value
        for key in update.get("$unset", {}):
            doc.pop(key, None)
        return FakeResult(1)


class FakeDB:
    def __init__(self):
        self.active_challenges = FakeCollection()


def test_active_challenge_claim_and_release(monkeypatch):
    async def run():
        fake_db = FakeDB()
        monkeypatch.setattr(main.bot, "db", fake_db)
        fake_db.active_challenges.docs["guild_user"] = {
            "_id": "guild_user",
            "status": "active",
            "challenger_id": "user",
            "expires_at": __import__("time").time() + 3600,
        }

        claimed = await main.claim_active_challenge("guild", "user")
        assert claimed["status"] == "processing"
        assert fake_db.active_challenges.docs["guild_user"]["status"] == "processing"

        second_claim = await main.claim_active_challenge("guild", "user")
        assert second_claim is None

        await main.release_active_challenge("guild_user")
        assert fake_db.active_challenges.docs["guild_user"]["status"] == "active"
    asyncio.run(run())


def test_stale_processing_challenge_is_recovered(monkeypatch):
    async def run():
        fake_db = FakeDB()
        monkeypatch.setattr(main.bot, "db", fake_db)
        fake_db.active_challenges.docs["guild_user"] = {
            "_id": "guild_user",
            "status": "processing",
            "processing_at": 0,
            "expires_at": __import__("time").time() + 3600,
        }

        claimed = await main.claim_active_challenge("guild", "user")
        assert claimed["status"] == "processing"
        assert "processing_at" in claimed
        assert fake_db.active_challenges.docs["guild_user"]["status"] == "processing"
    asyncio.run(run())
