"""MCP tool client wrapping the ``mcp`` Python SDK.

Manages a single MCP server connection over stdio transport, discovers
available tools on connect, and provides a ``call_tool`` method for
invoking them by name.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from typing import Any

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
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}

        self._session: ClientSession | None = None
        self._tools: list[dict[str, Any]] = []
        self._connected = False
        self._stdio_ctx: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the MCP server subprocess and discover its tools.

        Raises:
            Exception: Any error from subprocess startup, handshake, or
                tool listing is propagated to the caller.
        """
        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
        )
        # Use stdio_client context manager
        self._stdio_ctx = stdio_client(params)
        read, write = await self._stdio_ctx.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()

        result = await self._session.list_tools()
        self._tools = [
            {
                "type": "function",
                "function": {
                    "name": f"mcp__{self.name}__{t.name}",
                    "description": t.description
                    or f"MCP tool from {self.name}: {t.name}",
                    "parameters": (
                        t.inputSchema
                        if hasattr(t, "inputSchema") and t.inputSchema
                        else {"type": "object", "properties": {}}
                    ),
                },
            }
            for t in result.tools
        ]
        self._connected = True

    async def disconnect(self) -> None:
        """Shut down the session and terminate the server subprocess."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        self._connected = False

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
        local_name = tool_name.replace(f"mcp__{self.name}__", "", 1)
        result = await self._session.call_tool(local_name, args)

        if result.content:
            return json.dumps(
                [c.text if hasattr(c, "text") else str(c) for c in result.content]
            )
        return str(result)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return the OpenAI-style function definitions for all discovered tools."""
        return self._tools
