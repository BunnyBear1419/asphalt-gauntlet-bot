import asyncio

from aiohttp.test_utils import TestClient, TestServer
import pytest

from ALU_Gauntlet.web.server import WebControlCenter


class FakeBot:
    guilds = [object(), object()]
    latency = 0.1234

    def is_ready(self):
        return True


@pytest.mark.asyncio
async def test_status_endpoint_reports_bot_state():
    control = WebControlCenter(FakeBot())
    server = TestServer(control.app)
    client = TestClient(server)
    await client.start_server()
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
    server = TestServer(control.app)
    client = TestClient(server)
    await client.start_server()
    try:
        response = await client.get("/")
        assert response.status == 200
        body = await response.text()
        assert "Gauntlet Control Center" in body
        assert "Players" in body
        assert "Simulator" in body
    finally:
        await client.close()
