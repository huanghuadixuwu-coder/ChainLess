"""Conversation-scoped file upload endpoints."""

from __future__ import annotations

import mimetypes
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found, validation_error
from app.api.deps import get_current_user, get_db
from app.config import settings
from app.core.artifacts import (
    ArtifactQuotaExceededError,
    create_uploaded_artifact,
    delete_artifact_storage,
    serialize_artifact,
)
from app.models.artifact import Artifact
from app.models.conversation import Conversation

router = APIRouter(prefix="/uploads", tags=["uploads"])

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_TEXT_UPLOAD_MIME_TYPES = {
    "application/json",
    "application/javascript",
    "application/x-javascript",
    "application/xml",
    "application/x-yaml",
    "text/markdown",
}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def upload_file(
    conversation_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Upload a bounded text attachment into the managed artifact store."""
    conversation = await _get_owned_conversation(db, conversation_id, current_user)
    safe_filename = _normalize_upload_filename(file.filename or "")
    mime_type = _resolve_upload_mime_type(file.content_type, safe_filename)
    if not _is_text_upload_mime_type(mime_type):
        raise api_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_UPLOAD_TYPE",
            "Only text, markdown, JSON, XML, JavaScript, YAML, and code-like text uploads are supported",
        )

    max_bytes = int(settings.artifact_max_file_bytes)
    payload = await file.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise api_error(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "UPLOAD_TOO_LARGE",
            f"Upload exceeds {max_bytes} bytes",
        )
    _validate_upload_content_policy(payload)

    artifact: Artifact | None = None
    try:
        artifact = await create_uploaded_artifact(
            db,
            tenant_id=current_user["tenant_id"],
            conversation_id=conversation.id,
            user_id=current_user["user_id"],
            safe_filename=safe_filename,
            content=payload,
            mime_type=mime_type,
        )
        await db.commit()
        await db.refresh(artifact)
    except ArtifactQuotaExceededError:
        await db.rollback()
        raise api_error(
            status.HTTP_409_CONFLICT,
            "UPLOAD_QUOTA_EXCEEDED",
            "Tenant artifact quota exceeded",
        )
    except ValueError as exc:
        await db.rollback()
        if artifact is not None:
            delete_artifact_storage(artifact)
        message = str(exc)
        if "Binary uploads" in message:
            raise api_error(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "UNSUPPORTED_UPLOAD_TYPE",
                "Binary uploads are not supported",
            )
        if "Upload exceeds" in message:
            raise api_error(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "UPLOAD_TOO_LARGE",
                f"Upload exceeds {max_bytes} bytes",
            )
        raise validation_error(message or "Invalid upload")
    except UnicodeDecodeError:
        await db.rollback()
        if artifact is not None:
            delete_artifact_storage(artifact)
        raise api_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_UPLOAD_TYPE",
            "Uploads must be valid UTF-8 text",
        )
    except Exception:
        await db.rollback()
        if artifact is not None:
            delete_artifact_storage(artifact)
        raise

    return {"artifact": serialize_artifact(artifact)}


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


def _normalize_upload_filename(filename: str) -> str:
    raw = filename.strip()
    if (
        not raw
        or "\x00" in raw
        or "/" in raw
        or "\\" in raw
        or raw in {".", ".."}
        or raw.startswith(".")
        or ".." in raw
    ):
        raise validation_error("Unsafe upload filename")

    normalized = _SAFE_FILENAME_RE.sub("_", raw).strip("._-")
    if not normalized or normalized in {".", ".."}:
        raise validation_error("Unsafe upload filename")
    return normalized[:160]


def _resolve_upload_mime_type(content_type: str | None, filename: str) -> str:
    provided = (content_type or "").split(";", 1)[0].strip().lower()
    if provided and provided != "application/octet-stream":
        return provided
    guessed, _ = mimetypes.guess_type(filename)
    return (guessed or "application/octet-stream").lower()


def _is_text_upload_mime_type(mime_type: str) -> bool:
    if mime_type.startswith("text/"):
        return True
    return mime_type in _TEXT_UPLOAD_MIME_TYPES


def _validate_upload_content_policy(payload: bytes) -> None:
    """Content-policy hook boundary for future malware scanning."""
    if b"\x00" in payload:
        raise api_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_UPLOAD_TYPE",
            "Binary uploads are not supported",
        )
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        raise api_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_UPLOAD_TYPE",
            "Uploads must be valid UTF-8 text",
        )
