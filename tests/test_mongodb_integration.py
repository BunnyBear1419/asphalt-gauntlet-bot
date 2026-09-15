import os
import uuid

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
