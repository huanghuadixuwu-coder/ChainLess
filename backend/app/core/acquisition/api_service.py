"""API-facing read and mutation seam for V3 acquisition records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TypeVar

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found
from app.core.acquisition import lifecycle, repository
from app.core.acquisition.activation import approve_activation, run_activation_saga
from app.core.acquisition.development_patch import request_development_patch_handoff
from app.core.acquisition.journal import redact_sensitive_value, render_acquisition_journal
from app.core.acquisition.rollback import rollback_activation
from app.core.acquisition.schemas import (
    AcquisitionProposalRequest,
    BrowserAutomationConfigurationContract,
    CapabilityGapResponse,
    CapabilityRecommendationResponse,
    CredentialConnectionCreateRequest,
    ExplorationRunResponse,
    RuntimePlanningIssueResponse,
    StandingPermissionResponse,
    WorkspaceConnectorContract,
)
from app.core.acquisition.verification import verify_proposal
from app.core.credentials.service import (
    create_credential_connection,
    credential_connection_response,
    revoke_credential_connection,
    rotate_credential_connection,
)
from app.core.planning_issues.service import dismiss_runtime_planning_issue
from app.models.acquisition import (
    AcquisitionProposal,
    ActivationTarget,
    BrowserAutomationConfiguration,
    CapabilityGap,
    CapabilityRecommendation,
    CredentialConnection,
    ExplorationRun,
    RuntimePlanningIssue,
    StandingPermission,
    WorkspaceConnector,
)


T = TypeVar("T")
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _redacted(value: Any) -> Any:
    return redact_sensitive_value(_jsonable(value))


def _contract_payload(contract: BaseModel) -> dict[str, Any]:
    return _redacted(contract.model_dump(mode="json"))


async def _one(db: AsyncSession, stmt: Select[Any], code: str, message: str) -> Any:
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise not_found(code, message)
    return row


async def _page(
    db: AsyncSession,
    model: type[T],
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[T], int]:
    filters = (model.tenant_id == tenant_id, model.user_id == user_id)
    order_field = getattr(model, "created_at", None) or getattr(model, "started_at", None) or model.id
    total = int(
        (await db.execute(select(func.count()).select_from(model).where(*filters))).scalar_one()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(model)
                .where(*filters)
                .order_by(order_field.asc(), model.id.asc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )
    return rows, total


async def list_gaps(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await _page(db, CapabilityGap, tenant_id=tenant_id, user_id=user_id, limit=limit, offset=offset)
    return [_gap_payload(row) for row in rows], total


async def get_gap(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
) -> dict[str, Any]:
    return _gap_payload(await repository.get_gap(db, tenant_id=tenant_id, user_id=user_id, gap_id=gap_id))


async def dismiss_gap(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    reason: str | None,
) -> dict[str, Any]:
    row, _ = await repository.transition_gap(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        status="dismissed",
        idempotency_key=f"api:gaps:{gap_id}:dismiss",
    )
    await db.commit()
    return _gap_payload(row, extra={"transition_reason": reason})


async def snooze_gap(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    snoozed_until: datetime,
) -> dict[str, Any]:
    row, _ = await repository.transition_gap(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        status="snoozed",
        idempotency_key=f"api:gaps:{gap_id}:snooze:{snoozed_until.isoformat()}",
    )
    await db.commit()
    return _gap_payload(row, extra={"snoozed_until": snoozed_until})


async def approve_exploration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    source_run_id: str,
    strategy: str,
    risk_level: str,
    bounds: dict[str, Any],
    approval_id: uuid.UUID | None,
) -> dict[str, Any]:
    row = await lifecycle.start_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        source_run_id=source_run_id,
        strategy=strategy,
        risk_level=risk_level,
        bounds=bounds,
        approval_id=approval_id,
        idempotency_key=f"api:gaps:{gap_id}:approve-exploration:{source_run_id}",
    )
    await db.commit()
    return _exploration_payload(row)


async def list_explorations(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await _page(db, ExplorationRun, tenant_id=tenant_id, user_id=user_id, limit=limit, offset=offset)
    return [_exploration_payload(row) for row in rows], total


async def get_exploration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    exploration_id: uuid.UUID,
) -> dict[str, Any]:
    row = await repository.get_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        exploration_id=exploration_id,
    )
    return _exploration_payload(row)


async def list_recommendations(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await _page(
        db,
        CapabilityRecommendation,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return [_recommendation_payload(row) for row in rows], total


async def get_recommendation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    recommendation_id: uuid.UUID,
) -> dict[str, Any]:
    row = await repository.get_recommendation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        recommendation_id=recommendation_id,
    )
    return _recommendation_payload(row)


async def draft_proposal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request: AcquisitionProposalRequest,
) -> dict[str, Any]:
    row = await lifecycle.create_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_kind=request.proposal_kind,
        gap_id=request.gap_id,
        recommendation_id=request.recommendation_id,
        title=request.title,
        reason=request.reason,
        evidence=request.evidence,
        risk_level=request.risk_level,
        permission_bundle=request.permission_bundle.model_dump(mode="json"),
        primary_target=request.primary_target.model_dump(mode="json") if request.primary_target else None,
        secondary_targets=[target.model_dump(mode="json") for target in request.secondary_targets],
        development_handoff=request.development_handoff,
        verification_plan=request.verification_plan,
        rollback_plan=request.rollback_plan,
        user_visible_effect=request.user_visible_effect,
        idempotency_key=f"api:recommendations:{request.recommendation_id}:draft-proposal",
    )
    await db.commit()
    return _proposal_payload(row)


async def list_proposals(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await _page(db, AcquisitionProposal, tenant_id=tenant_id, user_id=user_id, limit=limit, offset=offset)
    return [_proposal_payload(row) for row in rows], total


async def get_proposal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
) -> dict[str, Any]:
    return _proposal_payload(
        await repository.get_proposal(db, tenant_id=tenant_id, user_id=user_id, proposal_id=proposal_id)
    )


async def verify_proposal_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    verification_kind: str,
    input_fixture: dict[str, Any],
    expected_result: dict[str, Any],
    actual_result: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    target_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    row = await verify_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        verification_kind=verification_kind,
        input_fixture=input_fixture,
        expected_result=expected_result,
        actual_result=actual_result,
        artifact_refs=artifact_refs,
        target_id=target_id,
        idempotency_key=f"api:proposals:{proposal_id}:verify:{verification_kind}",
    )
    await db.commit()
    return _redacted(
        {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "user_id": row.user_id,
            "proposal_id": row.proposal_id,
            "target_id": row.target_id,
            "verification_kind": row.verification_kind,
            "input_fixture": row.input_fixture,
            "expected_result": row.expected_result,
            "status": row.status,
            "actual_result": row.actual_result,
            "artifact_refs": row.artifact_refs,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "verified_snapshot_hash": row.verified_snapshot_hash,
            "verified_snapshot_payload": row.verified_snapshot_payload,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }
    )


async def approve_activation_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    approved_snapshot_hash: str,
    reason: str | None,
) -> dict[str, Any]:
    row = await approve_activation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        approved_hash=approved_snapshot_hash,
        reason=reason,
        idempotency_key=f"api:proposals:{proposal_id}:approve-activation:{approved_snapshot_hash}",
    )
    await db.commit()
    return _proposal_payload(row)


async def activate_proposal_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    approved_snapshot_hash: str,
    verification_id: uuid.UUID | None,
    target_ids: list[uuid.UUID] | None,
) -> dict[str, Any]:
    row = await run_activation_saga(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        approved_hash=approved_snapshot_hash,
        verification_id=verification_id,
        target_ids=target_ids,
        idempotency_key=f"api:proposals:{proposal_id}:activate:{approved_snapshot_hash}",
    )
    await db.commit()
    return _proposal_payload(row)


async def rollback_proposal_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    reason: str | None,
) -> dict[str, Any]:
    result = await rollback_activation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        reason=reason,
        idempotency_key=f"api:proposals:{proposal_id}:rollback",
    )
    row = await repository.get_proposal(db, tenant_id=tenant_id, user_id=user_id, proposal_id=proposal_id)
    await db.commit()
    return _redacted(
        {
            **_proposal_payload(row),
            "rollback": {
                "status": result.status,
                "changed": result.changed,
                "target_results": list(result.target_results),
                "user_visible_recovery_state": result.user_visible_recovery_state,
            },
        }
    )


async def reject_activation_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    reason: str | None,
) -> dict[str, Any]:
    row = await lifecycle.reject_activation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        reason=reason,
        idempotency_key=f"api:proposals:{proposal_id}:reject-activation",
    )
    await db.commit()
    return _proposal_payload(row)


async def handoff_development_patch_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
) -> dict[str, Any]:
    row = await request_development_patch_handoff(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        idempotency_key=f"api:proposals:{proposal_id}:handoff-development-patch",
    )
    await db.commit()
    return _redacted(
        {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "user_id": row.user_id,
            "proposal_id": row.proposal_id,
            "status": row.status,
            "base_git_commit": row.base_git_commit,
            "patch_artifact_ref": row.patch_artifact_ref,
            "patch_digest": row.patch_digest,
            "test_plan_ref": row.test_plan_ref,
            "rollback_plan_ref": row.rollback_plan_ref,
            "review_checklist_ref": row.review_checklist_ref,
            "apply_check_status": row.apply_check_status,
            "working_tree_mutation_allowed": row.working_tree_mutation_allowed,
            "handoff_requested_at": row.handoff_requested_at,
            "handoff_requested_by": row.handoff_requested_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


async def list_runtime_planning_issues(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await _page(
        db,
        RuntimePlanningIssue,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return [_runtime_issue_payload(row) for row in rows], total


async def get_runtime_planning_issue(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    issue_id: uuid.UUID,
) -> dict[str, Any]:
    row = await _one(
        db,
        select(RuntimePlanningIssue).where(
            RuntimePlanningIssue.id == issue_id,
            RuntimePlanningIssue.tenant_id == tenant_id,
            RuntimePlanningIssue.user_id == user_id,
        ),
        "RUNTIME_PLANNING_ISSUE_NOT_FOUND",
        "Runtime planning issue not found",
    )
    return _runtime_issue_payload(row)


async def dismiss_runtime_issue_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    issue_id: uuid.UUID,
) -> dict[str, Any]:
    try:
        row = await dismiss_runtime_planning_issue(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            issue_id=issue_id,
        )
    except ValueError as exc:
        raise not_found("RUNTIME_PLANNING_ISSUE_NOT_FOUND", "Runtime planning issue not found") from exc
    await db.commit()
    return _runtime_issue_payload(row)


async def create_credential_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request: CredentialConnectionCreateRequest,
) -> dict[str, Any]:
    row = await create_credential_connection(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        name=request.name,
        provider=request.provider,
        connection_type=request.connection_type,
        credential_kind=request.credential_kind,
        secret_storage_kind=request.secret_storage_kind,
        secret_value=request.secret_value,
        scopes=request.scopes,
        allowed_target_types=[str(item) for item in request.allowed_target_types],
        allowed_target_refs=request.allowed_target_refs,
        metadata_redacted=request.metadata_redacted,
        expires_at=request.expires_at,
    )
    await db.commit()
    return _credential_payload(row)


async def list_credentials(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await _page(
        db,
        CredentialConnection,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return [_credential_payload(row) for row in rows], total


async def get_credential(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> dict[str, Any]:
    row = await _one(
        db,
        select(CredentialConnection).where(
            CredentialConnection.id == credential_id,
            CredentialConnection.tenant_id == tenant_id,
            CredentialConnection.user_id == user_id,
        ),
        "CREDENTIAL_CONNECTION_NOT_FOUND",
        "Credential connection not found",
    )
    return _credential_payload(row)


async def validate_credential_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> dict[str, Any]:
    row = await _one(
        db,
        select(CredentialConnection)
        .where(
            CredentialConnection.id == credential_id,
            CredentialConnection.tenant_id == tenant_id,
            CredentialConnection.user_id == user_id,
        )
        .with_for_update(),
        "CREDENTIAL_CONNECTION_NOT_FOUND",
        "Credential connection not found",
    )
    row.last_validated_at = _now()
    await db.commit()
    return _credential_payload(row)


async def rotate_credential_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_id: uuid.UUID,
    secret_value: str | None,
    secret_ref: str | None,
    secret_storage_kind: str | None,
    metadata_redacted: dict[str, Any] | None,
) -> dict[str, Any]:
    row = await rotate_credential_connection(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_connection_id=credential_id,
        secret_value=secret_value,
        secret_ref=secret_ref,
        secret_storage_kind=secret_storage_kind,
        metadata_redacted=metadata_redacted,
    )
    await db.commit()
    return _credential_payload(row)


async def revoke_credential_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> dict[str, Any]:
    row = await revoke_credential_connection(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_connection_id=credential_id,
    )
    await db.commit()
    return _credential_payload(row)


async def list_browser_sessions(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await _page(
        db,
        BrowserAutomationConfiguration,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return [_browser_session_payload(row) for row in rows], total


async def get_browser_session(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> dict[str, Any]:
    row = await _browser_session_or_404(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )
    return _browser_session_payload(row)


async def terminate_browser_session_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    reason: str | None,
) -> dict[str, Any]:
    row = await _browser_session_or_404(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        for_update=True,
    )
    row.enabled = False
    if row.profile_retention_policy is None:
        row.profile_retention_policy = {}
    row.profile_retention_policy = _redacted(
        {
            **(row.profile_retention_policy or {}),
            "terminated_at": _now(),
            "termination_reason": reason,
        }
    )
    await db.commit()
    payload = _browser_session_payload(row)
    payload["status"] = "terminated"
    return payload


async def get_browser_trace(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    trace_id: str,
) -> dict[str, Any]:
    target = (
        await db.execute(
            select(ActivationTarget).where(
                ActivationTarget.tenant_id == tenant_id,
                ActivationTarget.user_id == user_id,
            )
        )
    ).scalars()
    for row in target:
        result = row.activation_result if isinstance(row.activation_result, dict) else {}
        trace = result.get("trace_artifact") if isinstance(result.get("trace_artifact"), dict) else None
        if trace and str(trace.get("run_id")) == trace_id:
            return _redacted(
                {
                    "id": trace_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "target_id": row.id,
                    "proposal_id": row.proposal_id,
                    "trace": trace,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
            )
    raise not_found("BROWSER_TRACE_NOT_FOUND", "Browser trace not found")


async def list_permissions(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await _page(
        db,
        StandingPermission,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return [_permission_payload(row) for row in rows], total


async def list_workspace_connectors(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await _page(
        db,
        WorkspaceConnector,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return [_workspace_connector_payload(row) for row in rows], total


async def get_workspace_connector(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    connector_id: uuid.UUID,
) -> dict[str, Any]:
    row = await _one(
        db,
        select(WorkspaceConnector).where(
            WorkspaceConnector.id == connector_id,
            WorkspaceConnector.tenant_id == tenant_id,
            WorkspaceConnector.user_id == user_id,
        ),
        "WORKSPACE_CONNECTOR_NOT_FOUND",
        "Workspace connector not found",
    )
    return _workspace_connector_payload(row)


async def revoke_workspace_connector_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    connector_id: uuid.UUID,
    reason: str | None,
) -> dict[str, Any]:
    row = await _one(
        db,
        select(WorkspaceConnector)
        .where(
            WorkspaceConnector.id == connector_id,
            WorkspaceConnector.tenant_id == tenant_id,
            WorkspaceConnector.user_id == user_id,
        )
        .with_for_update(),
        "WORKSPACE_CONNECTOR_NOT_FOUND",
        "Workspace connector not found",
    )
    row.enabled = False
    row.mount_generation += 1
    row.mount_health_status = "stale"
    row.last_verified_at = None
    rule = row.allowlist_rule if isinstance(row.allowlist_rule, dict) else {}
    row.allowlist_rule = _redacted(
        {
            **rule,
            "revoked_at": _now().isoformat(),
            "revocation_reason": reason,
        }
    )
    await db.commit()
    return _workspace_connector_payload(row)


async def revoke_permission_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    permission_id: uuid.UUID,
    reason: str | None,
) -> dict[str, Any]:
    row = await _permission_or_404(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        permission_id=permission_id,
        for_update=True,
    )
    row.status = "revoked"
    row.revoked_at = _now()
    events = list(row.audit_events or [])
    events.append({"event": "permission_revoked", "reason": reason, "recorded_at": _now().isoformat()})
    row.audit_events = _redacted(events[-50:])
    await db.commit()
    return _permission_payload(row)


async def renew_permission_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    permission_id: uuid.UUID,
) -> dict[str, Any]:
    row = await _permission_or_404(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        permission_id=permission_id,
        for_update=True,
    )
    row.status = "active"
    row.revoked_at = None
    row.renewal_required_at = None
    events = list(row.audit_events or [])
    events.append({"event": "permission_renewed", "recorded_at": _now().isoformat()})
    row.audit_events = _redacted(events[-50:])
    await db.commit()
    return _permission_payload(row)


async def acquisition_journal_from_api(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    section_limit: int | None = None,
) -> dict[str, Any]:
    view = await render_acquisition_journal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        section_limit=section_limit,
    )
    return _contract_payload(view)


async def _browser_session_or_404(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    for_update: bool = False,
) -> BrowserAutomationConfiguration:
    stmt = select(BrowserAutomationConfiguration).where(
        BrowserAutomationConfiguration.id == session_id,
        BrowserAutomationConfiguration.tenant_id == tenant_id,
        BrowserAutomationConfiguration.user_id == user_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await _one(db, stmt, "BROWSER_SESSION_NOT_FOUND", "Browser session not found")


async def _permission_or_404(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    permission_id: uuid.UUID,
    for_update: bool = False,
) -> StandingPermission:
    stmt = select(StandingPermission).where(
        StandingPermission.id == permission_id,
        StandingPermission.tenant_id == tenant_id,
        StandingPermission.user_id == user_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await _one(db, stmt, "STANDING_PERMISSION_NOT_FOUND", "Standing permission not found")


def _gap_payload(row: CapabilityGap, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return _contract_payload(
        CapabilityGapResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            source_kind=row.source_kind,
            source_run_id=row.source_run_id,
            conversation_id=row.conversation_id,
            dedupe_key=row.dedupe_key,
            title=row.title,
            description=row.description,
            gap_type=row.gap_type,
            severity=row.severity,
            status=row.status,
            source_evidence=row.source_evidence or [],
            evidence=row.evidence or {},
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            occurrence_count=row.occurrence_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    ) | _redacted(extra or {})


def _exploration_payload(row: ExplorationRun) -> dict[str, Any]:
    return _contract_payload(
        ExplorationRunResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            gap_id=row.gap_id,
            source_run_id=row.source_run_id,
            risk_level=row.risk_level,
            approval_id=row.approval_id,
            strategy=row.strategy,
            status=row.status,
            tool_events=row.tool_events or [],
            script_ref=row.script_ref,
            artifact_refs=row.artifact_refs or [],
            stdout_excerpt=row.stdout_excerpt,
            stderr_excerpt=row.stderr_excerpt,
            result_summary=row.result_summary,
            failure_reason=row.failure_reason,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )
    )


def _recommendation_payload(row: CapabilityRecommendation) -> dict[str, Any]:
    return _contract_payload(
        CapabilityRecommendationResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            gap_id=row.gap_id,
            exploration_run_id=row.exploration_run_id,
            recommendation_type=row.recommendation_type,
            title=row.title,
            summary=row.summary,
            reason=row.reason,
            evidence=row.evidence or {},
            risk_level=row.risk_level,
            expected_value=row.expected_value or {},
            required_permissions=row.required_permissions or {},
            candidate_targets=row.candidate_targets or [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    )


def _proposal_payload(row: AcquisitionProposal) -> dict[str, Any]:
    payload = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id,
        "proposal_kind": row.proposal_kind,
        "gap_id": row.gap_id,
        "recommendation_id": row.recommendation_id,
        "title": row.title,
        "reason": row.reason,
        "evidence": row.evidence or {},
        "status": row.status,
        "risk_level": row.risk_level,
        "permission_bundle": row.permission_bundle or {},
        "primary_target": row.primary_target,
        "secondary_targets": row.secondary_targets or [],
        "development_handoff": row.development_handoff,
        "verification_plan": row.verification_plan or {},
        "rollback_plan": row.rollback_plan or {},
        "user_visible_effect": row.user_visible_effect,
        "approval_history": row.approval_history or [],
        "activation_snapshot_hash": row.activation_snapshot_hash,
        "snapshot_created_at": row.snapshot_created_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    return _redacted(payload)


def _runtime_issue_payload(row: RuntimePlanningIssue) -> dict[str, Any]:
    return _contract_payload(
        RuntimePlanningIssueResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            source_run_id=row.source_run_id,
            conversation_id=row.conversation_id,
            issue_type=row.issue_type,
            available_capability_ref=row.available_capability_ref or {},
            missed_signal=row.missed_signal,
            planner_decision_summary=row.planner_decision_summary,
            expected_decision_summary=row.expected_decision_summary,
            severity=row.severity,
            evidence=row.evidence or {},
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    )


def _credential_payload(row: CredentialConnection) -> dict[str, Any]:
    return _contract_payload(credential_connection_response(row))


def _browser_session_payload(row: BrowserAutomationConfiguration) -> dict[str, Any]:
    payload = BrowserAutomationConfigurationContract(
        name=row.name,
        allowlisted_domains=row.allowlisted_domains or [],
        credential_ref=row.credential_ref,
        credential_generation=row.credential_generation,
        runtime_service_name=row.runtime_service_name,
        runtime_image_ref=row.runtime_image_ref,
        runtime_health_check=row.runtime_health_check or {},
        network_policy=row.network_policy or {},
        cookie_scope=row.cookie_scope or {},
        profile_policy=row.profile_policy or {},
        profile_storage_ref=row.profile_storage_ref,
        profile_retention_policy=row.profile_retention_policy or {},
        max_session_seconds=row.max_session_seconds,
        max_actions_per_run=row.max_actions_per_run,
        concurrency_limit=row.concurrency_limit,
        cpu_limit=row.cpu_limit,
        memory_limit_mb=row.memory_limit_mb,
        max_trace_bytes=row.max_trace_bytes,
        trace_retention_days=row.trace_retention_days,
        action_redaction_policy=row.action_redaction_policy or {},
        write_confirmation_policy=row.write_confirmation_policy or {},
        enabled=row.enabled,
        last_verified_at=row.last_verified_at,
    ).model_dump(mode="json")
    return _redacted(
        {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "user_id": row.user_id,
            "activation_target_id": row.activation_target_id,
            "status": "active" if row.enabled else "inactive",
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            **payload,
        }
    )


def _permission_payload(row: StandingPermission) -> dict[str, Any]:
    return _contract_payload(
        StandingPermissionResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            proposal_id=row.proposal_id,
            target_id=row.target_id,
            target_type=row.target_type,
            permission_scope=row.permission_scope or {},
            risk_level=row.risk_level,
            duration=row.duration,
            approved_snapshot_hash=row.approved_snapshot_hash,
            expires_at=row.expires_at,
            revocation_plan=row.revocation_plan or {},
            status=row.status,
            revoked_at=row.revoked_at,
            renewal_required_at=row.renewal_required_at,
            audit_events=row.audit_events or [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    )


def _workspace_connector_payload(row: WorkspaceConnector) -> dict[str, Any]:
    payload = WorkspaceConnectorContract(
        name=row.name,
        connector_id=row.connector_id,
        display_path=row.display_path,
        container_mount_path=row.container_mount_path,
        backend_mount_path=row.backend_mount_path,
        sandbox_mount_path=row.sandbox_mount_path,
        connector_root=row.connector_root,
        mount_generation=row.mount_generation,
        mount_health_status=row.mount_health_status,
        mode=row.mode,
        allowlist_rule=row.allowlist_rule or {},
        standing_permission_id=row.standing_permission_id,
        enabled=row.enabled,
        expires_at=row.expires_at,
        last_verified_at=row.last_verified_at,
    ).model_dump(mode="json")
    return _redacted(
        {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "user_id": row.user_id,
            "activation_target_id": row.activation_target_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            **payload,
        }
    )


def rethrow_api_http(exc: HTTPException) -> HTTPException:
    return exc
