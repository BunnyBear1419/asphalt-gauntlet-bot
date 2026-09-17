import asyncio

from aiohttp.test_utils import TestClient, TestServer
import pytest

from ALU_Gauntlet.web.auth import SESSION_COOKIE, WebUser
from ALU_Gauntlet.web.server import WebControlCenter


class FakeBot:
    guilds = [object(), object()]
    latency = 0.1234

    def is_ready(self):
        return True


async def staff_client(control):
    server = TestServer(control.app)
    client = TestClient(server)
    await client.start_server()
    user = WebUser(
        user_id="123",
        username="test-staff",
        global_name="Test Staff",
        avatar=None,
        staff=True,
        admin_guild_ids=set(),
    )
    token = await control.auth.create_session(user)
    client.session.cookie_jar.update_cookies({SESSION_COOKIE: token})
    return client


@pytest.mark.asyncio
async def test_status_endpoint_reports_bot_state():
    control = WebControlCenter(FakeBot())
    client = await staff_client(control)
    try:
        response = await client.get("/api/status")
        assert response.status == 200
        payload = await response.json()
        assert payload["bot"]["online"] is True
        assert payload["bot"]["guild_count"] == 2
        assert payload["control_center"]["phase"] == 1
        assert payload["control_center"]["mutations_enabled"] is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_dashboard_is_served():
    control = WebControlCenter(FakeBot())
    client = await staff_client(control)
    try:
        response = await client.get("/")
        assert response.status == 200
        body = await response.text()
        assert "Gauntlet Control Center" in body
        assert "Players" in body
        assert "Simulator" in body
    finally:
        await client.close()
