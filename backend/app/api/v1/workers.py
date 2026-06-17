"""Personal Worker metadata API."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.pagination import paginated_response
from app.core.workers.service import (
    activate_after_confirmation,
    count_workers,
    create_version,
    create_worker,
    disable_worker,
    enable_worker,
    get_version,
    get_worker,
    list_runs,
    list_versions,
    list_workers,
    record_match_feedback,
    request_activation,
    rollback_worker,
    serialize_feedback,
    serialize_run,
    serialize_version,
    serialize_worker,
    soft_delete_worker,
    update_worker,
    verify_version,
)
from app.core.workers.matcher import match_workers

router = APIRouter(prefix="/workers", tags=["workers"])


class WorkerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    trigger: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)


class WorkerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    trigger: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None


class VersionCreate(BaseModel):
    version: int = Field(ge=1)
    definition: dict[str, Any] = Field(default_factory=dict)
    verification_plan: dict[str, Any] = Field(default_factory=dict)


class VersionVerify(BaseModel):
    verification_evidence: dict[str, Any]


class ActivationRequest(BaseModel):
    version_id: uuid.UUID


class ActivationConfirm(BaseModel):
    version_id: uuid.UUID
    activation_token: str
    confirmation_evidence: dict[str, Any] | None = None


class RollbackRequest(BaseModel):
    version_id: uuid.UUID
    activation_token: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=4000)
    confirmation_evidence: dict[str, Any] | None = None


class WorkerMatchRequest(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    input_payload: dict[str, Any] = Field(default_factory=dict)


class WorkerFeedbackRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=50)
    source_run_id: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _tenant_user(current_user: dict) -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.UUID(current_user["tenant_id"]), uuid.UUID(current_user["user_id"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_worker_endpoint(
    body: WorkerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return serialize_worker(
        await create_worker(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name=body.name,
            description=body.description,
            trigger=body.trigger,
            policy=body.policy,
        )
    )


@router.get("")
async def list_workers_endpoint(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    total = await count_workers(db, tenant_id=tenant_id, user_id=user_id)
    rows = await list_workers(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return paginated_response([serialize_worker(row) for row in rows], total, limit, offset, request)


@router.post("/match")
async def match_workers_endpoint(
    body: WorkerMatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from app.main import app_state

    tenant_id, user_id = _tenant_user(current_user)
    decisions = await match_workers(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        request=body.request,
        input_payload=body.input_payload,
        gateway=app_state.llm_gateway,
    )
    return {
        "items": [
            {
                "worker_id": str(decision.worker_id),
                "version_id": str(decision.version_id),
                "decision": decision.decision,
                "score": decision.score,
                "semantic_score": decision.semantic_score,
                "keyword_score": decision.keyword_score,
                "reasons": decision.reasons,
            }
            for decision in decisions
        ],
        "total": len(decisions),
    }


@router.get("/{worker_id}")
async def get_worker_endpoint(
    worker_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return serialize_worker(await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id))


@router.put("/{worker_id}")
async def update_worker_endpoint(
    worker_id: uuid.UUID,
    body: WorkerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    worker = await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    return serialize_worker(
        await update_worker(
            db,
            worker,
            name=body.name,
            description=body.description,
            trigger=body.trigger,
            policy=body.policy,
        )
    )


@router.post("/{worker_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_worker_version_endpoint(
    worker_id: uuid.UUID,
    body: VersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    worker = await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    return serialize_version(
        await create_version(
            db,
            worker=worker,
            version=body.version,
            definition=body.definition,
            verification_plan=body.verification_plan,
        )
    )


@router.get("/{worker_id}/versions")
async def list_worker_versions_endpoint(
    worker_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    return {
        "items": [
            serialize_version(version)
            for version in await list_versions(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
        ]
    }


@router.post("/{worker_id}/versions/{version_id}/verify")
async def verify_worker_version_endpoint(
    worker_id: uuid.UUID,
    version_id: uuid.UUID,
    body: VersionVerify,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    version = await get_version(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        worker_id=worker_id,
        version_id=version_id,
    )
    return serialize_version(
        await verify_version(
            db,
            version=version,
            verified_by=user_id,
            verification_evidence=body.verification_evidence,
        )
    )


@router.post("/{worker_id}/request-activation")
async def request_worker_activation_endpoint(
    worker_id: uuid.UUID,
    body: ActivationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    worker = await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    version = await get_version(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        worker_id=worker_id,
        version_id=body.version_id,
    )
    return await request_activation(db, worker=worker, version=version)


@router.post("/{worker_id}/activate")
async def activate_worker_endpoint(
    worker_id: uuid.UUID,
    body: ActivationConfirm,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    worker = await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    version = await get_version(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        worker_id=worker_id,
        version_id=body.version_id,
    )
    return serialize_worker(
        await activate_after_confirmation(
            db,
            worker=worker,
            version=version,
            user_id=user_id,
            activation_token=body.activation_token,
            confirmation_evidence=body.confirmation_evidence,
        )
    )


@router.post("/{worker_id}/disable")
async def disable_worker_endpoint(
    worker_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    worker = await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    return serialize_worker(await disable_worker(db, worker))


@router.get("/{worker_id}/runs")
async def list_worker_runs_endpoint(
    worker_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    return {
        "items": [
            serialize_run(run)
            for run in await list_runs(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                worker_id=worker_id,
                limit=limit,
            )
        ]
    }


@router.post("/{worker_id}/feedback", status_code=status.HTTP_201_CREATED)
async def worker_feedback_endpoint(
    worker_id: uuid.UUID,
    body: WorkerFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    worker = await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    return serialize_feedback(
        await record_match_feedback(
            db,
            worker=worker,
            feedback=body.feedback,
            source_run_id=body.source_run_id,
            reason=body.reason,
            metadata=body.metadata,
        )
    )


@router.post("/{worker_id}/enable")
async def enable_worker_endpoint(
    worker_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    worker = await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    return serialize_worker(await enable_worker(db, worker))


@router.post("/{worker_id}/rollback")
async def rollback_worker_endpoint(
    worker_id: uuid.UUID,
    body: RollbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    worker = await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    version = await get_version(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        worker_id=worker_id,
        version_id=body.version_id,
    )
    return serialize_worker(
        await rollback_worker(
            db,
            worker=worker,
            version=version,
            user_id=user_id,
            activation_token=body.activation_token,
            reason=body.reason,
            confirmation_evidence=body.confirmation_evidence,
        )
    )


@router.delete("/{worker_id}")
async def soft_delete_worker_endpoint(
    worker_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    worker = await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
    return serialize_worker(await soft_delete_worker(db, worker))
