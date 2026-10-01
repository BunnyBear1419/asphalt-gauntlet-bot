import asyncio
from datetime import datetime, timezone

from ALU_Gauntlet.web.auth import DiscordOAuth, WebUser, SESSION_COOKIE


class FakeCollection:
    def __init__(self):
        self.records = {}

    async def update_one(self, query, update, upsert=False):
        self.records[query["_id"]] = update["$set"]

    async def find_one(self, query):
        return self.records.get(query["_id"])

    async def delete_one(self, query):
        self.records.pop(query["_id"], None)


class FakeDatabase:
    def __init__(self):
        self.web_sessions = FakeCollection()


class FakeBot:
    def __init__(self):
        self.db = FakeDatabase()


class FakeRequest:
    def __init__(self, token):
        self.cookies = {SESSION_COOKIE: token}


def test_create_session_cache_round_trips_through_get_session():
    async def scenario():
        bot = FakeBot()
        auth = DiscordOAuth(bot)
        user = WebUser(
            user_id="123",
            username="driver",
            global_name="Driver",
            avatar=None,
            staff=False,
            admin_guild_ids=frozenset(),
            guild_ids=frozenset({"456"}),
        )

        token = await auth.create_session(user)
        cached_expiry, cached_user = auth.sessions[token]

        assert isinstance(cached_expiry, float)
        assert cached_expiry > datetime.now(timezone.utc).timestamp()
        assert cached_user == user

        restored = await auth.get_session(FakeRequest(token))
        assert restored == user

        record = await bot.db.web_sessions.find_one({"_id": auth._session_key(token)})
        assert isinstance(record["expires_at"], datetime)
        assert record["expires_at"].tzinfo is not None

    asyncio.run(scenario())


def test_session_store_failure_falls_back_to_memory_cache(caplog):
    async def scenario():
        class BrokenCollection(FakeCollection):
            async def update_one(self, *args, **kwargs):
                raise RuntimeError("temporary Mongo outage")

        bot = FakeBot()
        bot.db.web_sessions = BrokenCollection()
        auth = DiscordOAuth(bot)
        user = WebUser(
            user_id="123",
            username="driver",
            global_name=None,
            avatar=None,
            staff=False,
            admin_guild_ids=frozenset(),
            guild_ids=frozenset(),
        )

        token = await auth.create_session(user)
        assert await auth.get_session(FakeRequest(token)) == user

    with caplog.at_level("WARNING"):
        asyncio.run(scenario())

    assert "Unable to persist web session" in caplog.text
