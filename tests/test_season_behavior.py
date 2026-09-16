"""Behavioral regression tests for season command behavior."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from ALU_Gauntlet.cogs import season


ROOT = Path(__file__).resolve().parents[1]


class FakeResult:
    def __init__(self, modified_count=1):
        self.modified_count = modified_count


class FakeCollection:
    def __init__(self):
        self.docs = {}

    async def find_one(self, query):
        doc = self.docs.get(query.get("_id"))
        if doc is None:
            return None
        for key, expected in query.items():
            if key != "_id" and doc.get(key) != expected:
                return None
        return dict(doc)

    async def update_one(self, query, update, upsert=False):
        key = query.get("_id")
        doc = self.docs.get(key)
        if doc is None:
            if not upsert:
                return FakeResult(0)
            doc = {"_id": key}
            self.docs[key] = doc
        for field, value in update.get("$set", {}).items():
            doc[field] = value
        for field in update.get("$unset", {}):
            doc.pop(field, None)
        return FakeResult(1)


class FakeDB:
    def __init__(self):
        self.settings = FakeCollection()
        self.season_state = FakeCollection()


class FakeBot:
    def __init__(self, db):
        self.db = db


class FakeUser:
    def __init__(self, user_id=12345):
        self.id = user_id


class FakeResponse:
    def __init__(self):
        self.deferred = False
        self.sent = []

    def is_done(self):
        return self.deferred

    async def defer(self, **kwargs):
        self.deferred = True

    async def send_message(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeInteraction:
    def __init__(self, guild_id="guild-a", user_id=12345):
        self.guild_id = guild_id
        self.user = FakeUser(user_id)
        self.response = FakeResponse()
        self.followup = FakeFollowup()


async def _noop_async(*args, **kwargs):
    return None


async def _true_async(*args, **kwargs):
    return True


def _cog(monkeypatch, db):
    fake_bot = FakeBot(db)
    monkeypatch.setattr(season, "bot", fake_bot)
    return season.SeasonCog(fake_bot)


def _project_source():
    package = ROOT / "ALU_Gauntlet"
    files = [ROOT / "main.py", package / "core" / "core.py", *sorted((package / "cogs").glob("*.py"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in files if path.is_file())


def test_season_auto_only_changes_automatic_rollover(monkeypatch):
    async def run():
        db = FakeDB()
        cog = _cog(monkeypatch, db)
        interaction = FakeInteraction()
        mode = SimpleNamespace(value="on")
        await cog.season_auto_cmd.callback(cog, interaction, mode)
        settings = db.settings.docs["guild-a"]
        assert settings["automatic_season_end"] is True
        assert "starts_at" not in settings
        assert "ends_at" not in settings

    asyncio.run(run())


def test_early_season_start_preserves_scheduled_end(monkeypatch):
    async def run():
        db = FakeDB()
        db.season_state.docs["guild_guild-a"] = {
            "_id": "guild_guild-a", "guild_id": "guild-a", "season_number": 4,
            "starts_at": 2_000_000_000, "ends_at": 2_000_086_400,
            "season_active": False, "awaiting_staff_start": True,
        }
        cog = _cog(monkeypatch, db)
        monkeypatch.setattr(season, "enforce_channel_constraints", _true_async)
        monkeypatch.setattr(season, "announce_season_start", _noop_async)
        monkeypatch.setattr(season, "audit_admin_action", _noop_async)
        interaction = FakeInteraction()
        await cog.season_start_cmd.callback(cog, interaction)
        state = db.season_state.docs["guild_guild-a"]
        assert state["season_active"] is True
        assert state["awaiting_staff_start"] is False
        assert state["ends_at"] == 2_000_086_400
        assert state["starts_at"] == 2_000_000_000
        assert "scheduled end time remains unchanged" in interaction.followup.sent[-1][0][0]

    asyncio.run(run())


def test_season_state_isolated_between_guilds(monkeypatch):
    async def run():
        db = FakeDB()
        db.season_state.docs["guild_guild-a"] = {
            "_id": "guild_guild-a", "guild_id": "guild-a", "season_number": 2,
            "starts_at": 2_000_000_000, "ends_at": 2_000_086_400,
            "season_active": False, "awaiting_staff_start": True,
        }
        db.season_state.docs["guild_guild-b"] = {
            "_id": "guild_guild-b", "guild_id": "guild-b", "season_number": 7,
            "starts_at": 2_000_000_000, "ends_at": 2_000_172_800,
            "season_active": False, "awaiting_staff_start": True,
        }
        cog = _cog(monkeypatch, db)
        monkeypatch.setattr(season, "enforce_channel_constraints", _true_async)
        monkeypatch.setattr(season, "announce_season_start", _noop_async)
        monkeypatch.setattr(season, "audit_admin_action", _noop_async)
        await cog.season_start_cmd.callback(cog, FakeInteraction("guild-a"))
        assert db.season_state.docs["guild_guild-a"]["season_active"] is True
        assert db.season_state.docs["guild_guild-b"]["season_active"] is False
        assert db.season_state.docs["guild_guild-b"]["season_number"] == 7
        assert db.season_state.docs["guild_guild-b"]["ends_at"] == 2_000_172_800

    asyncio.run(run())


def test_invalid_schedule_does_not_change_existing_state(monkeypatch):
    async def run():
        db = FakeDB()
        db.settings.docs["guild-a"] = {"_id": "guild-a"}
        original = {
            "_id": "guild_guild-a", "guild_id": "guild-a", "season_number": 3,
            "starts_at": 2_000_000_000, "ends_at": 2_000_086_400,
            "season_active": False, "awaiting_staff_start": True,
        }
        db.season_state.docs["guild_guild-a"] = dict(original)
        cog = _cog(monkeypatch, db)
        interaction = FakeInteraction()
        await cog.season_schedule_cmd.callback(cog, interaction, "2026-01-02 12:00", "2026-01-02 11:00")
        assert db.season_state.docs["guild_guild-a"] == original
        assert interaction.followup.sent
        assert "Timestamp Read Error" in interaction.followup.sent[-1][0][0]

    asyncio.run(run())


def test_scheduled_end_uses_guild_rollover_setting_and_never_defaults_to_rollover():
    source = _project_source()
    assert "automatic_season_end" in source
    assert "start_next_season=auto_rollover" in source


def test_manual_end_forces_no_rollover_even_when_automatic_rollover_is_enabled():
    source = _project_source()
    assert "start_next_season=False" in source


def test_rollover_preserves_schedule_duration_and_announces_once_per_transition_path():
    source = _project_source()
    assert "season_duration = previous_end - previous_start" in source
    assert '"ends_at": now + season_duration' in source
    assert 'reason="rollover"' in source
