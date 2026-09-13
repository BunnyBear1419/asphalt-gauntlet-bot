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


def test_lap_time_rejects_invalid_values():
    invalid = ["", "0:00.000", "1:2.345", "01:02.34", "1:60.000", "abc", "1:02.0000"]
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
            "guild_id": "guild",
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
            "guild_id": "guild",
            "status": "processing",
            "challenger_id": "user",
            "processing_at": 0,
            "expires_at": __import__("time").time() + 3600,
        }

        claimed = await main.claim_active_challenge("guild", "user")
        assert claimed["status"] == "processing"
        assert "processing_at" in claimed
        assert fake_db.active_challenges.docs["guild_user"]["status"] == "processing"
    asyncio.run(run())


def test_season_schedule_automatically_starts_and_ends():
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "starts_at" in source and "ends_at" in source
    assert 'if (not bool(state.get("season_active", False)) and starts_at' in source
    assert 'now >= starts_at and now < ends_at' in source
    assert 'await announce_season_start(guild_id, season_number, reason="scheduled")' in source
    assert 'if bool(state.get("season_active", False)) and ends_at and now >= ends_at' in source


def test_seasonauto_controls_only_scheduled_end_rollover():
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert '@bot.tree.command(name="seasonauto"' in source
    assert 'app_commands.Choice(name="Enable automatic season rollover", value="on")' in source
    assert 'app_commands.Choice(name="Disable automatic season rollover", value="off")' in source
    assert 'await trigger_global_season_end(guild_id=guild_id, start_next_season=auto_rollover)' in source
    assert '"automatic_season_end": False' in source


def test_seasonstart_early_preserves_scheduled_end():
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert '@bot.tree.command(name="seasonstart"' in source
    assert '"scheduled end time remains unchanged"' in source
    assert '"season_active": True' in source


def test_manual_seasonend_never_auto_rolls_next_season():
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert 'trigger_global_season_end(guild_id=self.guild_id,forced_interaction=interaction, start_next_season=False)' in source
    assert 'the next season will not roll over automatically' in source


def test_automatic_rollover_announces_new_season_and_preserves_schedule_duration():
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert 'season_duration = previous_end - previous_start' in source
    assert 'await announce_season_start(guild_id, next_season, reason="rollover")' in source
    assert '"ends_at": now + season_duration' in source
