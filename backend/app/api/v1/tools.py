"""Tool management CRUD endpoints.

Provides APIs for listing registered tools (builtin + MCP) and for managing
MCP server connections (register, test, unregister).
"""

from __future__ import annotations

import logging
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found
from app.api.deps import get_current_user, get_db, require_role
from app.api.pagination import paginated_response
from app.core.agent.code_executor import CODE_AS_ACTION_TOOL
from app.core.tools.configuration import (
    VALID_RISKS,
    apply_tool_configuration,
    get_tool_configurations,
    tool_name,
)
from app.core.tools.builtin import ALL_TOOLS
from app.core.tools.mcp.manager import mcp_manager
from app.models.tool_configuration import ToolConfiguration

router = APIRouter(prefix="/tools", tags=["tools"])
logger = logging.getLogger(__name__)


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


class _ToolConfigurationRequest(BaseModel):
    enabled: bool | None = None
    risk_override: str | None = None


async def _configured_tools(db: AsyncSession, tenant_id: str) -> list[dict]:
    builtin_tools = list(ALL_TOOLS) + [CODE_AS_ACTION_TOOL]
    mcp_tools = mcp_manager.get_all_tools()
    configs = await get_tool_configurations(db, tenant_id)
    return [
        apply_tool_configuration(tool, configs.get(tool_name(tool)))
        for tool in builtin_tools + mcp_tools
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/")
async def list_tools(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    request: Request = None,
    user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all registered tools (builtin + MCP).

    Returns a combined list of tool definitions in OpenAI function format.
    """
    builtin_tools = list(ALL_TOOLS) + [CODE_AS_ACTION_TOOL]
    mcp_tools = mcp_manager.get_all_tools()
    all_tools = await _configured_tools(db, user["tenant_id"])
    total = len(all_tools)
    page = all_tools[offset:offset + limit]
    envelope = paginated_response(page, total, limit, offset, request)
    envelope.update({
        "builtin_count": len(builtin_tools),
        "mcp_count": len(mcp_tools),
    })
    return envelope


@router.get("/available")
async def list_available_tools(
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
    request: Request = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List enabled tools available to the chat composer for the current user."""
    enabled_tools = [
        tool
        for tool in await _configured_tools(db, user["tenant_id"])
        if tool.get("enabled", True) is not False
    ]
    total = len(enabled_tools)
    page = enabled_tools[offset:offset + limit]
    return paginated_response(page, total, limit, offset, request)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def register_tool(body: _RegisterToolRequest, _: dict = Depends(require_role("admin"))):
    """Register an MCP server and discover its tools.

    The server process is started on demand.  Discovered tool definitions
    are returned so the caller can inspect available tools immediately.
    """
    if body.tool_type != "mcp":
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            f"Unsupported tool_type: {body.tool_type}. Only 'mcp' is supported.",
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
    except Exception:
        logger.exception("Failed to connect to MCP server %s", body.name)
        raise api_error(
            status.HTTP_502_BAD_GATEWAY,
            "MCP_CONNECTION_FAILED",
            "Failed to connect to MCP server",
        )

    return {
        "name": body.name,
        "tool_type": "mcp",
        "tools_count": len(tools),
        "tools": tools,
    }


@router.post("/{name}/test")
async def test_mcp_tool(
    name: str,
    body: _TestToolRequest,
    _: dict = Depends(require_role("admin")),
):
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
        raise not_found(
            "TOOL_NOT_FOUND",
            f"MCP server '{name}' is not registered or has no tool matching '{body.tool_name}'",
        )

    try:
        result = await mcp_manager.execute(tool_name, body.args)
    except Exception:
        logger.exception("MCP tool call failed for %s", tool_name)
        raise api_error(
            status.HTTP_502_BAD_GATEWAY,
            "MCP_CONNECTION_FAILED",
            "Tool call failed",
        )

    return {"tool_name": tool_name, "result": result}


@router.patch("/{name}/configuration")
async def configure_tool(
    name: str,
    body: _ToolConfigurationRequest,
    user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Configure tenant-local activation and risk override for a tool."""
    known_tools = list(ALL_TOOLS) + [CODE_AS_ACTION_TOOL] + mcp_manager.get_all_tools()
    known = {tool_name(tool): tool for tool in known_tools}
    if name not in known:
        raise not_found("TOOL_NOT_FOUND", "Tool not found")

    tenant_id = uuid.UUID(user["tenant_id"])
    config = (
        await db.execute(
            select(ToolConfiguration).where(
                ToolConfiguration.tenant_id == tenant_id,
                ToolConfiguration.name == name,
            )
        )
    ).scalar_one_or_none()
    if config is None:
        tool_type = "mcp" if name.startswith("mcp__") else "builtin"
        config = ToolConfiguration(
            tenant_id=tenant_id,
            name=name,
            tool_type=tool_type,
        )
        db.add(config)

    if "enabled" in body.model_fields_set:
        if body.enabled is None:
            raise api_error(
                status.HTTP_400_BAD_REQUEST,
                "VALIDATION_ERROR",
                "enabled must be true or false",
            )
        config.enabled = body.enabled
    if "risk_override" in body.model_fields_set:
        if body.risk_override is not None and body.risk_override not in VALID_RISKS:
            raise api_error(
                status.HTTP_400_BAD_REQUEST,
                "VALIDATION_ERROR",
                "risk_override must be safe, risky, destructive, or null",
            )
        config.risk_override = body.risk_override

    await db.commit()
    await db.refresh(config)
    return {
        "name": config.name,
        "tool_type": config.tool_type,
        "enabled": config.enabled,
        "risk_override": config.risk_override,
    }


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_tool(name: str, _: dict = Depends(require_role("admin"))):
    """Unregister an MCP server and disconnect it."""
    client = mcp_manager.get_client_for_tool(f"mcp__{name}__")
    if not client:
        raise not_found("TOOL_NOT_FOUND", f"MCP server '{name}' is not registered")

    await mcp_manager.unregister(name)
    return None
