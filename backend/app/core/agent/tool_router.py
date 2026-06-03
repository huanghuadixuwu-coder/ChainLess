"""Route tool calls to the correct executor.

Checks builtin executors first, then falls through to MCP tools.
Tools that need runtime injection (e.g. ``shell_exec`` requires a
``SandboxManager``) are *not* in the flat ``TOOL_EXECUTORS`` dictionary;
the Agent Engine resolves those separately.
"""

from app.core.tools.builtin import TOOL_EXECUTORS
from app.core.tools.mcp.manager import mcp_manager


async def execute_tool(tool_name: str, args: dict) -> str:
    """Execute a tool by name.

    Args:
        tool_name: Name of the tool to execute (e.g. ``web_fetch``).
        args: Tool-specific arguments as a dictionary.

    Returns:
        Text result from the tool.

    Raises:
        ValueError: If *tool_name* is not recognised.
    """
    if tool_name in TOOL_EXECUTORS:
        executor = TOOL_EXECUTORS[tool_name]
        return await executor(tool_name, args)

    # Check MCP tools
    if tool_name.startswith("mcp__"):
        return await mcp_manager.execute(tool_name, args)

    raise ValueError(f"Tool not found: {tool_name}")
