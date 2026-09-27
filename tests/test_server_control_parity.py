from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "ALU_Gauntlet" / "cogs" / "administration.py"
STAFF = ROOT / "ALU_Gauntlet" / "cogs" / "staff.py"
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
WEB = ROOT / "ALU_Gauntlet" / "web" / "static" / "admin.html"


def test_discord_server_control_exists_without_new_public_command():
    admin = ADMIN.read_text(encoding="utf-8")
    staff = STAFF.read_text(encoding="utf-8")
    assert "class ServerControlView" in admin
    assert "class ServerControlModal" in admin
    assert "guild.create_role" in admin
    assert "guild.create_category" in admin
    assert "guild.create_text_channel" in admin
    assert "class ServerControlDashboardButton" in staff
    assert "view.add_item(ServerControlDashboardButton())" in staff
    assert "@app_commands.command(name='servercontrol'" not in staff
    assert '@app_commands.command(name="servercontrol"' not in staff


def test_web_server_control_has_bot_identity_and_discord_resource_routes():
    server = SERVER.read_text(encoding="utf-8")
    for marker in (
        '/api/admin/server-control',
        '/api/admin/server-control/role',
        '/api/admin/server-control/channel',
        '/api/admin/server-control/bot-identity',
        'async def admin_server_control',
        'async def admin_create_role',
        'async def admin_create_channel',
        'async def admin_bot_identity',
    ):
        assert marker in server
    assert 'await self.bot.user.edit(username=username)' in server
    assert 'await self.bot.user.edit(avatar=avatar_bytes)' in server


def test_web_admin_exposes_matching_emergency_controls():
    web = WEB.read_text(encoding="utf-8")
    for marker in (
        'id="section-server-control"',
        'id="save-bot-identity"',
        'id="create-server-role"',
        'id="create-server-channel"',
        'loadServerControl',
        '/api/admin/server-control/bot-identity',
        '/api/admin/server-control/role',
        '/api/admin/server-control/channel',
    ):
        assert marker in web
