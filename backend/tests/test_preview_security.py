"""Artifact preview and storage safety tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.config import settings
from app.core.artifacts import capture_file_write_artifact, cleanup_orphaned_artifact_files
from app.models.artifact import Artifact
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


async def _conversation_scope(
    client: AsyncClient,
    headers: dict[str, str],
) -> tuple[str, str, str]:
    created = await client.post(
        "/api/v1/conversations/",
        headers=headers,
        json={"title": "preview-security"},
    )
    assert created.status_code == 200, created.text
    token = headers["Authorization"].split(" ", 1)[1]
    payload = decode_token(token)
    return created.json()["id"], payload["tenant_id"], payload["user_id"]


async def _insert_artifact(
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    state: str = "available",
    mime_type: str = "text/plain",
    content_path: str | None = None,
    diff_path: str | None = None,
    metadata: dict | None = None,
) -> uuid.UUID:
    async with _async_session_factory() as db:
        artifact = Artifact(
            tenant_id=uuid.UUID(tenant_id),
            conversation_id=uuid.UUID(conversation_id),
            user_id=uuid.UUID(user_id),
            artifact_type="file",
            operation="write",
            workspace_path=f"w6/{uuid.uuid4().hex}.txt",
            state=state,
            mime_type=mime_type,
            size_bytes=1,
            content_bytes_stored=1 if content_path else 0,
            diff_bytes_stored=1 if diff_path else 0,
            content_path=content_path,
            diff_path=diff_path,
            after_sha256="0" * 64,
            meta_data=metadata or {},
        )
        db.add(artifact)
        await db.commit()
        return artifact.id


async def test_preview_url_is_strictly_allowlisted(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    conv_id, tenant_id, user_id = await _conversation_scope(client, tenant_a_headers)
    unsafe_id = await _insert_artifact(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conv_id,
        mime_type="text/html",
        metadata={"preview_url": "https://evil.example/app"},
    )
    safe_id = await _insert_artifact(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conv_id,
        mime_type="text/html",
        metadata={"preview_url": "http://localhost:3000/app"},
    )

    unsafe = await client.get(f"/api/v1/artifacts/{unsafe_id}", headers=tenant_a_headers)
    safe = await client.get(f"/api/v1/artifacts/{safe_id}", headers=tenant_a_headers)

    assert unsafe.status_code == 200
    assert unsafe.json()["preview"] == {
        "mode": "blocked",
        "allowed": False,
        "reason": "preview_url_not_allowlisted",
    }
    assert safe.status_code == 200
    assert safe.json()["preview"]["mode"] == "iframe"
    assert safe.json()["preview"]["allowed"] is True


async def test_storage_path_escape_is_forbidden(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    conv_id, tenant_id, user_id = await _conversation_scope(client, tenant_a_headers)
    artifact_id = await _insert_artifact(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conv_id,
        content_path="../outside.txt",
    )

    response = await client.get(
        f"/api/v1/artifacts/{artifact_id}/content",
        headers=tenant_a_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ARTIFACT_STORAGE_FORBIDDEN"


async def test_missing_content_returns_not_found_and_marks_state(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    conv_id, tenant_id, user_id = await _conversation_scope(client, tenant_a_headers)
    artifact_id = await _insert_artifact(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conv_id,
        content_path="missing-content.txt",
    )

    response = await client.get(
        f"/api/v1/artifacts/{artifact_id}/content",
        headers=tenant_a_headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ARTIFACT_CONTENT_NOT_FOUND"
    async with _async_session_factory() as db:
        artifact = (
            await db.execute(select(Artifact).where(Artifact.id == artifact_id))
        ).scalar_one()
    assert artifact.state == "missing"


async def test_binary_and_oversized_artifacts_are_not_previewed(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conv_id, tenant_id, user_id = await _conversation_scope(client, tenant_a_headers)
    binary_id = await _insert_artifact(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conv_id,
        mime_type="application/octet-stream",
    )
    monkeypatch.setattr(settings, "artifact_max_file_bytes", 4)
    refs = await capture_file_write_artifact(
        tenant_id=tenant_id,
        conversation_id=conv_id,
        user_id=user_id,
        run_id="oversized-run",
        tool_call_id="oversized-call",
        workspace_path="w6/oversized.txt",
        before_content=None,
        after_content="too large",
    )

    binary = await client.get(f"/api/v1/artifacts/{binary_id}", headers=tenant_a_headers)
    oversized_content = await client.get(
        f"/api/v1/artifacts/{refs[0]['id']}/content",
        headers=tenant_a_headers,
    )

    assert binary.status_code == 200
    assert binary.json()["preview"] == {
        "mode": "blocked",
        "allowed": False,
        "reason": "mime_type_not_previewable",
    }
    assert refs[0]["state"] == "oversized"
    assert oversized_content.status_code == 409
    assert oversized_content.json()["error"]["code"] == "ARTIFACT_NOT_PREVIEWABLE"


async def test_tenant_quota_records_metadata_without_storing_content(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conv_id, tenant_id, user_id = await _conversation_scope(client, tenant_a_headers)
    monkeypatch.setattr(settings, "artifact_tenant_quota_bytes", 1)

    refs = await capture_file_write_artifact(
        tenant_id=tenant_id,
        conversation_id=conv_id,
        user_id=user_id,
        run_id="quota-run",
        tool_call_id="quota-call",
        workspace_path="w6/quota.txt",
        before_content=None,
        after_content="quota",
    )

    artifact = await client.get(f"/api/v1/artifacts/{refs[0]['id']}", headers=tenant_a_headers)
    content = await client.get(
        f"/api/v1/artifacts/{refs[0]['id']}/content",
        headers=tenant_a_headers,
    )

    assert artifact.status_code == 200
    assert artifact.json()["state"] == "quota_exceeded"
    assert artifact.json()["has_content"] is False
    assert content.status_code == 409


async def test_blocked_preview_url_cannot_read_content(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(settings, "artifact_base_path", str(tmp_path))
    conv_id, tenant_id, user_id = await _conversation_scope(client, tenant_a_headers)
    stored = tmp_path / "blocked" / "content.txt"
    stored.parent.mkdir(parents=True)
    stored.write_text("<script>unsafe()</script>", encoding="utf-8")
    artifact_id = await _insert_artifact(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conv_id,
        mime_type="text/html",
        content_path="blocked/content.txt",
        metadata={"preview_url": "https://evil.example/app"},
    )

    response = await client.get(
        f"/api/v1/artifacts/{artifact_id}/content",
        headers=tenant_a_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ARTIFACT_NOT_PREVIEWABLE"


async def test_orphaned_managed_artifact_directories_are_cleaned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(settings, "artifact_base_path", str(tmp_path))
    orphan_dir = tmp_path / str(uuid.uuid4()) / str(uuid.uuid4()) / str(uuid.uuid4())
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "content.txt").write_text("orphan", encoding="utf-8")

    async with _async_session_factory() as db:
        removed = await cleanup_orphaned_artifact_files(db)

    assert removed == 1
    assert not orphan_dir.exists()


async def test_diff_truncation_preserves_utf8_boundaries(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conv_id, tenant_id, user_id = await _conversation_scope(client, tenant_a_headers)
    monkeypatch.setattr(settings, "artifact_max_file_bytes", 10000)
    monkeypatch.setattr(settings, "artifact_max_diff_bytes", 80)
    refs = await capture_file_write_artifact(
        tenant_id=tenant_id,
        conversation_id=conv_id,
        user_id=user_id,
        run_id="utf8-run",
        tool_call_id="utf8-call",
        workspace_path="w6/utf8.txt",
        before_content=None,
        after_content="你好世界\n" * 100,
    )

    response = await client.get(
        f"/api/v1/artifacts/{refs[0]['id']}/diff",
        headers=tenant_a_headers,
    )

    assert response.status_code == 200, response.text
    assert "[diff truncated]" in response.json()["content"]
