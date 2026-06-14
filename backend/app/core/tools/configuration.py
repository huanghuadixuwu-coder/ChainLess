"""Tenant-scoped tool activation and risk override helpers."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tools.classifier import RiskLevel, classify_tool
from app.models.tool_configuration import ToolConfiguration

VALID_RISKS = {level.value for level in RiskLevel}


def tool_name(tool: dict[str, Any]) -> str:
    return tool.get("function", {}).get("name", "")


def default_tool_type(name: str) -> str:
    return "mcp" if name.startswith("mcp__") else "builtin"


async def get_tool_configurations(
    db: AsyncSession,
    tenant_id: str | uuid.UUID,
) -> dict[str, ToolConfiguration]:
    tenant_uuid = uuid.UUID(str(tenant_id))
    rows = (
        await db.execute(
            select(ToolConfiguration).where(ToolConfiguration.tenant_id == tenant_uuid)
        )
    ).scalars().all()
    return {row.name: row for row in rows}


def apply_tool_configuration(
    tool: dict[str, Any],
    config: ToolConfiguration | None,
) -> dict[str, Any]:
    name = tool_name(tool)
    tool_type = config.tool_type if config else default_tool_type(name)
    risk = (
        config.risk_override
        if config and config.risk_override
        else classify_tool(name, tool_type).value
    )
    enabled = config.enabled if config is not None else True
    return {
        **tool,
        "risk": risk,
        "tool_type": tool_type,
        "enabled": enabled,
        "risk_override": config.risk_override if config else None,
    }


def filter_enabled_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [tool for tool in tools if tool.get("enabled", True)]
