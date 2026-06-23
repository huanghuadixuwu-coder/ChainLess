"""W8 MCP transport lifecycle and risk contract."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.tools.classifier import RiskLevel, classify_tool, is_pre_authorized
from app.core.tools.mcp.client import (
    MCPToolClient,
    RemoteMCPTransportAdapter,
    RemoteMCPTransportEvidence,
    RemoteMCPTransportResult,
)
from app.core.tools.mcp.manager import MCPManager


class TrustedRemoteAdapter(RemoteMCPTransportAdapter):
    def __init__(
        self,
        *,
        trusted_peer_ips: tuple[str, ...] = ("93.184.216.34",),
        streaming_response_cap_enforced: bool = True,
        raise_before_payload: Exception | None = None,
    ) -> None:
        self.trusted_peer_ips = trusted_peer_ips
        self.streaming_response_cap_enforced = streaming_response_cap_enforced
        self.raise_before_payload = raise_before_payload
        self.discover_count = 0
        self.call_count = 0
        self.close_count = 0

    def _evidence(self) -> RemoteMCPTransportEvidence:
        return RemoteMCPTransportEvidence(
            trusted_peer_ips=self.trusted_peer_ips,
            resolved_ips=self.trusted_peer_ips,
            streaming_response_cap_enforced=self.streaming_response_cap_enforced,
        )

    async def discover_tools(self, *, base_url, transport, policy, network_scope):
        self.discover_count += 1
        if self.raise_before_payload is not None:
            raise self.raise_before_payload
        return RemoteMCPTransportResult(
            payload={
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
            },
            evidence=self._evidence(),
        )

    async def call_tool(self, *, base_url, transport, tool_name, arguments, policy, network_scope):
        self.call_count += 1
        return RemoteMCPTransportResult(
            payload={"content": [f"echo:{arguments['text']}"]},
            evidence=self._evidence(),
        )

    async def aclose(self):
        self.close_count += 1


def approved_stdio_config(**overrides):
    config = {
        "transport": "stdio",
        "runtime_kind": "isolated_stdio",
        "command": "python",
        "args": ["/runtime/echo_mcp_server.py"],
        "env_secret_refs": [],
        "egress_policy": {},
        "stdio_runtime_image_ref": "chainless-mcp-runtime:w4-1-quality",
        "stdio_command_provenance": {
            "source": "activation_target",
            "approved_by": "admin",
            "approved_at": "2026-06-22T00:00:00Z",
        },
        "stdio_package_digest": "sha256:" + "a" * 64,
        "stdio_filesystem_policy": {
            "allow_docker_socket": False,
            "allow_backend_fs": False,
            "allow_host_fs": False,
            "mounts": [],
        },
        "stdio_network_policy": {
            "mode": "none",
            "allowed_hosts": [],
            "deny_private_networks": True,
        },
        "stdio_resource_limits": {
            "memory_mb": 256,
            "cpus": 0.5,
            "pids": 64,
            "timeout_seconds": 30,
        },
        "stdio_max_session_seconds": 30,
        "stdio_max_output_bytes": 65536,
        "stdio_restart_policy": {"max_restarts": 1},
    }
    config.update(overrides)
    return config


@pytest.mark.asyncio
async def test_http_and_sse_transports_require_trusted_streaming_adapter() -> None:
    for transport in ("http", "sse"):
        adapter = TrustedRemoteAdapter()
        client = MCPToolClient(
            "demo",
            transport=transport,
            url="http://mcp.local",
            egress_policy={"allow_hosts": ["mcp.local"], "max_response_bytes": 10000},
            remote_transport_adapter=adapter,
        )
        await client.connect()

        tools = client.get_tool_definitions()
        assert tools[0]["function"]["name"] == "mcp__demo__echo"
        assert tools[0]["risk"] == "risky"
        result = await client.call_tool("mcp__demo__echo", {"text": transport})
        assert json.loads(result) == [f"echo:{transport}"]
        assert adapter.discover_count == 1
        assert adapter.call_count == 1
        await client.disconnect()


@pytest.mark.asyncio
async def test_remote_mcp_transport_still_works_with_trusted_adapter_evidence() -> None:
    adapter = TrustedRemoteAdapter()
    client = MCPToolClient(
        "remote",
        transport="http",
        url="http://mcp.local",
        egress_policy={"allow_hosts": ["mcp.local"], "max_response_bytes": 10000},
        remote_transport_adapter=adapter,
    )
    await client.connect()
    try:
        assert client.get_tool_definitions()[0]["function"]["name"] == "mcp__remote__echo"
        assert json.loads(await client.call_tool("mcp__remote__echo", {"text": "ok"})) == ["echo:ok"]
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_remote_mcp_egress_policy_denies_unsafe_direct_transport_and_bad_evidence() -> None:
    with pytest.raises(ValueError, match="REMOTE_EGRESS_POLICY_REQUIRED"):
        await MCPToolClient(
            "missing-policy",
            transport="http",
            url="http://mcp.local",
        ).connect()

    with pytest.raises(ValueError, match="SAFE_REMOTE_TRANSPORT_REQUIRED"):
        await MCPToolClient(
            "direct-unsupported",
            transport="http",
            url="http://mcp.local",
            egress_policy={"allow_hosts": ["mcp.local"], "max_response_bytes": 10000},
        ).connect()

    with pytest.raises(ValueError, match="CONNECTED_PEER_EVIDENCE_REQUIRED"):
        await MCPToolClient(
            "missing-peer-evidence",
            transport="http",
            url="http://mcp.local",
            egress_policy={"allow_hosts": ["mcp.local"], "max_response_bytes": 10000},
            remote_transport_adapter=TrustedRemoteAdapter(trusted_peer_ips=()),
        ).connect()

    with pytest.raises(ValueError, match="STREAMING_RESPONSE_CAP_REQUIRED"):
        await MCPToolClient(
            "missing-stream-cap",
            transport="http",
            url="http://mcp.local",
            egress_policy={"allow_hosts": ["mcp.local"], "max_response_bytes": 10000},
            remote_transport_adapter=TrustedRemoteAdapter(streaming_response_cap_enforced=False),
        ).connect()

    with pytest.raises(ValueError, match="HOST_NOT_ALLOWLISTED"):
        await MCPToolClient(
            "blocked-host",
            transport="http",
            url="http://blocked.local",
            egress_policy={"allow_hosts": ["mcp.local"], "max_response_bytes": 10000},
            remote_transport_adapter=TrustedRemoteAdapter(),
        ).connect()

    with pytest.raises(ValueError, match="RESPONSE_SIZE_CAP_REQUIRED"):
        await MCPToolClient(
            "missing-cap",
            transport="http",
            url="http://mcp.local",
            egress_policy={"allow_hosts": ["mcp.local"]},
            remote_transport_adapter=TrustedRemoteAdapter(),
        ).connect()

    with pytest.raises(ValueError, match="PRIVATE_NETWORK_DENIED"):
        await MCPToolClient(
            "private",
            transport="http",
            url="http://mcp.local",
            egress_policy={"allow_hosts": ["mcp.local"], "max_response_bytes": 10000},
            remote_transport_adapter=TrustedRemoteAdapter(trusted_peer_ips=("127.0.0.1",)),
        ).connect()

    with pytest.raises(ValueError, match="ARBITRARY_NETWORK_FORBIDDEN"):
        await MCPToolClient(
            "arbitrary",
            transport="http",
            url="http://mcp.local",
            egress_policy={"allow_hosts": ["mcp.local"], "max_response_bytes": 10000},
            egress_network_scope="arbitrary_network",
            remote_transport_adapter=TrustedRemoteAdapter(),
        ).connect()


@pytest.mark.asyncio
async def test_remote_mcp_response_size_cap_must_be_stream_enforced_by_adapter() -> None:
    adapter = TrustedRemoteAdapter(raise_before_payload=ValueError("MCP remote egress denied: RESPONSE_TOO_LARGE"))
    with pytest.raises(ValueError, match="RESPONSE_TOO_LARGE"):
        await MCPToolClient(
            "oversized",
            transport="http",
            url="http://mcp.local",
            egress_policy={"allow_hosts": ["mcp.local"], "max_response_bytes": 10},
            remote_transport_adapter=adapter,
        ).connect()
    assert adapter.discover_count == 1


@pytest.mark.asyncio
async def test_idle_client_reconnects_before_tool_call() -> None:
    adapter = TrustedRemoteAdapter()
    client = MCPToolClient(
        "idle",
        transport="http",
        url="http://mcp.local",
        idle_timeout_s=0.001,
        egress_policy={"allow_hosts": ["mcp.local"], "max_response_bytes": 10000},
        remote_transport_adapter=adapter,
    )
    await client.connect()
    await asyncio.sleep(0.01)
    await client.call_tool("mcp__idle__echo", {"text": "again"})

    assert adapter.discover_count == 2
    assert adapter.close_count >= 1
    await client.disconnect()


@pytest.mark.asyncio
async def test_manager_reports_unavailable_mcp_tools_with_stable_error() -> None:
    manager = MCPManager()

    with pytest.raises(ValueError, match="No MCP client for tool"):
        await manager.execute("mcp__missing__echo", {})


@pytest.mark.asyncio
async def test_stdio_mcp_uses_isolated_runtime_contract() -> None:
    client = MCPToolClient("fs", **approved_stdio_config())
    await client.connect()
    try:
        tools = client.get_tool_definitions()
        names = [tool["function"]["name"] for tool in tools]
        assert "mcp__fs__echo" in names
        assert next(
            tool for tool in tools if tool["function"]["name"] == "mcp__fs__echo"
        )["risk"] == "risky"

        result = json.loads(
            await client.call_tool("mcp__fs__echo", {"text": "hello"})
        )
        assert result == ["hello"]
    finally:
        await client.disconnect()


def test_mcp_filesystem_tool_defaults_to_risky_and_requires_preauthorization() -> None:
    tool_name = "mcp__fs__list_directory"

    assert classify_tool(tool_name) == RiskLevel.RISKY
    assert is_pre_authorized(tool_name, []) is False
    assert is_pre_authorized(tool_name, ["mcp__fs__list_directory"]) is True


@pytest.mark.asyncio
async def test_stdio_mcp_does_not_retain_task_bound_context_between_calls() -> None:
    client = MCPToolClient("echo", **approved_stdio_config())

    await client.connect()
    try:
        assert client.get_tool_definitions()[0]["function"]["name"] == "mcp__echo__echo"
        assert client._runtime_client is not None

        first = json.loads(await client.call_tool("mcp__echo__echo", {"text": "first"}))
        second = json.loads(await client.call_tool("mcp__echo__echo", {"text": "second"}))

        assert first == ["first"]
        assert second == ["second"]
    finally:
        await client.disconnect()
