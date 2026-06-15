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
        self._client_owners: dict[str, str | None] = {}

    def _registry_key(self, name: str, owner: str | None = None) -> str:
        if owner is None:
            return name
        return f"{owner}:{name}"

    def _visible_to(self, registry_key: str, owner: str | None = None) -> bool:
        registered_owner = self._client_owners.get(registry_key)
        return owner is None or registered_owner == owner

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def register(
        self,
        name: str,
        config: dict[str, Any],
        owner: str | None = None,
    ) -> list[dict[str, Any]]:
        """Register an MCP server and discover its tools.

        If a server with the same *name* already exists it is disconnected
        first (allowing re-registration / hot-reload).

        Args:
            name: Unique name for the MCP server instance.
            config: Dictionary with keys:
                - ``command`` (str, required): shell command to start the server.
                - ``args`` (list[str], optional): CLI arguments.
                - ``env`` (dict[str,str], optional): extra environment variables.
                - ``transport`` (stdio|http|sse, optional): MCP transport.
                - ``url`` (str, optional): HTTP/SSE MCP endpoint base URL.
                - ``idle_timeout_s`` (float, optional): reconnect after idle.

        Returns:
            List of discovered tool definitions (``openai`` format).
        """
        registry_key = self._registry_key(name, owner)
        if registry_key in self._clients:
            await self._clients[registry_key].disconnect()

        client = MCPToolClient(
            name,
            config.get("command"),
            config.get("args", []),
            config.get("env"),
            transport=config.get("transport", "stdio"),
            url=config.get("url"),
            idle_timeout_s=config.get("idle_timeout_s"),
        )
        await client.connect()
        self._clients[registry_key] = client
        self._client_owners[registry_key] = owner
        return client.get_tool_definitions()

    async def unregister(self, name: str, owner: str | None = None) -> None:
        """Unregister an MCP server and disconnect it."""
        registry_key = self._registry_key(name, owner)
        if registry_key in self._clients:
            await self._clients[registry_key].disconnect()
            del self._clients[registry_key]
            self._client_owners.pop(registry_key, None)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_all_tools(self, owner: str | None = None) -> list[dict[str, Any]]:
        """Return tool definitions visible to an owner scope."""
        tools: list[dict[str, Any]] = []
        for registry_key, client in self._clients.items():
            if not self._visible_to(registry_key, owner):
                continue
            tools.extend(client.get_tool_definitions())
        return tools

    def get_client_for_tool(
        self,
        tool_name: str,
        owner: str | None = None,
    ) -> MCPToolClient | None:
        """Return the client that owns a given fully qualified tool name.

        The tool name is expected to follow the prefix convention
        ``mcp__{server_name}__{tool_name}``.
        """
        for registry_key, client in self._clients.items():
            if not self._visible_to(registry_key, owner):
                continue
            if tool_name.startswith(f"mcp__{client.name}__"):
                return client
        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        owner: str | None = None,
    ) -> str:
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
        client = self.get_client_for_tool(tool_name, owner)
        if not client:
            raise ValueError(f"No MCP client for tool: {tool_name}")
        return await client.call_tool(tool_name, args)


# Global singleton
mcp_manager = MCPManager()
