from pathlib import Path
from web_source import web_source


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "ALU_Gauntlet" / "core" / "core.py"
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"


def test_discord_presence_intent_is_enabled():
    source = CORE.read_text(encoding="utf-8")
    assert "intents.members = True" in source
    assert "intents.presences = True" in source


def test_live_counter_uses_presence_states_and_excludes_bots():
    source = web_source()
    assert 'getattr(guild, "presences", None)' in source
    assert '{"online", "idle", "dnd"}' in source
    assert 'getattr(member, "bot", False)' in source
    assert "_discord_community_counts" in source


def test_server_render_and_api_share_live_counter():
    source = web_source()
    assert "online, total = self._discord_community_counts(guild)" in source
    assert '"online_members": online' in source
    assert '"server_members": total' in source


def test_homepage_discord_counter_ids_match_server_first_paint_renderer():
    server = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    home = (ROOT / "ALU_Gauntlet" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="discord-online-members"' in home
    assert 'id="discord-server-members"' in home
    assert '("discord-online-members", online)' in server
    assert '("discord-server-members", total)' in server


def test_web_guild_selection_uses_live_membership_not_only_oauth_snapshot():
    server = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    assert "async def _live_member_for_user" in server
    assert "async def _connected_guilds_for_user" in server
    connected_start = server.index("async def _connected_guilds_for_user")
    connected_end = server.index("async def require_guild_member", connected_start)
    connected = server[connected_start:connected_end]
    assert "await self._live_member_for_user" in connected
    guilds_start = server.index("async def guilds", 0)
    guilds_end = server.index("async def player_me", guilds_start)
    guilds = server[guilds_start:guilds_end]
    assert "await self._connected_guilds_for_user(user)" in guilds
    admin_start = server.index("async def _admin_guilds_data")
    admin_end = server.index("async def admin_page", admin_start)
    admin = server[admin_start:admin_end]
    assert "await self._connected_guilds_for_user(user)" in admin
