"""Minimal user-scoped tool manifest invalidation for acquired targets."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities.bounds import validate_bounded_json
from app.models.acquisition import (
    APIToolConfiguration,
    ActivationTarget,
    BrowserAutomationConfiguration,
    MCPServerConfiguration,
    WorkspaceConnector,
)


CONFIG_MODELS: dict[str, type[Any]] = {
    "api_tool": APIToolConfiguration,
    "mcp_tool": MCPServerConfiguration,
    "workspace_connector": WorkspaceConnector,
    "browser_automation": BrowserAutomationConfiguration,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _hidden_ref_evidence(resource_ref: dict[str, Any], *, hidden_at: str) -> dict[str, Any]:
    """Return shallow manifest evidence without embedding rollback payloads."""

    evidence_keys = (
        "kind",
        "manifest_ref",
        "tool_name",
        "worker_id",
        "worker_version_id",
        "skill_id",
        "memory_id",
        "config_id",
        "server_name",
        "connector_id",
        "browser_session_id",
        "exposed_to_runtime",
    )
    return {
        **{key: resource_ref[key] for key in evidence_keys if key in resource_ref},
        "hidden": True,
        "hidden_at": hidden_at,
    }


def _manifest_version(now: datetime | None = None) -> str:
    return (now or _now()).isoformat()


def active_target_manifest_evidence(
    *,
    resource_ref: dict[str, Any],
    target: ActivationTarget,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return user-scoped manifest evidence for a newly active target."""

    version = _manifest_version(now)
    return {
        "status": "active",
        "version": version,
        "manifest_version": version,
        "activated_at": version,
        "tenant_id": str(target.tenant_id),
        "user_id": str(target.user_id),
        "target_id": str(target.id),
        "target_type": target.target_type,
        "manifest_ref": resource_ref.get("manifest_ref"),
        "tool_name": resource_ref.get("tool_name") or resource_ref.get("manifest_ref"),
        "configuration_id": resource_ref.get("configuration_id") or resource_ref.get("config_id"),
        "exposed_to_runtime": bool(resource_ref.get("exposed_to_runtime")),
        "idempotency_key": idempotency_key,
    }


async def hide_target_manifest_refs(
    db: AsyncSession,
    *,
    target: ActivationTarget,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Hide manifest/registry references for one activation target.

    This is intentionally narrow for W2.3: it updates durable rows already tied
    to the activation target and records hide evidence on the target result.
    """

    now = _now()
    hidden_refs: list[dict[str, Any]] = []
    disabled_config_ids: list[str] = []

    resource_ref = target.activated_resource_ref if isinstance(target.activated_resource_ref, dict) else {}
    if resource_ref:
        hidden_at = now.isoformat()
        hidden_ref = {**resource_ref, "hidden": True, "hidden_at": hidden_at}
        hidden_refs.append(_hidden_ref_evidence(resource_ref, hidden_at=hidden_at))
        target.activated_resource_ref = validate_bounded_json(_jsonable(hidden_ref), field="activated_resource_ref")

    model = CONFIG_MODELS.get(target.target_type)
    if model is not None:
        rows = list(
            (
                await db.execute(
                    select(model)
                    .where(
                        model.tenant_id == target.tenant_id,
                        model.user_id == target.user_id,
                        model.activation_target_id == target.id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )
        for row in rows:
            if getattr(row, "enabled", False):
                row.enabled = False
            if hasattr(row, "disabled_at") and getattr(row, "disabled_at", None) is None:
                row.disabled_at = now
            disabled_config_ids.append(str(row.id))

    result = target.activation_result if isinstance(target.activation_result, dict) else {}
    manifest_evidence = {
        "status": "hidden",
        "hidden_at": now.isoformat(),
        "version": now.isoformat(),
        "manifest_version": now.isoformat(),
        "hidden_refs": hidden_refs,
        "disabled_config_ids": disabled_config_ids,
        "idempotency_key": idempotency_key,
    }
    target.activation_result = validate_bounded_json(
        _jsonable({**result, "tool_manifest": manifest_evidence}),
        field="activation_result",
    )
    await db.flush()
    return manifest_evidence
