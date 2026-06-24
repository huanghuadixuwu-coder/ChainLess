"""User-scoped acquired tool manifest read model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.acquisition.facade import runtime_capability_enabled
from app.models.acquisition import (
    APIToolConfiguration,
    ActivationTarget,
    BrowserAutomationConfiguration,
    MCPServerConfiguration,
    WorkspaceConnector,
)

RUNTIME_CONFIG_MODELS: dict[str, type[Any]] = {
    "api_tool": APIToolConfiguration,
    "mcp_tool": MCPServerConfiguration,
    "workspace_connector": WorkspaceConnector,
    "browser_automation": BrowserAutomationConfiguration,
}


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _version_from_target(target: ActivationTarget) -> str | None:
    result = target.activation_result if isinstance(target.activation_result, dict) else {}
    manifest = result.get("tool_manifest") if isinstance(result.get("tool_manifest"), dict) else {}
    for key in ("manifest_version", "version", "activated_at", "hidden_at"):
        value = manifest.get(key)
        if value:
            return str(value)
    ref = target.activated_resource_ref if isinstance(target.activated_resource_ref, dict) else {}
    for key in ("manifest_version", "version", "activated_at", "hidden_at"):
        value = ref.get(key)
        if value:
            return str(value)
    timestamp = target.updated_at or target.created_at
    return timestamp.isoformat() if isinstance(timestamp, datetime) else None


async def get_user_tool_manifest_version(
    db: AsyncSession,
    *,
    tenant_id: str | uuid.UUID,
    user_id: str | uuid.UUID,
) -> str:
    """Return the freshest manifest version for acquired runtime targets."""

    tenant_uuid = _uuid(tenant_id)
    user_uuid = _uuid(user_id)
    targets = list(
        (
            await db.execute(
                select(ActivationTarget)
                .where(
                    ActivationTarget.tenant_id == tenant_uuid,
                    ActivationTarget.user_id == user_uuid,
                )
                .order_by(ActivationTarget.updated_at.desc())
            )
        ).scalars()
    )
    versions = [value for target in targets if (value := _version_from_target(target))]
    if not versions:
        return "empty"
    return max(versions)


async def assert_user_tool_manifest_current(
    db: AsyncSession,
    *,
    tenant_id: str | uuid.UUID,
    user_id: str | uuid.UUID,
    expected_version: str | None,
) -> None:
    """Fail closed when an acquired-tool run resumes with a stale manifest."""

    current_version = await get_user_tool_manifest_version(db, tenant_id=tenant_id, user_id=user_id)
    assert_manifest_version_current(current_version, expected_version=expected_version)


async def build_user_tool_manifest(
    db: AsyncSession,
    *,
    tenant_id: str | uuid.UUID,
    user_id: str | uuid.UUID,
) -> dict[str, Any]:
    """Build a bounded manifest read model for currently visible acquired tools."""

    tenant_uuid = _uuid(tenant_id)
    user_uuid = _uuid(user_id)
    tools: list[dict[str, Any]] = []
    for target_type, model in RUNTIME_CONFIG_MODELS.items():
        if not runtime_capability_enabled(target_type):
            continue
        rows = list(
            (
                await db.execute(
                    select(model)
                    .where(
                        model.tenant_id == tenant_uuid,
                        model.user_id == user_uuid,
                        model.enabled.is_(True),
                    )
                    .order_by(model.created_at.asc())
                    .limit(100)
                )
            ).scalars()
        )
        for row in rows:
            if await _config_visible_to_runtime(db, target_type, row):
                tools.append(_manifest_ref_for_config(target_type, row))
    return {
        "tenant_id": str(tenant_uuid),
        "user_id": str(user_uuid),
        "version": await get_user_tool_manifest_version(db, tenant_id=tenant_uuid, user_id=user_uuid),
        "tools": tools[:100],
    }


def assert_manifest_version_current(
    current_version: str,
    *,
    expected_version: str | None,
) -> None:
    """Fail closed when a resumed run references a stale acquired-tool manifest."""

    if expected_version and expected_version != current_version:
        raise ValueError("ACQUIRED_TOOL_MANIFEST_STALE")


def manifest_context_arg(version: str) -> dict[str, str]:
    return {"acquired_tool_manifest_version": version}


async def _config_visible_to_runtime(db: AsyncSession, target_type: str, row: Any) -> bool:
    if not bool(getattr(row, "enabled", False)):
        return False
    if getattr(row, "last_verified_at", None) is None:
        return False
    disabled_at = getattr(row, "disabled_at", None)
    if disabled_at is not None:
        return False
    activation_target_id = getattr(row, "activation_target_id", None)
    if activation_target_id is None:
        return True
    target = (
        await db.execute(
            select(ActivationTarget).where(
                ActivationTarget.id == activation_target_id,
                ActivationTarget.tenant_id == row.tenant_id,
                ActivationTarget.user_id == row.user_id,
                ActivationTarget.target_type == target_type,
            )
        )
    ).scalar_one_or_none()
    if target is None or target.activation_status != "active":
        return False
    resource_ref = target.activated_resource_ref if isinstance(target.activated_resource_ref, dict) else {}
    if resource_ref.get("hidden") is True:
        return False
    if resource_ref and resource_ref.get("exposed_to_runtime") is False:
        return False
    return True


def _manifest_ref_for_config(target_type: str, row: Any) -> dict[str, Any]:
    ref = {
        "target_type": target_type,
        "configuration_id": str(row.id),
        "activation_target_id": str(row.activation_target_id) if getattr(row, "activation_target_id", None) else None,
        "enabled": bool(getattr(row, "enabled", False)),
    }
    tool_name = getattr(row, "tool_name", None) or getattr(row, "name", None) or getattr(row, "server_name", None)
    if tool_name:
        ref["tool_name"] = str(tool_name)
        ref["manifest_ref"] = f"{target_type}:{tool_name}"
    disabled_at = getattr(row, "disabled_at", None)
    if isinstance(disabled_at, datetime):
        ref["disabled_at"] = disabled_at.isoformat()
    verified_at = getattr(row, "last_verified_at", None)
    if isinstance(verified_at, datetime):
        ref["last_verified_at"] = verified_at.isoformat()
    ref["generated_at"] = datetime.now(timezone.utc).isoformat()
    return {key: value for key, value in ref.items() if value is not None}
