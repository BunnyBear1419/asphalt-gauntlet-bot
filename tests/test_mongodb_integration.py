import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest


MONGO_TEST_URI = os.getenv("MONGO_TEST_URI")

pytestmark = pytest.mark.skipif(not MONGO_TEST_URI, reason="MONGO_TEST_URI is not configured")


def test_mongodb_transactions_and_indexes():
    from pymongo import MongoClient

    client = MongoClient(MONGO_TEST_URI, serverSelectionTimeoutMS=10000)
    client.admin.command("ping")
    db_name = f"alu_ci_{uuid.uuid4().hex[:12]}"
    db = client[db_name]
    try:
        db.system_events.create_index([("guild_id", 1), ("timestamp", -1)])
        db.lap_time_history.create_index([("match_id", 1)], unique=True, sparse=True)

        with client.start_session() as session:
            with session.start_transaction():
                db.system_events.insert_one(
                    {"guild_id": "ci", "timestamp": 1, "event_type": "CI_TEST"},
                    session=session,
                )
                db.lap_time_history.insert_one(
                    {"guild_id": "ci", "match_id": "ci-match", "timestamp": 1},
                    session=session,
                )

        assert db.system_events.count_documents({"event_type": "CI_TEST"}) == 1
        assert db.lap_time_history.count_documents({"match_id": "ci-match"}) == 1
        assert "guild_id_1_timestamp_-1" in db.system_events.index_information()
        assert "match_id_1" in db.lap_time_history.index_information()
    finally:
        client.drop_database(db_name)
        client.close()


def test_club_membership_and_name_races_are_protected_by_unique_indexes():
    from pymongo import MongoClient
    from pymongo.errors import DuplicateKeyError

    client = MongoClient(MONGO_TEST_URI, serverSelectionTimeoutMS=10000, maxPoolSize=20)
    client.admin.command("ping")
    db_name = f"alu_ci_{uuid.uuid4().hex[:12]}"
    db = client[db_name]
    try:
        db.club_members.create_index(
            [("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_club_membership_per_guild",
        )
        db.clubs.create_index(
            [("guild_id", 1), ("name_ci", 1)],
            unique=True,
            name="uniq_club_name_per_guild",
        )

        club_ids = [
            db.clubs.insert_one(
                {"guild_id": "guild", "name": name, "name_ci": name.casefold(), "member_count": 1}
            ).inserted_id
            for name in ("Alpha", "Beta")
        ]

        def join(club_id):
            reservation = db.clubs.update_one(
                {"_id": club_id, "member_count": {"$lt": 20}},
                {"$inc": {"member_count": 1}},
            )
            if reservation.modified_count != 1:
                return "full"
            try:
                db.club_members.insert_one(
                    {"club_id": str(club_id), "guild_id": "guild", "user_id": "racer"}
                )
                return "joined"
            except DuplicateKeyError:
                db.clubs.update_one(
                    {"_id": club_id, "member_count": {"$gt": 0}},
                    {"$inc": {"member_count": -1}},
                )
                return "duplicate"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(join, club_ids))

        assert sorted(results) == ["duplicate", "joined"]
        assert db.club_members.count_documents(
            {"guild_id": "guild", "user_id": "racer"}
        ) == 1

        for club_id in club_ids:
            club = db.clubs.find_one({"_id": club_id})
            member_count = db.club_members.count_documents({"club_id": str(club_id)})
            assert club["member_count"] == member_count + 1

        def create_same_name(_):
            try:
                db.clubs.insert_one(
                    {
                        "guild_id": "guild-2",
                        "name": "Racers",
                        "name_ci": "racers",
                        "member_count": 1,
                    }
                )
                return "created"
            except DuplicateKeyError:
                return "duplicate"

        with ThreadPoolExecutor(max_workers=2) as pool:
            create_results = list(pool.map(create_same_name, range(2)))

        assert sorted(create_results) == ["created", "duplicate"]
        assert db.clubs.count_documents(
            {"guild_id": "guild-2", "name_ci": "racers"}
        ) == 1

    finally:
        client.drop_database(db_name)
        client.close()
