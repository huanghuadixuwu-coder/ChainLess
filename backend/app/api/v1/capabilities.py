"""Capability Candidate API contract."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.pagination import paginated_response
from app.core.capabilities.service import (
    accept_candidate as accept_candidate_service,
    as_dict,
    count_candidates,
    get_candidate,
    list_candidates,
    merge_candidate,
    transition_candidate,
)

router = APIRouter(prefix="/capability-candidates", tags=["capability-candidates"])


class SnoozeRequest(BaseModel):
    snoozed_until: datetime


class MutePatternRequest(BaseModel):
    mute_pattern: str = Field(min_length=1, max_length=255)


class MergeRequest(BaseModel):
    target_candidate_id: uuid.UUID
    merge_reason: str | None = Field(default=None, max_length=4000)


class EditedProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    body: str | None = Field(default=None, max_length=8000)
    content: str | None = Field(default=None, max_length=8000)
    description: str | None = Field(default=None, max_length=4000)
    memory_type: str | None = Field(default=None, min_length=1, max_length=50)
    tags: list[str] | None = Field(default=None, max_length=50)
    trigger_terms: list[str] | None = Field(default=None, max_length=100)
    trigger: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    definition: dict[str, Any] | None = None
    verification_plan: dict[str, Any] | None = None

    @field_validator("tags", "trigger_terms")
    @classmethod
    def _bounded_string_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("entries must be strings")
            normalized = " ".join(item.strip().split())
            if not normalized:
                continue
            if len(normalized) > 120:
                raise ValueError("entries must be 120 characters or less")
            cleaned.append(normalized)
        return cleaned


class AcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edited_proposal: EditedProposal | None = None


def _tenant_user(current_user: dict) -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.UUID(current_user["tenant_id"]), uuid.UUID(current_user["user_id"])


@router.get("")
async def list_capability_candidates(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    total = await count_candidates(db, tenant_id=tenant_id, user_id=user_id)
    rows = await list_candidates(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return paginated_response([as_dict(row) for row in rows], total, limit, offset, request)


@router.get("/{candidate_id}")
async def get_capability_candidate(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return as_dict(
        await get_candidate(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_id=candidate_id,
        )
    )


@router.post("/{candidate_id}/accept")
async def accept_candidate(
    candidate_id: uuid.UUID,
    body: AcceptRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return as_dict(
        await accept_candidate_service(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_id=candidate_id,
            edited_proposal=body.edited_proposal.model_dump(exclude_none=True)
            if body and body.edited_proposal
            else None,
        )
    )


@router.post("/{candidate_id}/dismiss")
async def dismiss_candidate(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return as_dict(
        await transition_candidate(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_id=candidate_id,
            status="dismissed",
        )
    )


@router.post("/{candidate_id}/snooze")
async def snooze_candidate(
    candidate_id: uuid.UUID,
    body: SnoozeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return as_dict(
        await transition_candidate(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_id=candidate_id,
            status="snoozed",
            snoozed_until=body.snoozed_until,
        )
    )


@router.post("/{candidate_id}/archive")
async def archive_candidate(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return as_dict(
        await transition_candidate(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_id=candidate_id,
            status="archived",
        )
    )


@router.post("/{candidate_id}/mute-pattern")
async def mute_candidate_pattern(
    candidate_id: uuid.UUID,
    body: MutePatternRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return as_dict(
        await transition_candidate(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_id=candidate_id,
            status="muted_pattern",
            mute_pattern=body.mute_pattern,
        )
    )


@router.post("/{candidate_id}/merge")
async def merge_candidate_endpoint(
    candidate_id: uuid.UUID,
    body: MergeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tenant_id, user_id = _tenant_user(current_user)
    return as_dict(
        await merge_candidate(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_id=candidate_id,
            target_candidate_id=body.target_candidate_id,
            merge_reason=body.merge_reason,
        )
    )
