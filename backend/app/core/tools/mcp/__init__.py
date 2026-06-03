"""MCP (Model Context Protocol) tool integration module.

Provides an MCP client wrapper and a manager that registers MCP servers,
discovers their tools, and routes agent tool calls to them.
"""

from .client import MCPToolClient
from .manager import MCPManager, mcp_manager

__all__ = [
    "MCPToolClient",
    "MCPManager",
    "mcp_manager",
]
