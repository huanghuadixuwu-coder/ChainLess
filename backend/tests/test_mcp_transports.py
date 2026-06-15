"""W8 MCP transport lifecycle and risk contract."""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from app.core.tools.classifier import RiskLevel, classify_tool, is_pre_authorized
from app.core.tools.mcp.client import MCPToolClient
from app.core.tools.mcp.manager import MCPManager


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    instances: list["FakeAsyncClient"] = []

    def __init__(self, timeout=10.0):
        self.get_count = 0
        self.post_count = 0
        self.closed = False
        FakeAsyncClient.instances.append(self)

    async def get(self, url):
        self.get_count += 1
        return FakeResponse(
            {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
            }
        )

    async def post(self, url, json):
        self.post_count += 1
        return FakeResponse({"content": [f"echo:{json['arguments']['text']}"]})

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_http_and_sse_transports_discover_and_call_tools(monkeypatch) -> None:
    FakeAsyncClient.instances.clear()
    monkeypatch.setattr("app.core.tools.mcp.client.httpx.AsyncClient", FakeAsyncClient)

    for transport in ("http", "sse"):
        client = MCPToolClient("demo", transport=transport, url="http://mcp.local")
        await client.connect()

        tools = client.get_tool_definitions()
        assert tools[0]["function"]["name"] == "mcp__demo__echo"
        assert tools[0]["risk"] == "risky"
        result = await client.call_tool("mcp__demo__echo", {"text": transport})
        assert json.loads(result) == [f"echo:{transport}"]
        await client.disconnect()


@pytest.mark.asyncio
async def test_idle_client_reconnects_before_tool_call(monkeypatch) -> None:
    FakeAsyncClient.instances.clear()
    monkeypatch.setattr("app.core.tools.mcp.client.httpx.AsyncClient", FakeAsyncClient)
    client = MCPToolClient(
        "idle",
        transport="http",
        url="http://mcp.local",
        idle_timeout_s=0.001,
    )
    await client.connect()
    await asyncio.sleep(0.01)
    await client.call_tool("mcp__idle__echo", {"text": "again"})

    assert len(FakeAsyncClient.instances) >= 2
    assert FakeAsyncClient.instances[0].closed is True
    await client.disconnect()


@pytest.mark.asyncio
async def test_manager_reports_unavailable_mcp_tools_with_stable_error() -> None:
    manager = MCPManager()

    with pytest.raises(ValueError, match="No MCP client for tool"):
        await manager.execute("mcp__missing__echo", {})


@pytest.mark.asyncio
async def test_stdio_filesystem_mcp_discovers_invokes_and_disconnects() -> None:
    client = MCPToolClient(
        "fs",
        command=sys.executable,
        args=["scripts/mcp_filesystem_server.py"],
    )
    await client.connect()
    try:
        tools = client.get_tool_definitions()
        names = [tool["function"]["name"] for tool in tools]
        assert "mcp__fs__list_directory" in names
        assert next(
            tool for tool in tools if tool["function"]["name"] == "mcp__fs__list_directory"
        )["risk"] == "risky"

        result = json.loads(
            await client.call_tool("mcp__fs__list_directory", {"path": "scripts"})
        )
        assert "mcp_filesystem_server.py" in result
    finally:
        await client.disconnect()


def test_mcp_filesystem_tool_defaults_to_risky_and_requires_preauthorization() -> None:
    tool_name = "mcp__fs__list_directory"

    assert classify_tool(tool_name) == RiskLevel.RISKY
    assert is_pre_authorized(tool_name, []) is False
    assert is_pre_authorized(tool_name, ["mcp__fs__list_directory"]) is True
