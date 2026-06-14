"""Tenant-scoped artifact metadata and bounded file storage."""

from __future__ import annotations

import difflib
import hashlib
import mimetypes
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.artifact import Artifact


ARTIFACT_STATE_AVAILABLE = "available"
ARTIFACT_STATE_OVERSIZED = "oversized"
ARTIFACT_STATE_QUOTA_EXCEEDED = "quota_exceeded"
ARTIFACT_STATE_MISSING = "missing"
ARTIFACT_STATE_DELETED = "deleted"


@dataclass
class ToolExecutionResult:
    """Tool output plus optional artifact references for public SSE metadata."""

    content: str
    artifacts: list[dict] = field(default_factory=list)


class ArtifactQuotaExceededError(RuntimeError):
    """Raised when a new artifact would exceed tenant managed-storage quota."""


def serialize_artifact(artifact: Artifact) -> dict:
    """Return a stable public artifact metadata contract."""
    metadata = artifact.meta_data or {}
    return {
        "id": str(artifact.id),
        "tenant_id": str(artifact.tenant_id),
        "conversation_id": str(artifact.conversation_id),
        "run_id": artifact.run_id,
        "tool_call_id": artifact.tool_call_id,
        "type": artifact.artifact_type,
        "operation": artifact.operation,
        "path": artifact.workspace_path,
        "state": artifact.state,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "content_bytes_stored": artifact.content_bytes_stored,
        "diff_bytes_stored": artifact.diff_bytes_stored,
        "has_content": bool(artifact.content_path),
        "has_diff": bool(artifact.diff_path),
        "before_sha256": artifact.before_sha256,
        "after_sha256": artifact.after_sha256,
        "preview": _preview_contract(artifact),
        "metadata": {
            key: value
            for key, value in metadata.items()
            if key not in {"content_path", "diff_path"}
        },
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
        "expires_at": artifact.expires_at.isoformat() if artifact.expires_at else None,
    }


def artifact_preview_contract(artifact: Artifact) -> dict:
    """Expose the backend-owned preview decision for API enforcement."""
    return _preview_contract(artifact)


async def capture_file_write_artifact(
    *,
    tenant_id: str | uuid.UUID | None,
    conversation_id: str | uuid.UUID | None,
    user_id: str | uuid.UUID | None,
    run_id: str | None,
    tool_call_id: str | None,
    workspace_path: str,
    before_content: str | None,
    after_content: str,
) -> list[dict]:
    """Persist metadata and bounded content/diff for one workspace write."""
    if not tenant_id or not conversation_id:
        return []

    from app.api.deps import _async_session_factory

    async with _async_session_factory() as db:
        await cleanup_expired_artifacts(db, commit=False)
        artifact: Artifact | None = None
        try:
            artifact = await _create_file_write_artifact(
                db,
                tenant_id=uuid.UUID(str(tenant_id)),
                conversation_id=uuid.UUID(str(conversation_id)),
                user_id=uuid.UUID(str(user_id)) if user_id else None,
                run_id=run_id,
                tool_call_id=tool_call_id,
                workspace_path=workspace_path,
                before_content=before_content,
                after_content=after_content,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            if artifact is not None:
                _delete_artifact_files(artifact)
            raise
        await db.refresh(artifact)
        return [serialize_artifact(artifact)]


async def create_uploaded_artifact(
    db: AsyncSession,
    *,
    tenant_id: str | uuid.UUID,
    conversation_id: str | uuid.UUID,
    user_id: str | uuid.UUID,
    safe_filename: str,
    content: bytes,
    mime_type: str,
) -> Artifact:
    """Persist a user-uploaded text attachment as a conversation artifact."""
    _assert_upload_artifact_inputs(safe_filename, content)
    tenant_uuid = uuid.UUID(str(tenant_id))
    requested_storage_bytes = len(content)
    await _lock_tenant_artifact_quota(db, tenant_uuid)
    if requested_storage_bytes and await _tenant_storage_would_exceed_quota(
        db,
        tenant_uuid,
        requested_storage_bytes,
    ):
        raise ArtifactQuotaExceededError("Tenant artifact quota exceeded")

    now = datetime.now(timezone.utc)
    artifact = Artifact(
        tenant_id=tenant_uuid,
        conversation_id=uuid.UUID(str(conversation_id)),
        user_id=uuid.UUID(str(user_id)),
        artifact_type="file",
        operation="upload",
        workspace_path=f"uploads/{safe_filename}",
        state=ARTIFACT_STATE_AVAILABLE,
        mime_type=mime_type,
        size_bytes=len(content),
        content_bytes_stored=len(content),
        diff_bytes_stored=0,
        before_sha256=None,
        after_sha256=_sha256(content),
        expires_at=now + timedelta(days=int(settings.artifact_retention_days)),
        meta_data={
            "retention_days": settings.artifact_retention_days,
            "file_size_limit_bytes": settings.artifact_max_file_bytes,
            "content_policy": "text_upload_v1",
        },
    )
    db.add(artifact)
    await db.flush()

    artifact_dir = _artifact_dir(artifact)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact.content_path = _write_storage_file(
        artifact_dir,
        "content.txt",
        content,
    )
    return artifact


def delete_artifact_storage(artifact: Artifact) -> None:
    """Delete managed files for an artifact row without mutating the row."""
    _delete_artifact_files(artifact)


async def cleanup_expired_artifacts(
    db: AsyncSession,
    *,
    tenant_id: str | uuid.UUID | None = None,
    commit: bool = True,
) -> int:
    """Delete expired artifact rows and their managed storage files."""
    now = datetime.now(timezone.utc)
    filters = [Artifact.expires_at.is_not(None), Artifact.expires_at <= now]
    if tenant_id is not None:
        filters.append(Artifact.tenant_id == uuid.UUID(str(tenant_id)))

    rows = (await db.execute(select(Artifact).where(*filters))).scalars().all()
    for artifact in rows:
        _delete_artifact_files(artifact)
        await db.delete(artifact)
    if commit and rows:
        await db.commit()
    return len(rows) + await cleanup_orphaned_artifact_files(db, tenant_id=tenant_id)


async def cleanup_orphaned_artifact_files(
    db: AsyncSession,
    *,
    tenant_id: str | uuid.UUID | None = None,
) -> int:
    """Remove managed storage directories that no live artifact row owns."""
    root = _artifact_root()
    tenant_filter = uuid.UUID(str(tenant_id)) if tenant_id is not None else None
    query = select(Artifact.id)
    if tenant_filter is not None:
        query = query.where(Artifact.tenant_id == tenant_filter)
    live_ids = {str(row[0]) for row in (await db.execute(query)).all()}

    removed = 0
    for tenant_dir in _iter_dirs(root):
        if tenant_filter is not None and tenant_dir.name != str(tenant_filter):
            continue
        for conversation_dir in _iter_dirs(tenant_dir):
            for artifact_dir in _iter_dirs(conversation_dir):
                if artifact_dir.name not in live_ids:
                    shutil.rmtree(artifact_dir, ignore_errors=True)
                    removed += 1
            _remove_empty_dir(conversation_dir)
        _remove_empty_dir(tenant_dir)
    return removed


async def delete_artifacts_for_conversation(
    db: AsyncSession,
    *,
    tenant_id: str | uuid.UUID,
    conversation_id: str | uuid.UUID,
) -> int:
    """Remove managed artifact storage before a conversation is purged."""
    rows = (
        await db.execute(
            select(Artifact).where(
                Artifact.tenant_id == uuid.UUID(str(tenant_id)),
                Artifact.conversation_id == uuid.UUID(str(conversation_id)),
            )
        )
    ).scalars().all()
    for artifact in rows:
        _delete_artifact_files(artifact)
    if rows:
        await db.execute(
            delete(Artifact).where(
                Artifact.tenant_id == uuid.UUID(str(tenant_id)),
                Artifact.conversation_id == uuid.UUID(str(conversation_id)),
            )
        )
    return len(rows)


async def read_artifact_content(artifact: Artifact, *, content_kind: str) -> str:
    """Read stored content or diff from the managed artifact volume."""
    relative_path = artifact.content_path if content_kind == "content" else artifact.diff_path
    if not relative_path:
        raise FileNotFoundError(f"Artifact {content_kind} is not stored")
    path = _safe_storage_path(relative_path)
    if not path.is_file():
        artifact.state = ARTIFACT_STATE_MISSING
        raise FileNotFoundError(f"Artifact {content_kind} is missing")
    return path.read_text(encoding="utf-8")


async def _create_file_write_artifact(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    run_id: str | None,
    tool_call_id: str | None,
    workspace_path: str,
    before_content: str | None,
    after_content: str,
) -> Artifact:
    now = datetime.now(timezone.utc)
    max_file_bytes = int(settings.artifact_max_file_bytes)
    max_diff_bytes = int(settings.artifact_max_diff_bytes)
    after_bytes = after_content.encode("utf-8")
    before_bytes = before_content.encode("utf-8") if before_content is not None else b""
    diff_text = _unified_diff(workspace_path, before_content, after_content)
    diff_bytes = diff_text.encode("utf-8")
    storage_content = after_bytes
    storage_diff = diff_bytes
    state = ARTIFACT_STATE_AVAILABLE
    metadata = {
        "before_exists": before_content is not None,
        "retention_days": settings.artifact_retention_days,
        "file_size_limit_bytes": max_file_bytes,
        "diff_size_limit_bytes": max_diff_bytes,
    }

    await _lock_tenant_artifact_quota(db, tenant_id)

    if len(after_bytes) > max_file_bytes:
        state = ARTIFACT_STATE_OVERSIZED
        storage_content = b""
        storage_diff = b""
        metadata["content_omitted_reason"] = "file_size_limit_exceeded"
    elif len(diff_bytes) > max_diff_bytes:
        storage_diff = _truncate_utf8(diff_text, max_diff_bytes)
        metadata["diff_truncated"] = True

    requested_storage_bytes = len(storage_content) + len(storage_diff)
    if requested_storage_bytes and await _tenant_storage_would_exceed_quota(
        db,
        tenant_id,
        requested_storage_bytes,
    ):
        state = ARTIFACT_STATE_QUOTA_EXCEEDED
        storage_content = b""
        storage_diff = b""
        metadata["content_omitted_reason"] = "tenant_quota_exceeded"
        metadata["tenant_quota_bytes"] = settings.artifact_tenant_quota_bytes

    artifact = Artifact(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        user_id=user_id,
        run_id=run_id,
        tool_call_id=tool_call_id,
        artifact_type="file",
        operation="write" if before_content is None else "modify",
        workspace_path=_normalize_workspace_path(workspace_path),
        state=state,
        mime_type=_guess_mime_type(workspace_path),
        size_bytes=len(after_bytes),
        content_bytes_stored=len(storage_content),
        diff_bytes_stored=len(storage_diff),
        before_sha256=_sha256(before_bytes) if before_content is not None else None,
        after_sha256=_sha256(after_bytes),
        expires_at=now + timedelta(days=int(settings.artifact_retention_days)),
        meta_data=metadata,
    )
    db.add(artifact)
    await db.flush()

    if storage_content or storage_diff:
        artifact_dir = _artifact_dir(artifact)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        if storage_content:
            artifact.content_path = _write_storage_file(
                artifact_dir,
                "content.txt",
                storage_content,
            )
        if storage_diff:
            artifact.diff_path = _write_storage_file(
                artifact_dir,
                "diff.patch",
                storage_diff,
            )
    return artifact


async def _tenant_storage_would_exceed_quota(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    requested_bytes: int,
) -> bool:
    quota = int(settings.artifact_tenant_quota_bytes)
    if quota <= 0:
        return False
    current = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(Artifact.content_bytes_stored + Artifact.diff_bytes_stored),
                    0,
                )
            ).where(Artifact.tenant_id == tenant_id)
        )
    ).scalar_one()
    return int(current or 0) + requested_bytes > quota


async def _lock_tenant_artifact_quota(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Serialize quota decisions per tenant inside the current DB transaction."""
    await db.execute(
        text("select pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"artifact-quota:{tenant_id}"},
    )


def _assert_upload_artifact_inputs(safe_filename: str, content: bytes) -> None:
    if (
        not safe_filename
        or "/" in safe_filename
        or "\\" in safe_filename
        or safe_filename in {".", ".."}
        or ".." in safe_filename
    ):
        raise ValueError("Unsafe upload filename")
    if len(content) > int(settings.artifact_max_file_bytes):
        raise ValueError("Upload exceeds artifact file size limit")
    if b"\x00" in content:
        raise ValueError("Binary uploads are not supported")
    content.decode("utf-8")


def _unified_diff(path: str, before: str | None, after: str) -> str:
    before_lines = (before or "").splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff_lines = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=f"a/{_normalize_workspace_path(path)}",
        tofile=f"b/{_normalize_workspace_path(path)}",
    )
    return "".join(diff_lines)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_workspace_path(path: str) -> str:
    value = path.replace("\\", "/").lstrip("/")
    return value or "."


def _guess_mime_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "text/plain"


def _artifact_root() -> Path:
    root = Path(settings.artifact_base_path)
    if not root.is_absolute():
        raise RuntimeError("Artifact base path must be absolute")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _artifact_dir(artifact: Artifact) -> Path:
    return _artifact_root() / str(artifact.tenant_id) / str(artifact.conversation_id) / str(artifact.id)


def _write_storage_file(directory: Path, name: str, data: bytes) -> str:
    path = directory / name
    path.write_bytes(data)
    return os.path.relpath(path, _artifact_root())


def _truncate_utf8(text: str, max_bytes: int) -> bytes:
    if max_bytes <= 0:
        return b""
    marker = "\n[diff truncated]\n"
    budget = max_bytes - len(marker.encode("utf-8"))
    if budget <= 0:
        return marker.encode("utf-8")[:max_bytes]
    selected: list[str] = []
    used = 0
    for char in text:
        encoded = char.encode("utf-8")
        if used + len(encoded) > budget:
            break
        selected.append(char)
        used += len(encoded)
    return ("".join(selected) + marker).encode("utf-8")


def _safe_storage_path(relative_path: str) -> Path:
    root = _artifact_root()
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise PermissionError("Artifact storage path escaped managed root")
    return candidate


def _delete_artifact_files(artifact: Artifact) -> None:
    for relative in (artifact.content_path, artifact.diff_path):
        if relative:
            try:
                path = _safe_storage_path(relative)
                if path.is_file():
                    path.unlink()
            except FileNotFoundError:
                pass
    try:
        directory = _artifact_dir(artifact)
        if directory.exists():
            shutil.rmtree(directory)
    except FileNotFoundError:
        pass


def _iter_dirs(path: Path):
    if not path.exists():
        return []
    return [child for child in path.iterdir() if child.is_dir()]


def _remove_empty_dir(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def _preview_contract(artifact: Artifact) -> dict:
    metadata = artifact.meta_data or {}
    preview_url = str(metadata.get("preview_url") or "")
    if preview_url:
        origin = _origin(preview_url)
        if origin in _allowed_preview_origins():
            return {"mode": "iframe", "allowed": True, "url": preview_url}
        return {"mode": "blocked", "allowed": False, "reason": "preview_url_not_allowlisted"}

    mime_type = artifact.mime_type or ""
    if artifact.state != ARTIFACT_STATE_AVAILABLE:
        return {"mode": artifact.state, "allowed": False, "reason": artifact.state}
    if mime_type.startswith("text/") or mime_type in {
        "application/json",
        "application/javascript",
        "application/x-javascript",
        "application/xml",
    }:
        return {
            "mode": "code" if _looks_like_code(artifact.workspace_path) else "text",
            "allowed": True,
        }
    if mime_type.startswith("image/"):
        return {"mode": "image", "allowed": True}
    return {"mode": "blocked", "allowed": False, "reason": "mime_type_not_previewable"}


def _allowed_preview_origins() -> set[str]:
    return {
        origin.strip().rstrip("/")
        for origin in settings.artifact_preview_allowed_origins.split(",")
        if origin.strip()
    }


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _looks_like_code(path: str) -> bool:
    return Path(path).suffix.lower() in {
        ".c",
        ".cpp",
        ".css",
        ".go",
        ".html",
        ".java",
        ".js",
        ".json",
        ".md",
        ".py",
        ".rs",
        ".sh",
        ".sql",
        ".ts",
        ".tsx",
        ".yaml",
        ".yml",
    }
