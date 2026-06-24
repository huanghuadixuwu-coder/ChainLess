"""Workspace Connector service.

This module owns approved local/workspace path mapping. Agent/runtime contracts
only receive connector metadata; the real host path is encrypted for trusted
mount orchestration and never included in audit details or mount payloads.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit.service import AuditRecord, add_audit_log
from app.core.secrets import encrypt_secret
from app.models.acquisition import WorkspaceConnector
from app.models.conversation import Conversation
from app.models.tool_confirmation import ToolConfirmation

CONNECTOR_MOUNT_ROOT = "/workspace/connectors"
CONNECTOR_ID_PREFIX = "wsc_"


class WorkspaceConnectorApprovalRequired(PermissionError):
    """Raised when a local/workspace path mapping is requested without approval."""


class WorkspaceConnectorServiceError(RuntimeError):
    """Base error for connector lifecycle failures."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _connector_id() -> str:
    return f"{CONNECTOR_ID_PREFIX}{uuid.uuid4().hex}"


def _connector_path(connector_id: str) -> str:
    return f"{CONNECTOR_MOUNT_ROOT}/{connector_id}"


def _canonical_host_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _host_realpath_hash(path: str | Path) -> str:
    resolved = _canonical_host_path(path)
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
        b"chainless/workspace-connector/v1\0" + resolved.encode("utf-8", errors="replace"),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest}"


def _display_path(path: str | Path) -> str:
    resolved = Path(path).expanduser()
    name = resolved.name or "workspace"
    return f"approved://{name}"


async def _validate_connector_approval(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    approval_id: uuid.UUID,
    canonical_host_path: str,
    host_realpath_hash: str,
    mode: str,
) -> None:
    confirmation = (
        await db.execute(
            select(ToolConfirmation)
            .join(Conversation, ToolConfirmation.conversation_id == Conversation.id)
            .where(
                ToolConfirmation.id == approval_id,
                ToolConfirmation.status == "approved",
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if confirmation is None:
        raise WorkspaceConnectorApprovalRequired(
            "Workspace Connector approval must be an approved confirmation owned by this tenant and user."
        )
    args = confirmation.args if isinstance(confirmation.args, dict) else {}
    if confirmation.tool_name != "workspace_connector.create":
        raise WorkspaceConnectorApprovalRequired(
            "Workspace Connector approval must be for workspace_connector.create."
        )
    if args.get("purpose") != "workspace_connector":
        raise WorkspaceConnectorApprovalRequired(
            "Workspace Connector approval purpose must be workspace_connector."
        )
    if args.get("mode") != mode:
        raise WorkspaceConnectorApprovalRequired(
            "Workspace Connector approval mode does not match this request."
        )
    if not _approval_host_identity_matches(
        args,
        canonical_host_path=canonical_host_path,
        host_realpath_hash=host_realpath_hash,
    ):
        raise WorkspaceConnectorApprovalRequired(
            "Workspace Connector approval host path does not match this request."
        )
    reused = (
        await db.execute(
            select(WorkspaceConnector.id).where(
                WorkspaceConnector.tenant_id == tenant_id,
                WorkspaceConnector.user_id == user_id,
                WorkspaceConnector.allowlist_rule["approval_id"].astext == str(approval_id),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if reused is not None:
        raise WorkspaceConnectorApprovalRequired(
            "Workspace Connector approval has already been used; ask the user to approve it again."
        )


def _approval_host_identity_matches(
    args: dict[str, Any],
    *,
    canonical_host_path: str,
    host_realpath_hash: str,
) -> bool:
    approved_hash = args.get("host_realpath_hash")
    if isinstance(approved_hash, str):
        return hmac.compare_digest(approved_hash, host_realpath_hash)

    approved_path = args.get("canonical_host_path") or args.get("host_path")
    if not isinstance(approved_path, str):
        return False
    return hmac.compare_digest(_canonical_host_path(approved_path), canonical_host_path)


_DANGEROUS_ALLOWLIST_KEYS = {
    "approval_id",
    "confirmation_id",
    "host_path",
    "host_paths",
    "raw_host_path",
    "raw_host_path_exposed",
    "host_realpath",
    "host_realpath_hash",
    "host_path_secret_ref",
}
_DANGEROUS_ALLOWLIST_SUBSTRINGS = ("secret", "token", "password")


def _sanitize_allowlist_rule(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if (
                lowered in _DANGEROUS_ALLOWLIST_KEYS
                or any(marker in lowered for marker in _DANGEROUS_ALLOWLIST_SUBSTRINGS)
                or ("host" in lowered and "path" in lowered)
            ):
                continue
            sanitized[key_text] = _sanitize_allowlist_rule(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_allowlist_rule(item) for item in value]
    return value


async def create_workspace_connector(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    host_path: str | Path,
    mode: str,
    approval_id: uuid.UUID | None,
    activation_target_id: uuid.UUID | None = None,
    standing_permission_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    allowlist_rule: dict[str, Any] | None = None,
) -> WorkspaceConnector:
    """Create one approved connector mapping for a user.

    The approval id is intentionally mandatory. W5.1 does not expose a draft
    local-path owner because unapproved host paths must never become runtime
    state or agent context by accident.
    """

    if approval_id is None:
        raise WorkspaceConnectorApprovalRequired(
            "Workspace Connector creation requires explicit user approval."
        )
    if mode not in {"read_only", "read_write"}:
        raise WorkspaceConnectorServiceError("Workspace Connector mode must be read_only or read_write.")
    canonical_host_path = _canonical_host_path(host_path)
    host_realpath_hash = _host_realpath_hash(canonical_host_path)
    await _validate_connector_approval(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        approval_id=approval_id,
        canonical_host_path=canonical_host_path,
        host_realpath_hash=host_realpath_hash,
        mode=mode,
    )

    connector_id = _connector_id()
    mount_path = _connector_path(connector_id)
    now = _now()
    sanitized_allowlist_rule = _sanitize_allowlist_rule(allowlist_rule or {})
    record = WorkspaceConnector(
        tenant_id=tenant_id,
        user_id=user_id,
        activation_target_id=activation_target_id,
        name=name,
        connector_id=connector_id,
        display_path=_display_path(host_path),
        host_realpath_hash=host_realpath_hash,
        host_path_secret_ref=encrypt_secret(canonical_host_path),
        container_mount_path=mount_path,
        backend_mount_path=mount_path,
        sandbox_mount_path=mount_path,
        connector_root=mount_path,
        mount_generation=1,
        mount_health_status="healthy",
        mode=mode,
        allowlist_rule={
            **sanitized_allowlist_rule,
            "approval_id": str(approval_id),
            "raw_host_path_exposed": False,
        },
        standing_permission_id=standing_permission_id,
        enabled=True,
        expires_at=expires_at,
        last_verified_at=now,
    )
    db.add(record)
    await db.flush()
    await _audit(
        db,
        action="workspace_connector.created",
        tenant_id=tenant_id,
        user_id=user_id,
        connector=record,
        details={"mode": mode, "approval_id": str(approval_id)},
    )
    return record


async def revoke_workspace_connector(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    connector_id: str,
    reason: str,
) -> WorkspaceConnector:
    """Disable one connector and bump generation so stale bundles are rejected."""

    record = (
        await db.execute(
            select(WorkspaceConnector)
            .where(
                WorkspaceConnector.tenant_id == tenant_id,
                WorkspaceConnector.user_id == user_id,
                WorkspaceConnector.connector_id == connector_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if record is None:
        raise WorkspaceConnectorServiceError(f"Workspace Connector not found: {connector_id}")

    record.enabled = False
    record.mount_generation += 1
    record.mount_health_status = "stale"
    record.last_verified_at = None
    rule = record.allowlist_rule if isinstance(record.allowlist_rule, dict) else {}
    record.allowlist_rule = {
        **rule,
        "revoked_at": _now().isoformat(),
        "revocation_reason": reason,
    }
    await db.flush()
    await _audit(
        db,
        action="workspace_connector.revoked",
        tenant_id=tenant_id,
        user_id=user_id,
        connector=record,
        details={"reason": reason},
    )
    return record


async def _audit(
    db: AsyncSession,
    *,
    action: str,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    connector: WorkspaceConnector,
    details: dict[str, Any],
) -> None:
    """Audit seam; writes inside the caller transaction and never exposes paths."""

    await add_audit_log(
        db,
        AuditRecord(
            action=action,
            method="SYSTEM",
            path="/internal/workspace-connectors",
            status_code=200,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="workspace_connector",
            resource_id=str(connector.id),
            details={
                "connector_id": connector.connector_id,
                "mount_generation": connector.mount_generation,
                **details,
            },
        ),
    )
