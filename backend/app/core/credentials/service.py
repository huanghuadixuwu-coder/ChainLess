"""V3 CredentialConnection lifecycle and runtime secret resolution."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found, validation_error
from app.core.acquisition.snapshot import credential_ref_ids_from_bundles, permission_bundles_for_proposal
from app.core.capabilities.bounds import validate_bounded_json
from app.core.observability import increment_acquisition_metric
from app.core.secrets import decrypt_secret, encrypt_secret, redact_sensitive_data, secret_metadata
from app.core.acquisition.schemas import CredentialConnectionResponse
from app.models.acquisition import (
    APIToolConfiguration,
    ActivationTarget,
    AcquisitionProposal,
    AcquisitionVerification,
    BrowserAutomationConfiguration,
    CredentialConnection,
    MCPServerConfiguration,
    WorkspaceConnector,
)

ACTIVE_RESOLUTION_STATUS = "active"
INVALIDATING_PROPOSAL_STATUSES = {
    "verified",
    "activation_requested",
    "activation_approved",
    "activating",
    "activated",
    "partial_activation",
}
VERIFICATION_STALE_PROPOSAL_STATUSES = {
    "verified",
    "activation_requested",
    "activation_approved",
    "activating",
}
ENCRYPTED_DB_STORAGE = "encrypted_db"
EXTERNAL_REF_STORAGE_KINDS = {"external_vault_ref"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _redacted_metadata(secret_value: str | None, metadata: dict[str, Any] | None) -> dict[str, Any]:
    redacted = redact_sensitive_data(metadata or {})
    if isinstance(redacted, dict):
        return {**secret_metadata(secret_value), **redacted}
    return secret_metadata(secret_value)


def _metadata_for_secret_ref(secret_ref: str | None, metadata: dict[str, Any] | None) -> dict[str, Any]:
    redacted = redact_sensitive_data(metadata or {})
    base = {"configured": bool(secret_ref), "secret_ref_present": bool(secret_ref)}
    if isinstance(redacted, dict):
        return {**base, **redacted}
    return base


async def _credential_or_404(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_connection_id: uuid.UUID,
    for_update: bool = False,
) -> CredentialConnection:
    stmt = select(CredentialConnection).where(
        CredentialConnection.id == credential_connection_id,
        CredentialConnection.tenant_id == tenant_id,
        CredentialConnection.user_id == user_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    credential = (await db.execute(stmt)).scalar_one_or_none()
    if credential is None:
        raise not_found("CREDENTIAL_CONNECTION_NOT_FOUND", "Credential connection not found")
    return credential


def _secret_ref_for_storage(
    *,
    secret_storage_kind: str,
    secret_value: str | None,
    secret_ref: str | None,
) -> str:
    if secret_storage_kind == ENCRYPTED_DB_STORAGE:
        if not secret_value:
            raise validation_error("Encrypted DB credentials require secret_value")
        return encrypt_secret(secret_value)
    if secret_storage_kind in EXTERNAL_REF_STORAGE_KINDS or secret_storage_kind.endswith("_ref"):
        if not secret_ref:
            raise validation_error("External credential references require secret_ref")
        return secret_ref
    raise validation_error(
        "Unsupported credential secret storage kind",
        {"secret_storage_kind": secret_storage_kind},
    )


def _metadata_for_storage(
    *,
    secret_storage_kind: str,
    secret_value: str | None,
    secret_ref: str | None,
    metadata_redacted: dict[str, Any] | None,
) -> dict[str, Any]:
    if secret_storage_kind == ENCRYPTED_DB_STORAGE:
        return _redacted_metadata(secret_value, metadata_redacted)
    return _metadata_for_secret_ref(secret_ref, metadata_redacted)


async def create_credential_connection(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    provider: str,
    connection_type: str,
    credential_kind: str,
    secret_storage_kind: str,
    secret_value: str | None = None,
    secret_ref: str | None = None,
    scopes: list[str] | None = None,
    allowed_target_types: list[str] | None = None,
    allowed_target_refs: list[dict[str, Any]] | None = None,
    metadata_redacted: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> CredentialConnection:
    stored_secret_ref = _secret_ref_for_storage(
        secret_storage_kind=secret_storage_kind,
        secret_value=secret_value,
        secret_ref=secret_ref,
    )
    credential = CredentialConnection(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        provider=provider,
        connection_type=connection_type,
        credential_kind=credential_kind,
        secret_storage_kind=secret_storage_kind,
        secret_ref=stored_secret_ref,
        secret_generation=1,
        scopes=scopes or [],
        allowed_target_types=allowed_target_types or [],
        allowed_target_refs=allowed_target_refs or [],
        status="active",
        metadata_redacted=_metadata_for_storage(
            secret_storage_kind=secret_storage_kind,
            secret_value=secret_value,
            secret_ref=secret_ref,
            metadata_redacted=metadata_redacted,
        ),
        expires_at=expires_at,
    )
    db.add(credential)
    await db.flush()
    return credential


def credential_connection_response(credential: CredentialConnection) -> CredentialConnectionResponse:
    return CredentialConnectionResponse(
        id=credential.id,
        tenant_id=credential.tenant_id,
        user_id=credential.user_id,
        name=credential.name,
        provider=credential.provider,
        connection_type=credential.connection_type,
        credential_kind=credential.credential_kind,
        secret_storage_kind=credential.secret_storage_kind,
        secret_generation=credential.secret_generation,
        secret_ref_present=bool(credential.secret_ref),
        scopes=credential.scopes or [],
        allowed_target_types=credential.allowed_target_types or [],
        allowed_target_refs=credential.allowed_target_refs or [],
        status=credential.status,
        metadata_redacted=redact_sensitive_data(credential.metadata_redacted or {}),
        expires_at=credential.expires_at,
        last_validated_at=credential.last_validated_at,
        rotation_required_at=credential.rotation_required_at,
        revoked_at=credential.revoked_at,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


def _target_ref_matches(allowed_ref: dict[str, Any], target_ref: Any) -> bool:
    if target_ref is None:
        return False
    if isinstance(target_ref, dict):
        return all(str(target_ref.get(key)) == str(value) for key, value in allowed_ref.items())
    target_ref_text = str(target_ref)
    for key in ("id", "target_id", "ref", "manifest_ref", "name", "target_name"):
        value = allowed_ref.get(key)
        if value is not None and str(value) == target_ref_text:
            return True
    return False


def _ensure_target_allowed(
    credential: CredentialConnection,
    *,
    target_type: str | None,
    target_ref: Any,
) -> None:
    if target_type and credential.allowed_target_types and target_type not in credential.allowed_target_types:
        raise api_error(
            403,
            "CREDENTIAL_TARGET_NOT_ALLOWED",
            "Credential is not allowed for this target type",
            {"target_type": target_type},
        )
    if target_ref is not None and credential.allowed_target_refs:
        if not any(_target_ref_matches(allowed_ref, target_ref) for allowed_ref in credential.allowed_target_refs):
            raise api_error(
                403,
                "CREDENTIAL_TARGET_NOT_ALLOWED",
                "Credential is not allowed for this target",
            )


def _ensure_runtime_resolvable(credential: CredentialConnection) -> None:
    now = _now()
    if credential.status != ACTIVE_RESOLUTION_STATUS or (
        credential.expires_at is not None and credential.expires_at <= now
    ):
        raise api_error(
            409,
            "CREDENTIAL_NOT_ACTIVE",
            "Credential is not active for runtime execution",
            {"status": credential.status},
        )
    if credential.secret_storage_kind != ENCRYPTED_DB_STORAGE:
        raise api_error(
            409,
            "CREDENTIAL_SECRET_NOT_RESOLVABLE",
            "Only encrypted DB credentials can be resolved to raw runtime secret material",
            {"secret_storage_kind": credential.secret_storage_kind},
        )


async def resolve_credential_secret(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_connection_id: uuid.UUID,
    target_type: str | None = None,
    target_ref: Any = None,
) -> str:
    credential = await _credential_or_404(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_connection_id=credential_connection_id,
    )
    _ensure_runtime_resolvable(credential)
    _ensure_target_allowed(credential, target_type=target_type, target_ref=target_ref)
    return decrypt_secret(credential.secret_ref)


async def rotate_credential_connection(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_connection_id: uuid.UUID,
    secret_value: str | None = None,
    secret_ref: str | None = None,
    secret_storage_kind: str | None = None,
    metadata_redacted: dict[str, Any] | None = None,
) -> CredentialConnection:
    credential = await _credential_or_404(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_connection_id=credential_connection_id,
        for_update=True,
    )
    storage_kind = secret_storage_kind or credential.secret_storage_kind
    credential.secret_ref = _secret_ref_for_storage(
        secret_storage_kind=storage_kind,
        secret_value=secret_value,
        secret_ref=secret_ref,
    )
    credential.secret_storage_kind = storage_kind
    credential.secret_generation += 1
    credential.status = "active"
    credential.revoked_at = None
    credential.rotation_required_at = None
    credential.metadata_redacted = _metadata_for_storage(
        secret_storage_kind=storage_kind,
        secret_value=secret_value,
        secret_ref=secret_ref,
        metadata_redacted=metadata_redacted or credential.metadata_redacted,
    )
    await invalidate_dependent_activation_snapshots(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_connection_id=credential.id,
        reason="rotated",
    )
    await db.flush()
    return credential


async def revoke_credential_connection(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_connection_id: uuid.UUID,
) -> CredentialConnection:
    credential = await _credential_or_404(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_connection_id=credential_connection_id,
        for_update=True,
    )
    was_revoked = credential.status == "revoked"
    credential.status = "revoked"
    credential.revoked_at = _now()
    if not was_revoked:
        increment_acquisition_metric("acquisition_credential_revocations")
    await invalidate_dependent_activation_snapshots(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_connection_id=credential.id,
        reason="revoked",
    )
    await db.flush()
    return credential


def _proposal_references_credential(proposal: AcquisitionProposal, credential_connection_id: uuid.UUID) -> bool:
    refs = credential_ref_ids_from_bundles(permission_bundles_for_proposal(proposal))
    return str(credential_connection_id) in refs


def _verification_references_credential(
    verification: AcquisitionVerification,
    credential_connection_id: uuid.UUID,
) -> bool:
    for generation in (verification.verified_snapshot_payload or {}).get("credential_generations") or []:
        if str(generation.get("credential_connection_id")) == str(credential_connection_id):
            return True
    return False


def _credential_ref_matches(value: Any, credential_connection_id: uuid.UUID) -> bool:
    return value is not None and str(value) == str(credential_connection_id)


def _credential_ref_list_matches(refs: Any, credential_connection_id: uuid.UUID) -> bool:
    if not isinstance(refs, list):
        return False
    for ref in refs:
        if _credential_ref_matches(ref, credential_connection_id):
            return True
        if isinstance(ref, dict):
            for key in ("credential_connection_id", "credential_connection_ref", "credential_ref", "id", "ref"):
                if _credential_ref_matches(ref.get(key), credential_connection_id):
                    return True
    return False


def _disable_target_for_credential(
    target: ActivationTarget,
    *,
    credential_connection_id: uuid.UUID,
    reason: str,
    invalidated_at: str,
) -> None:
    if target.activation_status in {"disabled", "rolled_back"}:
        return
    existing = target.activation_result if isinstance(target.activation_result, dict) else {}
    events = [
        item
        for item in existing.get("credential_invalidation_events", [])
        if isinstance(item, dict)
    ]
    events.append(
        {
            "event": "credential_connection_invalidated",
            "reason": reason,
            "credential_connection_id": str(credential_connection_id),
            "at": invalidated_at,
        }
    )
    target.activation_status = "disabled"
    target.activated_resource_ref = None
    target.activation_result = validate_bounded_json(
        {
            **existing,
            "phase": "disabled",
            "disabled_reason": f"Credential connection {reason}",
            "credential_invalidation_events": events[-10:],
        },
        field="activation_result",
    )


async def _disable_dependent_targets_and_configs(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_ids: list[uuid.UUID],
    credential_connection_id: uuid.UUID,
    reason: str,
    invalidated_at: str,
) -> list[uuid.UUID]:
    targets = []
    if proposal_ids:
        targets = list(
            (
                await db.execute(
                    select(ActivationTarget)
                    .where(
                        ActivationTarget.tenant_id == tenant_id,
                        ActivationTarget.user_id == user_id,
                        ActivationTarget.proposal_id.in_(proposal_ids),
                    )
                    .with_for_update()
                )
            ).scalars()
        )
    affected_targets = [
        target
        for target in targets
        if str(credential_connection_id)
        in credential_ref_ids_from_bundles([target.permission_bundle if isinstance(target.permission_bundle, dict) else {}])
    ]
    affected_target_ids = [target.id for target in affected_targets]
    for target in affected_targets:
        _disable_target_for_credential(
            target,
            credential_connection_id=credential_connection_id,
            reason=reason,
            invalidated_at=invalidated_at,
        )

    api_tools = list(
        (
            await db.execute(
                select(APIToolConfiguration)
                .where(
                    APIToolConfiguration.tenant_id == tenant_id,
                    APIToolConfiguration.user_id == user_id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    for api_tool in api_tools:
        if api_tool.enabled and (
            _credential_ref_matches(api_tool.credential_ref, credential_connection_id)
            or api_tool.activation_target_id in affected_target_ids
        ):
            api_tool.enabled = False
            api_tool.last_verified_at = None

    browser_configs = list(
        (
            await db.execute(
                select(BrowserAutomationConfiguration)
                .where(
                    BrowserAutomationConfiguration.tenant_id == tenant_id,
                    BrowserAutomationConfiguration.user_id == user_id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    for browser_config in browser_configs:
        if browser_config.enabled and (
            _credential_ref_matches(browser_config.credential_ref, credential_connection_id)
            or browser_config.activation_target_id in affected_target_ids
        ):
            browser_config.enabled = False
            browser_config.last_verified_at = None

    mcp_configs = list(
        (
            await db.execute(
                select(MCPServerConfiguration)
                .where(
                    MCPServerConfiguration.tenant_id == tenant_id,
                    MCPServerConfiguration.user_id == user_id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    for mcp_config in mcp_configs:
        if mcp_config.enabled and (
            _credential_ref_list_matches(mcp_config.credential_connection_refs, credential_connection_id)
            or mcp_config.activation_target_id in affected_target_ids
        ):
            mcp_config.enabled = False
            mcp_config.disabled_at = _now()
            mcp_config.last_verified_at = None

    workspace_connectors = list(
        (
            await db.execute(
                select(WorkspaceConnector)
                .where(
                    WorkspaceConnector.tenant_id == tenant_id,
                    WorkspaceConnector.user_id == user_id,
                    WorkspaceConnector.activation_target_id.in_(affected_target_ids),
                )
                .with_for_update()
            )
        ).scalars()
    )
    for workspace_connector in workspace_connectors:
        if workspace_connector.enabled:
            workspace_connector.enabled = False
            workspace_connector.last_verified_at = None

    return affected_target_ids


async def invalidate_dependent_activation_snapshots(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_connection_id: uuid.UUID,
    reason: str,
) -> list[uuid.UUID]:
    proposals = list(
        (
            await db.execute(
                select(AcquisitionProposal)
                .where(
                    AcquisitionProposal.tenant_id == tenant_id,
                    AcquisitionProposal.user_id == user_id,
                    AcquisitionProposal.status.in_(INVALIDATING_PROPOSAL_STATUSES),
                )
                .with_for_update()
            )
        ).scalars()
    )
    affected = [
        proposal
        for proposal in proposals
        if _proposal_references_credential(proposal, credential_connection_id)
    ]
    invalidated_at = _now().isoformat()
    affected_ids = [proposal.id for proposal in affected]
    await _disable_dependent_targets_and_configs(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_ids=affected_ids,
        credential_connection_id=credential_connection_id,
        reason=reason,
        invalidated_at=invalidated_at,
    )
    if not affected:
        await db.flush()
        return []

    for proposal in affected:
        history = list(proposal.approval_history or [])
        history.append(
            {
                "event": "verification_stale",
                "reason": f"Credential connection {reason}",
                "credential_connection_id": str(credential_connection_id),
                "at": invalidated_at,
            }
        )
        if proposal.status in VERIFICATION_STALE_PROPOSAL_STATUSES:
            proposal.status = "verification_stale"
        proposal.activation_snapshot_hash = None
        proposal.snapshot_created_at = None
        proposal.approval_history = validate_bounded_json(history[-50:], field="approval_history")

    verifications = list(
        (
            await db.execute(
                select(AcquisitionVerification).where(
                    AcquisitionVerification.tenant_id == tenant_id,
                    AcquisitionVerification.user_id == user_id,
                    AcquisitionVerification.proposal_id.in_(affected_ids),
                    AcquisitionVerification.status == "passed",
                )
            )
        ).scalars()
    )
    for verification in verifications:
        if not _verification_references_credential(verification, credential_connection_id):
            continue
        verification.verified_snapshot_hash = None
        verification.verified_snapshot_payload = validate_bounded_json(
            {
                **(verification.verified_snapshot_payload or {}),
                "invalidated_by_credential_connection_id": str(credential_connection_id),
                "credential_invalidation_reason": reason,
                "credential_invalidated_at": invalidated_at,
            },
            field="verified_snapshot_payload",
        )
    await db.flush()
    return affected_ids
