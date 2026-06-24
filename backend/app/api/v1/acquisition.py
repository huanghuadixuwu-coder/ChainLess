"""V3 acquisition API routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.pagination import paginated_response
from app.core.acquisition import api_service
from app.core.acquisition.schemas import AcquisitionProposalRequest, CredentialConnectionCreateRequest


router = APIRouter(prefix="/acquisition", tags=["acquisition"])


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=4000)


class SnoozeGapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snoozed_until: datetime


class ApproveExplorationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=255)
    strategy: str = Field(min_length=1, max_length=80)
    risk_level: str = Field(min_length=1, max_length=40)
    bounds: dict[str, Any] = Field(default_factory=dict)
    approval_id: uuid.UUID | None = None


class VerifyProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_kind: str = Field(default="contract", min_length=1, max_length=80)
    input_fixture: dict[str, Any] = Field(default_factory=dict)
    expected_result: dict[str, Any] = Field(default_factory=dict)
    actual_result: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    target_id: uuid.UUID | None = None


class ApproveActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_snapshot_hash: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=4000)


class ActivateProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_snapshot_hash: str = Field(min_length=1, max_length=128)
    verification_id: uuid.UUID | None = None
    target_ids: list[uuid.UUID] | None = None


class RotateCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_value: str | None = Field(default=None, exclude=True)
    secret_ref: str | None = None
    secret_storage_kind: str | None = None
    metadata_redacted: dict[str, Any] | None = None


def _tenant_user(current_user: dict) -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.UUID(current_user["tenant_id"]), uuid.UUID(current_user["user_id"])


async def _page_response(
    request: Request,
    rows: tuple[list[dict[str, Any]], int],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    items, total = rows
    return paginated_response(items, total, limit, offset, request)


@router.get("/gaps")
async def list_gaps(
    request: Request,
    limit: int = Query(api_service.DEFAULT_LIMIT, ge=1, le=api_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await _page_response(
        request,
        await api_service.list_gaps(db, tenant_id=tenant_id, user_id=user_id, limit=limit, offset=offset),
        limit,
        offset,
    )


@router.get("/gaps/{gap_id}")
async def get_gap(
    gap_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.get_gap(db, tenant_id=tenant_id, user_id=user_id, gap_id=gap_id)


@router.post("/gaps/{gap_id}/dismiss")
async def dismiss_gap(
    gap_id: uuid.UUID,
    body: ReasonRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.dismiss_gap(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        reason=body.reason if body else None,
    )


@router.post("/gaps/{gap_id}/snooze")
async def snooze_gap(
    gap_id: uuid.UUID,
    body: SnoozeGapRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.snooze_gap(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        snoozed_until=body.snoozed_until,
    )


@router.post("/gaps/{gap_id}/approve-exploration")
async def approve_exploration(
    gap_id: uuid.UUID,
    body: ApproveExplorationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.approve_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        source_run_id=body.source_run_id,
        strategy=body.strategy,
        risk_level=body.risk_level,
        bounds=body.bounds,
        approval_id=body.approval_id,
    )


@router.get("/explorations")
async def list_explorations(
    request: Request,
    limit: int = Query(api_service.DEFAULT_LIMIT, ge=1, le=api_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await _page_response(
        request,
        await api_service.list_explorations(db, tenant_id=tenant_id, user_id=user_id, limit=limit, offset=offset),
        limit,
        offset,
    )


@router.get("/explorations/{exploration_id}")
async def get_exploration(
    exploration_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.get_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        exploration_id=exploration_id,
    )


@router.get("/recommendations")
async def list_recommendations(
    request: Request,
    limit: int = Query(api_service.DEFAULT_LIMIT, ge=1, le=api_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await _page_response(
        request,
        await api_service.list_recommendations(db, tenant_id=tenant_id, user_id=user_id, limit=limit, offset=offset),
        limit,
        offset,
    )


@router.get("/recommendations/{recommendation_id}")
async def get_recommendation(
    recommendation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.get_recommendation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        recommendation_id=recommendation_id,
    )


@router.post(
    "/recommendations/{recommendation_id}/draft-proposal",
    status_code=status.HTTP_201_CREATED,
)
async def draft_proposal(
    recommendation_id: uuid.UUID,
    body: AcquisitionProposalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    if body.recommendation_id != recommendation_id:
        from app.api.contracts import api_error

        raise api_error(
            422,
            "RECOMMENDATION_ID_MISMATCH",
            "Path recommendation_id must match request recommendation_id",
        )
    return await api_service.draft_proposal(db, tenant_id=tenant_id, user_id=user_id, request=body)


@router.get("/proposals")
async def list_proposals(
    request: Request,
    limit: int = Query(api_service.DEFAULT_LIMIT, ge=1, le=api_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await _page_response(
        request,
        await api_service.list_proposals(db, tenant_id=tenant_id, user_id=user_id, limit=limit, offset=offset),
        limit,
        offset,
    )


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.get_proposal(db, tenant_id=tenant_id, user_id=user_id, proposal_id=proposal_id)


@router.post("/proposals/{proposal_id}/verify")
async def verify_proposal(
    proposal_id: uuid.UUID,
    body: VerifyProposalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.verify_proposal_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        verification_kind=body.verification_kind,
        input_fixture=body.input_fixture,
        expected_result=body.expected_result,
        actual_result=body.actual_result,
        artifact_refs=body.artifact_refs,
        target_id=body.target_id,
    )


@router.post("/proposals/{proposal_id}/approve-activation")
async def approve_activation(
    proposal_id: uuid.UUID,
    body: ApproveActivationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.approve_activation_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        approved_snapshot_hash=body.approved_snapshot_hash,
        reason=body.reason,
    )


@router.post("/proposals/{proposal_id}/activate")
async def activate_proposal(
    proposal_id: uuid.UUID,
    body: ActivateProposalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.activate_proposal_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        approved_snapshot_hash=body.approved_snapshot_hash,
        verification_id=body.verification_id,
        target_ids=body.target_ids,
    )


@router.post("/proposals/{proposal_id}/rollback")
async def rollback_proposal(
    proposal_id: uuid.UUID,
    body: ReasonRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.rollback_proposal_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        reason=body.reason if body else None,
    )


@router.post("/proposals/{proposal_id}/reject-activation")
async def reject_activation(
    proposal_id: uuid.UUID,
    body: ReasonRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.reject_activation_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        reason=body.reason if body else None,
    )


@router.post("/proposals/{proposal_id}/handoff-development-patch")
async def handoff_development_patch(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.handoff_development_patch_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
    )


@router.get("/runtime-planning-issues")
async def list_runtime_planning_issues(
    request: Request,
    limit: int = Query(api_service.DEFAULT_LIMIT, ge=1, le=api_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await _page_response(
        request,
        await api_service.list_runtime_planning_issues(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            limit=limit,
            offset=offset,
        ),
        limit,
        offset,
    )


@router.get("/runtime-planning-issues/{issue_id}")
async def get_runtime_planning_issue(
    issue_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.get_runtime_planning_issue(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        issue_id=issue_id,
    )


@router.post("/runtime-planning-issues/{issue_id}/dismiss")
async def dismiss_runtime_planning_issue(
    issue_id: uuid.UUID,
    body: ReasonRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.dismiss_runtime_issue_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        issue_id=issue_id,
    )


@router.post("/credential-connections", status_code=status.HTTP_201_CREATED)
async def create_credential_connection(
    body: CredentialConnectionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.create_credential_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        request=body,
    )


@router.get("/credential-connections")
async def list_credential_connections(
    request: Request,
    limit: int = Query(api_service.DEFAULT_LIMIT, ge=1, le=api_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await _page_response(
        request,
        await api_service.list_credentials(db, tenant_id=tenant_id, user_id=user_id, limit=limit, offset=offset),
        limit,
        offset,
    )


@router.get("/credential-connections/{credential_id}")
async def get_credential_connection(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.get_credential(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_id=credential_id,
    )


@router.post("/credential-connections/{credential_id}/validate")
async def validate_credential_connection(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.validate_credential_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_id=credential_id,
    )


@router.post("/credential-connections/{credential_id}/rotate")
async def rotate_credential_connection(
    credential_id: uuid.UUID,
    body: RotateCredentialRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.rotate_credential_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_id=credential_id,
        secret_value=body.secret_value,
        secret_ref=body.secret_ref,
        secret_storage_kind=body.secret_storage_kind,
        metadata_redacted=body.metadata_redacted,
    )


@router.post("/credential-connections/{credential_id}/revoke")
async def revoke_credential_connection(
    credential_id: uuid.UUID,
    body: ReasonRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.revoke_credential_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        credential_id=credential_id,
    )


@router.get("/browser-sessions")
async def list_browser_sessions(
    request: Request,
    limit: int = Query(api_service.DEFAULT_LIMIT, ge=1, le=api_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await _page_response(
        request,
        await api_service.list_browser_sessions(db, tenant_id=tenant_id, user_id=user_id, limit=limit, offset=offset),
        limit,
        offset,
    )


@router.get("/browser-sessions/{session_id}")
async def get_browser_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.get_browser_session(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )


@router.post("/browser-sessions/{session_id}/terminate")
async def terminate_browser_session(
    session_id: uuid.UUID,
    body: ReasonRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.terminate_browser_session_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        reason=body.reason if body else None,
    )


@router.get("/browser-traces/{trace_id}")
async def get_browser_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.get_browser_trace(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        trace_id=trace_id,
    )


@router.get("/permissions")
async def list_permissions(
    request: Request,
    limit: int = Query(api_service.DEFAULT_LIMIT, ge=1, le=api_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await _page_response(
        request,
        await api_service.list_permissions(db, tenant_id=tenant_id, user_id=user_id, limit=limit, offset=offset),
        limit,
        offset,
    )


@router.get("/workspace-connectors")
async def list_workspace_connectors(
    request: Request,
    limit: int = Query(api_service.DEFAULT_LIMIT, ge=1, le=api_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await _page_response(
        request,
        await api_service.list_workspace_connectors(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            limit=limit,
            offset=offset,
        ),
        limit,
        offset,
    )


@router.get("/workspace-connectors/{connector_id}")
async def get_workspace_connector(
    connector_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.get_workspace_connector(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        connector_id=connector_id,
    )


@router.post("/workspace-connectors/{connector_id}/revoke")
async def revoke_workspace_connector(
    connector_id: uuid.UUID,
    body: ReasonRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.revoke_workspace_connector_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        connector_id=connector_id,
        reason=body.reason if body else None,
    )


@router.post("/permissions/{permission_id}/revoke")
async def revoke_permission(
    permission_id: uuid.UUID,
    body: ReasonRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.revoke_permission_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        permission_id=permission_id,
        reason=body.reason if body else None,
    )


@router.post("/permissions/{permission_id}/renew")
async def renew_permission(
    permission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.renew_permission_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        permission_id=permission_id,
    )


@router.get("/journal")
async def get_acquisition_journal(
    section_limit: int | None = Query(default=None, ge=1, le=25),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return await api_service.acquisition_journal_from_api(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        section_limit=section_limit,
    )
