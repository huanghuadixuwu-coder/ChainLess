"""Route tool calls to the correct executor.

Checks builtin executors first, then falls through to MCP tools.
Tools that need runtime injection (e.g. ``shell_exec`` requires a
``SandboxManager``) are *not* in the flat ``TOOL_EXECUTORS`` dictionary;
the Agent Engine resolves those separately.
"""

import uuid
from collections.abc import Mapping

from sqlalchemy import select

from app.core.acquisition.activation import approved_snapshot_hash
from app.core.acquisition.facade import runtime_capability_enabled
from app.core.acquisition.policy import (
    RuntimePermissionRequest,
    build_runtime_confirmation_context,
    evaluate_runtime_permission,
)
from app.core.tools.builtin import TOOL_EXECUTORS
from app.core.capabilities.policy import require_worker_tool_policy
from app.core.browser_automation import execute_browser_tool
from app.core.secrets import redact_sensitive_data
from app.core.tools.api_runtime import execute_api_tool
from app.core.tools.manifest import assert_user_tool_manifest_current
from app.core.tools.mcp.manager import mcp_manager
from app.models.acquisition import ActivationTarget, AcquisitionProposal, MCPServerConfiguration


class AcquiredToolConfirmationRequired(RuntimeError):
    """Trusted backend confirmation request for a generic acquired tool."""

    def __init__(
        self,
        *,
        tool_name: str,
        args: Mapping,
        risk: str,
        confirmation_context: Mapping,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.original_args = dict(args or {})
        self.sanitized_args = redact_sensitive_data({
            str(key): value
            for key, value in dict(args or {}).items()
            if not str(key).startswith("__")
        })
        self.risk = risk
        self.confirmation_context = dict(confirmation_context)
        self.code = code
        self.message = message


async def execute_tool(tool_name: str, args: dict, context: dict | None = None):
    """Execute a tool by name.

    Args:
        tool_name: Name of the tool to execute (e.g. ``web_fetch``).
        args: Tool-specific arguments as a dictionary.

    Returns:
        Text result from the tool.

    Raises:
        ValueError: If *tool_name* is not recognised.
    """
    require_worker_tool_policy(tool_name, (context or {}).get("worker_context"))

    if tool_name in TOOL_EXECUTORS:
        executor = TOOL_EXECUTORS[tool_name]
        if tool_name in {"file_read", "file_write", "file_list"}:
            return await executor(tool_name, args, context=context)
        return await executor(tool_name, args)

    # Check MCP tools
    if tool_name.startswith("mcp__"):
        tenant_id = (context or {}).get("tenant_id")
        await _ensure_mcp_runtime_allowed(tool_name, args, context or {})
        return await mcp_manager.execute(tool_name, args, tenant_id)

    if tool_name.startswith("api__"):
        return await execute_api_tool(tool_name, args, context=context)

    if tool_name.startswith("browser__"):
        return await execute_browser_tool(tool_name, args, context=context)

    raise ValueError(f"Tool not found: {tool_name}")


async def _ensure_mcp_runtime_allowed(tool_name: str, args: dict, context: dict) -> None:
    if not runtime_capability_enabled("mcp_tool"):
        raise ValueError("MCP runtime is disabled")
    tenant_id = context.get("tenant_id")
    user_id = context.get("user_id")
    if tenant_id is None or user_id is None:
        raise ValueError("MCP tool execution requires tenant_id and user_id")
    server_name = _mcp_server_name(tool_name)
    if not server_name:
        raise ValueError(f"Invalid MCP tool name: {tool_name}")

    db = context.get("db")
    if db is not None:
        await _ensure_mcp_runtime_allowed_with_db(tool_name, args, context, db, server_name=server_name)
        return

    from app.api.deps import _async_session_factory

    async with _async_session_factory() as session:
        await _ensure_mcp_runtime_allowed_with_db(tool_name, args, context, session, server_name=server_name)


async def _ensure_mcp_runtime_allowed_with_db(
    tool_name: str,
    args: dict,
    context: dict,
    db,
    *,
    server_name: str,
) -> None:
    tenant_uuid = _uuid(context["tenant_id"])
    user_uuid = _uuid(context["user_id"])
    await assert_user_tool_manifest_current(
        db,
        tenant_id=tenant_uuid,
        user_id=user_uuid,
        expected_version=context.get("acquired_tool_manifest_version"),
    )
    record = (
        await db.execute(
            select(MCPServerConfiguration).where(
                MCPServerConfiguration.tenant_id == tenant_uuid,
                MCPServerConfiguration.user_id == user_uuid,
                MCPServerConfiguration.name == server_name,
                MCPServerConfiguration.enabled.is_(True),
                MCPServerConfiguration.last_verified_at.is_not(None),
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise ValueError(f"MCP tool not active for user: {tool_name}")
    if record.activation_target_id is None:
        return

    target = (
        await db.execute(
            select(ActivationTarget).where(
                ActivationTarget.id == record.activation_target_id,
                ActivationTarget.tenant_id == tenant_uuid,
                ActivationTarget.user_id == user_uuid,
                ActivationTarget.target_type == "mcp_tool",
                ActivationTarget.activation_status == "active",
            )
        )
    ).scalar_one_or_none()
    resource_ref = target.activated_resource_ref if target and isinstance(target.activated_resource_ref, dict) else {}
    if target is None or resource_ref.get("hidden") is True or resource_ref.get("exposed_to_runtime") is False:
        raise ValueError(f"MCP tool not active for user: {tool_name}")

    proposal = (
        await db.execute(
            select(AcquisitionProposal).where(
                AcquisitionProposal.id == target.proposal_id,
                AcquisitionProposal.tenant_id == tenant_uuid,
                AcquisitionProposal.user_id == user_uuid,
            )
        )
    ).scalar_one_or_none()
    approved_hash = approved_snapshot_hash(proposal) if proposal else None
    current_hash = proposal.activation_snapshot_hash if proposal else None
    if not proposal or not approved_hash or not current_hash:
        raise ValueError("MCP tool execution requires verified and approved activation snapshot evidence")

    bundle = target.permission_bundle if isinstance(target.permission_bundle, Mapping) else {}
    request = RuntimePermissionRequest(
        tenant_id=tenant_uuid,
        user_id=user_uuid,
        proposal_id=proposal.id,
        target_id=target.id,
        target_type="mcp_tool",
        permission_bundle=bundle,
        approved_snapshot_hash=approved_hash,
        current_snapshot_hash=current_hash,
        permission_scope=bundle.get("permission_scope") if isinstance(bundle.get("permission_scope"), Mapping) else None,
        risk_level=str(record.risk_level or bundle.get("risk_level") or "risky"),
        action_category=str(bundle.get("action_category") or bundle.get("side_effect_category") or "read"),
        tool_context={
            "tool_name": tool_name,
            "server_name": server_name,
            "args_schema": sorted(str(key) for key in (args or {}).keys()),
            "worker_run_id": (context.get("worker_context") or {}).get("worker_run_id"),
        },
        confirmation_context=context.get("confirmation_context"),
    )
    decision = await evaluate_runtime_permission(db, request)
    if decision.confirmation_required:
        confirmation_context = decision.context or build_runtime_confirmation_context(request)
        raise AcquiredToolConfirmationRequired(
            tool_name=tool_name,
            args=args,
            risk=str(confirmation_context.get("risk_level") or request.risk_level or "risky"),
            confirmation_context=confirmation_context,
            code=decision.code,
            message=decision.message,
        )
    if not decision.allowed:
        raise ValueError(decision.message)


def _mcp_server_name(tool_name: str) -> str:
    parts = tool_name.split("__", 2)
    return parts[1] if len(parts) == 3 and parts[0] == "mcp" else ""


def _uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
