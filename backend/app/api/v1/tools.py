"""Tool management CRUD endpoints.

Provides APIs for listing registered tools (builtin + MCP) and for managing
MCP server connections (register, test, unregister).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.tools.builtin import ALL_TOOLS
from app.core.tools.mcp.manager import mcp_manager

router = APIRouter(prefix="/tools", tags=["tools"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class _MCPConfig(BaseModel):
    command: str
    args: list[str] = []
    env: dict[str, str] = {}


class _RegisterToolRequest(BaseModel):
    name: str
    tool_type: str  # "mcp"
    config: _MCPConfig


class _TestToolRequest(BaseModel):
    """Request body for testing an MCP tool."""

    tool_name: str
    args: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/")
async def list_tools():
    """List all registered tools (builtin + MCP).

    Returns a combined list of tool definitions in OpenAI function format.
    """
    builtin_tools = list(ALL_TOOLS)
    mcp_tools = mcp_manager.get_all_tools()
    all_tools = builtin_tools + mcp_tools
    return {
        "items": all_tools,
        "total": len(all_tools),
        "builtin_count": len(builtin_tools),
        "mcp_count": len(mcp_tools),
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def register_tool(body: _RegisterToolRequest):
    """Register an MCP server and discover its tools.

    The server process is started on demand.  Discovered tool definitions
    are returned so the caller can inspect available tools immediately.
    """
    if body.tool_type != "mcp":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported tool_type: {body.tool_type}. Only 'mcp' is supported.",
        )

    try:
        tools = await mcp_manager.register(
            body.name,
            {
                "command": body.config.command,
                "args": body.config.args,
                "env": body.config.env,
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to connect to MCP server '{body.name}': {exc}",
        )

    return {
        "name": body.name,
        "tool_type": "mcp",
        "tools_count": len(tools),
        "tools": tools,
    }


@router.post("/{name}/test")
async def test_mcp_tool(name: str, body: _TestToolRequest):
    """Test an MCP tool by calling it with the provided arguments.

    The tool name should match the format
    ``mcp__{server_name}__{tool_name}``, or just ``{tool_name}`` for
    the server identified by *name*.
    """
    # Normalise tool name: if no prefix, prepend the server prefix
    tool_name = body.tool_name
    if not tool_name.startswith(f"mcp__"):
        tool_name = f"mcp__{name}__{tool_name}"

    # Verify the owning client exists
    client = mcp_manager.get_client_for_tool(tool_name)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{name}' is not registered or has no tool matching '{body.tool_name}'",
        )

    try:
        result = await mcp_manager.execute(tool_name, body.args)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Tool call failed: {exc}",
        )

    return {"tool_name": tool_name, "result": result}


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_tool(name: str):
    """Unregister an MCP server and disconnect it."""
    client = mcp_manager.get_client_for_tool(f"mcp__{name}__")
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{name}' is not registered",
        )

    await mcp_manager.unregister(name)
    return None
