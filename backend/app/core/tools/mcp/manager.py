"""MCP Manager — tracks all registered MCP servers and dispatches tool calls.

Provides a global singleton ``mcp_manager`` that the rest of the application
uses to register, unregister, and query MCP servers and their tools.
"""

from __future__ import annotations

from typing import Any

from .client import MCPToolClient


class MCPManager:
    """Manages the lifecycle of zero or more MCP server connections.

    The manager acts as a registry: you *register* an MCP server with a name
    and config, which starts the server and discovers its tools; you can then
    route tool calls to the owning server via ``execute``.
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPToolClient] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def register(self, name: str, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Register an MCP server and discover its tools.

        If a server with the same *name* already exists it is disconnected
        first (allowing re-registration / hot-reload).

        Args:
            name: Unique name for the MCP server instance.
            config: Dictionary with keys:
                - ``command`` (str, required): shell command to start the server.
                - ``args`` (list[str], optional): CLI arguments.
                - ``env`` (dict[str,str], optional): extra environment variables.

        Returns:
            List of discovered tool definitions (``openai`` format).
        """
        if name in self._clients:
            await self._clients[name].disconnect()

        client = MCPToolClient(
            name,
            config["command"],
            config.get("args", []),
            config.get("env"),
        )
        await client.connect()
        self._clients[name] = client
        return client.get_tool_definitions()

    async def unregister(self, name: str) -> None:
        """Unregister an MCP server and disconnect it."""
        if name in self._clients:
            await self._clients[name].disconnect()
            del self._clients[name]

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions from every registered MCP server."""
        tools: list[dict[str, Any]] = []
        for client in self._clients.values():
            tools.extend(client.get_tool_definitions())
        return tools

    def get_client_for_tool(self, tool_name: str) -> MCPToolClient | None:
        """Return the client that owns a given fully qualified tool name.

        The tool name is expected to follow the prefix convention
        ``mcp__{server_name}__{tool_name}``.
        """
        for client in self._clients.values():
            if tool_name.startswith(f"mcp__{client.name}__"):
                return client
        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute a tool on the MCP server that owns it.

        Args:
            tool_name: Fully qualified tool name
                (``mcp__{server_name}__{local_tool_name}``).
            args: Tool arguments.

        Returns:
            Tool result as a string.

        Raises:
            ValueError: If no registered server handles *tool_name*.
        """
        client = self.get_client_for_tool(tool_name)
        if not client:
            raise ValueError(f"No MCP client for tool: {tool_name}")
        return await client.call_tool(tool_name, args)


# Global singleton
mcp_manager = MCPManager()
