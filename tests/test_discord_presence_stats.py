from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "ALU_Gauntlet" / "core" / "core.py"
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"


def test_discord_presence_intent_is_enabled():
    source = CORE.read_text(encoding="utf-8")
    assert "intents.members = True" in source
    assert "intents.presences = True" in source


def test_live_counter_uses_presence_states_and_excludes_bots():
    source = SERVER.read_text(encoding="utf-8")
    assert "guild.presences" in source
    assert '{"online", "idle", "dnd"}' in source
    assert 'getattr(member, "bot", False)' in source
    assert "_discord_community_counts" in source


def test_server_render_and_api_share_live_counter():
    source = SERVER.read_text(encoding="utf-8")
    assert "online, total = self._discord_community_counts(guild)" in source
    assert '"online_members": online' in source
    assert '"server_members": total' in source
