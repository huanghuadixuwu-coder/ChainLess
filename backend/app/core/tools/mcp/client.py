"""MCP tool client wrapping the ``mcp`` Python SDK.

Discovers available tools on connect and provides a ``call_tool`` method
for invoking them by name.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPToolClient:
    """A client for a single MCP server communicated over stdio transport.

    Attributes:
        name: Human-readable label for this server (used in tool name
            prefixing, e.g. ``mcp__{name}__{tool_name}``).
        command: Shell command that launches the MCP server process.
        args: Extra CLI arguments for *command*.
        env: Extra environment variables for the subprocess.
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
    ) -> None:
        self.name = name
        self.command = command or ""
        self.args = args or []
        self.env = env or {}
        self.transport = transport
        self.url = url
        self.idle_timeout_s = idle_timeout_s

        self._session: ClientSession | None = None
        self._tools: list[dict[str, Any]] = []
        self._connected = False
        self._stdio_ctx: Any = None
        self._http_client: httpx.AsyncClient | None = None
        self._last_used_monotonic = time.monotonic()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the MCP server subprocess and discover its tools.

        Raises:
            Exception: Any error from subprocess startup, handshake, or
                tool listing is propagated to the caller.
        """
        if self.transport in {"http", "sse"}:
            await self._connect_http()
            return
        if self.transport != "stdio":
            raise ValueError(f"Unsupported MCP transport: {self.transport}")
        if not self.command:
            raise ValueError("MCP stdio transport requires command")

        async with stdio_client(self._stdio_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
        self._tools = [
            self._openai_tool_definition(
                t.name,
                t.description or f"MCP tool from {self.name}: {t.name}",
                (
                    t.inputSchema
                    if hasattr(t, "inputSchema") and t.inputSchema
                    else {"type": "object", "properties": {}}
                ),
            )
            for t in result.tools
        ]
        self._connected = True
        self._last_used_monotonic = time.monotonic()

    def _stdio_params(self) -> StdioServerParameters:
        if self.transport != "stdio":
            raise ValueError(f"Unsupported MCP transport: {self.transport}")
        if not self.command:
            raise ValueError("MCP stdio transport requires command")
        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
        )

    async def _call_stdio_tool(self, local_name: str, args: dict[str, Any]) -> Any:
        async with stdio_client(self._stdio_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(local_name, args)

    async def _connect_http(self) -> None:
        if not self.url:
            raise ValueError(f"MCP {self.transport} transport requires url")
        self._http_client = httpx.AsyncClient(timeout=10.0)
        response = await self._http_client.get(f"{self.url.rstrip('/')}/tools")
        response.raise_for_status()
        payload = response.json()
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
        """Shut down the session and terminate the server subprocess."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        if self._stdio_ctx:
            try:
                await self._stdio_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._stdio_ctx = None
        if self._http_client:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None
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
            assert self._http_client is not None
            response = await self._http_client.post(
                f"{self.url.rstrip('/')}/call",
                json={"name": local_name, "arguments": args},
            )
            response.raise_for_status()
            payload = response.json()
            self._last_used_monotonic = time.monotonic()
            if isinstance(payload, dict) and "content" in payload:
                return json.dumps(payload["content"], ensure_ascii=False)
            return json.dumps(payload, ensure_ascii=False)

        result = await self._call_stdio_tool(local_name, args)
        self._last_used_monotonic = time.monotonic()

        if result.content:
            return json.dumps(
                [c.text if hasattr(c, "text") else str(c) for c in result.content]
            )
        return str(result)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return the OpenAI-style function definitions for all discovered tools."""
        return self._tools
