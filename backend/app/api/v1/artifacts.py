"""Conversation-scoped artifact APIs."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found, validation_error
from app.api.deps import get_current_user, get_db
from app.api.pagination import paginated_response
from app.core.artifacts.service import (
    ARTIFACT_STATE_AVAILABLE,
    artifact_preview_contract,
    cleanup_expired_artifacts,
    read_artifact_content,
    serialize_artifact,
)
from app.models.artifact import Artifact
from app.models.conversation import Conversation

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/")
async def list_artifacts(
    conversation_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List artifacts visible to the current user for one conversation."""
    _validate_page(limit, offset, max_limit=100)
    tenant_id = uuid.UUID(current_user["tenant_id"])
    await _get_owned_conversation(db, conversation_id, current_user)
    await cleanup_expired_artifacts(db, tenant_id=tenant_id)

    filters = [
        Artifact.tenant_id == tenant_id,
        Artifact.conversation_id == conversation_id,
    ]
    total = (
        await db.execute(select(func.count()).select_from(Artifact).where(*filters))
    ).scalar_one()
    rows = (
        await db.execute(
            select(Artifact)
            .where(*filters)
            .order_by(Artifact.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return paginated_response(
        [serialize_artifact(row) for row in rows],
        total,
        limit,
        offset,
        request,
    )


@router.get("/{artifact_id}")
async def get_artifact(
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return one artifact metadata record."""
    artifact = await _get_owned_artifact(db, artifact_id, current_user)
    return serialize_artifact(artifact)


@router.get("/{artifact_id}/content")
async def get_artifact_content(
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return stored text content for safe in-app preview."""
    artifact = await _get_owned_artifact(db, artifact_id, current_user)
    return await _artifact_payload(db, artifact, "content")


@router.get("/{artifact_id}/diff")
async def get_artifact_diff(
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return stored unified diff for the artifact."""
    artifact = await _get_owned_artifact(db, artifact_id, current_user)
    return await _artifact_payload(db, artifact, "diff")


async def _artifact_payload(db: AsyncSession, artifact: Artifact, content_kind: str) -> dict:
    if artifact.state != ARTIFACT_STATE_AVAILABLE:
        raise api_error(
            409,
            "ARTIFACT_NOT_PREVIEWABLE",
            f"Artifact is {artifact.state}",
        )
    if content_kind == "content":
        preview = artifact_preview_contract(artifact)
        if not preview.get("allowed") or preview.get("mode") not in {"code", "text"}:
            raise api_error(
                409,
                "ARTIFACT_NOT_PREVIEWABLE",
                str(preview.get("reason") or preview.get("mode") or "Artifact content is not previewable"),
            )
    try:
        content = await read_artifact_content(artifact, content_kind=content_kind)
    except PermissionError:
        raise api_error(403, "ARTIFACT_STORAGE_FORBIDDEN", "Artifact storage path is forbidden")
    except FileNotFoundError:
        await db.commit()
        raise not_found("ARTIFACT_CONTENT_NOT_FOUND", "Artifact content not found")

    return {
        "artifact": serialize_artifact(artifact),
        "kind": content_kind,
        "content": content,
    }


async def _get_owned_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    current_user: dict,
) -> Conversation:
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == uuid.UUID(current_user["tenant_id"]),
                Conversation.user_id == uuid.UUID(current_user["user_id"]),
                Conversation.status != "archived",
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise not_found("CONVERSATION_NOT_FOUND", "Conversation not found")
    return conversation


async def _get_owned_artifact(
    db: AsyncSession,
    artifact_id: uuid.UUID,
    current_user: dict,
) -> Artifact:
    artifact = (
        await db.execute(
            select(Artifact)
            .join(Conversation, Artifact.conversation_id == Conversation.id)
            .where(
                Artifact.id == artifact_id,
                Artifact.tenant_id == uuid.UUID(current_user["tenant_id"]),
                Conversation.user_id == uuid.UUID(current_user["user_id"]),
                Conversation.status != "archived",
            )
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise not_found("ARTIFACT_NOT_FOUND", "Artifact not found")
    return artifact


def _validate_page(limit: int, offset: int, *, max_limit: int) -> None:
    if limit < 1 or limit > max_limit or offset < 0:
        raise validation_error("Invalid pagination parameters")
