"""MCP tool client wrapping approved MCP transports.

Discovers available tools on connect and provides a ``call_tool`` method
for invoking them by name.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from app.core.security.egress_policy import (
    EgressDecision,
    EgressPolicy,
    prepare_egress_runtime_guard,
    validate_runtime_egress,
)
from app.core.tools.mcp_runtime import (
    IsolatedMCPRuntimeClient,
    IsolatedMCPRuntimeSupervisor,
    StdioRuntimePolicy,
    validate_stdio_runtime_policy,
)


@dataclass(frozen=True)
class RemoteMCPTransportEvidence:
    """Evidence emitted by a remote MCP transport owner after a safe request."""

    trusted_peer_ips: tuple[str, ...] = ()
    resolved_ips: tuple[str, ...] = ()
    streaming_response_cap_enforced: bool = False


@dataclass(frozen=True)
class RemoteMCPTransportResult:
    """Parsed payload plus runtime evidence from a trusted remote adapter."""

    payload: Any
    evidence: RemoteMCPTransportEvidence


class RemoteMCPTransportAdapter:
    """Trusted remote MCP transport seam.

    The default backend does not own a safe HTTP/SSE connector that can bind
    DNS evidence to the actual connected peer and stream-limit the body before
    parsing. Production therefore fails closed unless a dedicated owner injects
    an adapter with that evidence.
    """

    async def discover_tools(
        self,
        *,
        base_url: str,
        transport: str,
        policy: EgressPolicy,
        network_scope: str,
    ) -> RemoteMCPTransportResult:
        raise ValueError("MCP remote transport denied: SAFE_REMOTE_TRANSPORT_REQUIRED")

    async def call_tool(
        self,
        *,
        base_url: str,
        transport: str,
        tool_name: str,
        arguments: dict[str, Any],
        policy: EgressPolicy,
        network_scope: str,
    ) -> RemoteMCPTransportResult:
        raise ValueError("MCP remote transport denied: SAFE_REMOTE_TRANSPORT_REQUIRED")

    async def aclose(self) -> None:
        return None


class MCPToolClient:
    """A client for a single MCP server.

    Attributes:
        name: Human-readable label for this server (used in tool name
            prefixing, e.g. ``mcp__{name}__{tool_name}``).
        command: MCP stdio command metadata handed to the isolated runtime.
        args: Extra CLI arguments for *command*.
        env: Legacy remote-only env metadata. Stdio uses env_secret_refs.
    """

    def __init__(
        self,
        name: str,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        *,
        transport: str = "stdio",
        url: str | None = None,
        idle_timeout_s: float | None = None,
        runtime_kind: str | None = None,
        env_secret_refs: list[dict[str, Any]] | None = None,
        egress_policy: dict[str, Any] | None = None,
        stdio_runtime_image_ref: str | None = None,
        stdio_runtime_url: str | None = None,
        stdio_command_provenance: dict[str, Any] | None = None,
        stdio_package_digest: str | None = None,
        stdio_filesystem_policy: dict[str, Any] | None = None,
        stdio_network_policy: dict[str, Any] | None = None,
        stdio_resource_limits: dict[str, Any] | None = None,
        stdio_max_session_seconds: int | None = None,
        stdio_max_output_bytes: int | None = None,
        stdio_restart_policy: dict[str, Any] | None = None,
        tool_definitions: list[dict[str, Any]] | None = None,
        egress_network_scope: str = "allowlisted_domains",
        runtime_supervisor: IsolatedMCPRuntimeSupervisor | None = None,
        remote_transport_adapter: RemoteMCPTransportAdapter | None = None,
    ) -> None:
        self.name = name
        self.command = command or ""
        self.args = args or []
        self.env = env or {}
        self.transport = transport
        self.url = url
        self.idle_timeout_s = idle_timeout_s
        self.runtime_kind = runtime_kind
        self.env_secret_refs = env_secret_refs or []
        self.egress_policy = egress_policy or {}
        self.stdio_runtime_image_ref = stdio_runtime_image_ref
        self.stdio_runtime_url = stdio_runtime_url
        self.stdio_command_provenance = stdio_command_provenance or {}
        self.stdio_package_digest = stdio_package_digest
        self.stdio_filesystem_policy = stdio_filesystem_policy or {}
        self.stdio_network_policy = stdio_network_policy or {}
        self.stdio_resource_limits = stdio_resource_limits or {}
        self.stdio_max_session_seconds = stdio_max_session_seconds
        self.stdio_max_output_bytes = stdio_max_output_bytes
        self.stdio_restart_policy = stdio_restart_policy or {}
        self._configured_tool_definitions = tool_definitions or []
        self.egress_network_scope = egress_network_scope
        self._runtime_supervisor = runtime_supervisor
        self._remote_transport_adapter = remote_transport_adapter or RemoteMCPTransportAdapter()

        self._tools: list[dict[str, Any]] = []
        self._connected = False
        self._runtime_client: IsolatedMCPRuntimeClient | None = None
        self._runtime_policy: StdioRuntimePolicy | None = None
        self._last_used_monotonic = time.monotonic()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to the MCP transport and discover its tools.

        Raises:
            Exception: Any error from transport startup, handshake, or tool
                listing is propagated to the caller.
        """
        if self.transport in {"http", "sse"}:
            await self._connect_http()
            return
        if self.transport != "stdio":
            raise ValueError(f"Unsupported MCP transport: {self.transport}")
        await self._connect_isolated_stdio()
        self._connected = True
        self._last_used_monotonic = time.monotonic()

    async def _connect_isolated_stdio(self) -> None:
        config = {
            "transport": self.transport,
            "runtime_kind": self.runtime_kind,
            "command": self.command,
            "args": self.args,
            "env_secret_refs": self.env_secret_refs,
            "egress_policy": self.egress_policy,
            "stdio_runtime_image_ref": self.stdio_runtime_image_ref,
            "stdio_runtime_url": self.stdio_runtime_url,
            "stdio_command_provenance": self.stdio_command_provenance,
            "stdio_package_digest": self.stdio_package_digest,
            "stdio_filesystem_policy": self.stdio_filesystem_policy,
            "stdio_network_policy": self.stdio_network_policy,
            "stdio_resource_limits": self.stdio_resource_limits,
            "stdio_max_session_seconds": self.stdio_max_session_seconds,
            "stdio_max_output_bytes": self.stdio_max_output_bytes,
            "stdio_restart_policy": self.stdio_restart_policy,
            "tool_definitions": self._configured_tool_definitions,
        }
        self._runtime_policy = validate_stdio_runtime_policy(self.name, config)
        self._runtime_client = IsolatedMCPRuntimeClient(
            self._runtime_policy,
            self._runtime_supervisor,
        )
        await self._runtime_client.connect()
        self._tools = [
            self._normalize_runtime_tool(tool)
            for tool in self._runtime_client.get_tool_definitions()
        ]

    async def _connect_http(self) -> None:
        if not self.url:
            raise ValueError(f"MCP {self.transport} transport requires url")
        policy = self._remote_egress_policy()
        result = await self._remote_transport_adapter.discover_tools(
            base_url=self.url.rstrip("/"),
            transport=self.transport,
            policy=policy,
            network_scope=self.egress_network_scope,
        )
        self._validate_remote_transport_evidence(
            f"{self.url.rstrip('/')}/tools",
            policy,
            result.evidence,
        )
        payload = result.payload
        raw_tools = payload.get("tools") if isinstance(payload, dict) else payload
        if not isinstance(raw_tools, list):
            raise ValueError("MCP HTTP tools response must include a tools list")
        self._tools = [self._normalize_remote_tool(tool) for tool in raw_tools]
        self._connected = True
        self._last_used_monotonic = time.monotonic()

    def _normalize_remote_tool(self, tool: dict[str, Any]) -> dict[str, Any]:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict) and function.get("name"):
            local_name = str(function["name"])
            if local_name.startswith(f"mcp__{self.name}__"):
                local_name = local_name.removeprefix(f"mcp__{self.name}__")
            return self._openai_tool_definition(
                local_name,
                function.get("description") or f"MCP tool from {self.name}: {local_name}",
                function.get("parameters") or {"type": "object", "properties": {}},
            )
        if not isinstance(tool, dict) or not tool.get("name"):
            raise ValueError("MCP tool definition requires a name")
        return self._openai_tool_definition(
            str(tool["name"]),
            str(tool.get("description") or f"MCP tool from {self.name}: {tool['name']}"),
            tool.get("inputSchema")
            or tool.get("parameters")
            or {"type": "object", "properties": {}},
        )

    def _normalize_runtime_tool(self, tool: dict[str, Any]) -> dict[str, Any]:
        return self._normalize_remote_tool(tool)

    def _openai_tool_definition(
        self,
        local_name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "risk": "risky",
            "function": {
                "name": f"mcp__{self.name}__{local_name}",
                "description": description,
                "parameters": parameters,
            },
        }

    async def disconnect(self) -> None:
        """Shut down transport state and request isolated runtime cleanup."""
        if self._runtime_client:
            try:
                await self._runtime_client.disconnect("success")
            except Exception:
                pass
            self._runtime_client = None
        try:
            await self._remote_transport_adapter.aclose()
        except Exception:
            pass
        self._connected = False

    def is_idle_expired(self) -> bool:
        if not self.idle_timeout_s:
            return False
        return time.monotonic() - self._last_used_monotonic >= self.idle_timeout_s

    async def ensure_connected(self) -> None:
        if self._connected and not self.is_idle_expired():
            return
        await self.disconnect()
        await self.connect()

    # ------------------------------------------------------------------
    # Tool operations
    # ------------------------------------------------------------------

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        """Call an MCP tool.

        Args:
            tool_name: Fully qualified tool name
                (``mcp__{server_name}__{local_tool_name}``).
            args: Arguments to pass to the tool.

        Returns:
            JSON string of the tool's content list.
        """
        await self.ensure_connected()
        local_name = tool_name.replace(f"mcp__{self.name}__", "", 1)
        if self.transport in {"http", "sse"}:
            policy = self._remote_egress_policy()
            result = await self._remote_transport_adapter.call_tool(
                base_url=self.url.rstrip("/") if self.url else "",
                transport=self.transport,
                tool_name=local_name,
                arguments=args,
                policy=policy,
                network_scope=self.egress_network_scope,
            )
            self._validate_remote_transport_evidence(
                f"{self.url.rstrip('/')}/call" if self.url else "",
                policy,
                result.evidence,
            )
            payload = result.payload
            self._last_used_monotonic = time.monotonic()
            if isinstance(payload, dict) and "content" in payload:
                return json.dumps(payload["content"], ensure_ascii=False)
            return json.dumps(payload, ensure_ascii=False)

        if self._runtime_client is None:
            raise ValueError("MCP stdio runtime is not connected")
        result = await self._runtime_client.call_tool(local_name, args)
        self._last_used_monotonic = time.monotonic()
        return result

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return the OpenAI-style function definitions for all discovered tools."""
        return self._tools

    def _validate_remote_transport_evidence(
        self,
        url: str,
        policy: EgressPolicy,
        evidence: RemoteMCPTransportEvidence,
    ) -> None:
        if not evidence.streaming_response_cap_enforced:
            raise ValueError("MCP remote egress denied: STREAMING_RESPONSE_CAP_REQUIRED")
        if not evidence.trusted_peer_ips:
            raise ValueError("MCP remote egress denied: CONNECTED_PEER_EVIDENCE_REQUIRED")
        resolved_ips = evidence.resolved_ips or evidence.trusted_peer_ips
        guard = prepare_egress_runtime_guard(
            policy,
            url,
            network_scope=self.egress_network_scope,
            target_type="mcp_tool",
            activated_target=True,
            resolved_ips=resolved_ips,
            resolver=None,
        )
        if isinstance(guard, EgressDecision) and not guard.allowed:
            raise ValueError(f"MCP remote egress denied: {guard.code}")
        connected = validate_runtime_egress(
            guard,
            connected_ips=evidence.trusted_peer_ips,
        )
        if not connected.allowed:
            raise ValueError(f"MCP remote egress denied: {connected.code}")

    def _remote_egress_policy(self) -> EgressPolicy:
        configured_hosts = self.egress_policy.get("allow_hosts") or self.egress_policy.get("allowed_hosts")
        if not configured_hosts:
            raise ValueError("MCP remote egress denied: REMOTE_EGRESS_POLICY_REQUIRED")
        if self.egress_policy.get("max_response_bytes") is None:
            raise ValueError("MCP remote egress denied: RESPONSE_SIZE_CAP_REQUIRED")
        return EgressPolicy(
            allow_hosts=tuple(configured_hosts),
            redirect_policy=self.egress_policy.get("redirect_policy", {"follow": False}),
            deny_private_networks=self.egress_policy.get("deny_private_networks", True),
            max_response_bytes=self.egress_policy.get("max_response_bytes"),
        )

    async def recover_after_backend_restart(self) -> None:
        """Restart-safe recovery hook for isolated stdio runtime sessions."""
        if self.transport != "stdio":
            return
        if self._runtime_client is None:
            await self.connect()
            return
        await self._runtime_client.recover_after_backend_restart()
        self._tools = [
            self._normalize_runtime_tool(tool)
            for tool in self._runtime_client.get_tool_definitions()
        ]
        self._connected = True

    async def rollback(self) -> None:
        """Rollback hook that cleans up an isolated stdio runtime session."""
        if self._runtime_client is not None:
            await self._runtime_client.rollback()
            self._runtime_client = None
        self._connected = False
