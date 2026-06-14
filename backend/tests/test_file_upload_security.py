"""Conversation-scoped upload security and artifact contract tests."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.config import settings
from app.main import app_state
from app.models.artifact import Artifact

pytestmark = pytest.mark.asyncio


async def _create_conversation(
    client: AsyncClient,
    headers: dict[str, str],
    title: str = "upload-security",
) -> str:
    response = await client.post(
        "/api/v1/conversations/",
        headers=headers,
        json={"title": title},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_text_upload_creates_conversation_artifact(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)

    response = await client.post(
        "/api/v1/uploads/",
        headers=tenant_a_headers,
        data={"conversation_id": conversation_id},
        files={"file": ("notes one.txt", b"hello upload\n", "text/plain")},
    )

    assert response.status_code == 201, response.text
    artifact = response.json()["artifact"]
    assert artifact["conversation_id"] == conversation_id
    assert artifact["operation"] == "upload"
    assert artifact["path"].startswith("uploads/")
    assert artifact["path"].endswith("notes_one.txt")
    assert artifact["state"] == "available"
    assert artifact["has_content"] is True
    assert artifact["has_diff"] is False
    assert artifact["preview"]["allowed"] is True

    content = await client.get(
        f"/api/v1/artifacts/{artifact['id']}/content",
        headers=tenant_a_headers,
    )
    assert content.status_code == 200, content.text
    assert content.json()["content"] == "hello upload\n"


async def test_chat_attachment_is_validated_and_injected_into_llm_context(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)
    uploaded = await client.post(
        "/api/v1/uploads/",
        headers=tenant_a_headers,
        data={"conversation_id": conversation_id},
        files={"file": ("notes.txt", b"attached fact: blue comet\n", "text/plain")},
    )
    artifact_id = uploaded.json()["artifact"]["id"]
    observed_messages: list[list[dict]] = []

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            observed_messages.append(messages)
            yield {"type": "text", "content": "attachment seen"}

    monkeypatch.setattr(app_state, "llm_gateway", Gateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/chat",
        headers=tenant_a_headers,
        json={
            "content": "Use the attached file.",
            "attachment_artifact_ids": [artifact_id],
        },
    )

    assert response.status_code == 200, response.text
    joined = "\n".join(str(message.get("content", "")) for message in observed_messages[0])
    assert "attached fact: blue comet" in joined
    assert "Attachment artifact" in joined


async def test_deleted_historical_attachment_is_not_reinjected_into_later_context(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)
    uploaded = await client.post(
        "/api/v1/uploads/",
        headers=tenant_a_headers,
        data={"conversation_id": conversation_id},
        files={"file": ("notes.txt", b"retired fact: green comet\n", "text/plain")},
    )
    artifact_id = uploaded.json()["artifact"]["id"]
    observed_messages: list[list[dict]] = []

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            observed_messages.append(messages)
            yield {"type": "text", "content": "ok"}

    monkeypatch.setattr(app_state, "llm_gateway", Gateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())

    first = await client.post(
        f"/api/v1/conversations/{conversation_id}/chat",
        headers=tenant_a_headers,
        json={
            "content": "Use the attached file.",
            "attachment_artifact_ids": [artifact_id],
        },
    )
    assert first.status_code == 200, first.text
    first_context = "\n".join(
        str(message.get("content", "")) for message in observed_messages[0]
    )
    assert "retired fact: green comet" in first_context

    async with _async_session_factory() as db:
        artifact = (
            await db.execute(select(Artifact).where(Artifact.id == uuid.UUID(artifact_id)))
        ).scalar_one()
        artifact.state = "deleted"
        await db.commit()

    second = await client.post(
        f"/api/v1/conversations/{conversation_id}/chat",
        headers=tenant_a_headers,
        json={"content": "Continue without attachments."},
    )
    assert second.status_code == 200, second.text
    second_context = "\n".join(
        str(message.get("content", "")) for message in observed_messages[1]
    )
    assert "retired fact: green comet" not in second_context
    assert "Attachment artifact" not in second_context


async def test_upload_rejects_foreign_conversation(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)

    response = await client.post(
        "/api/v1/uploads/",
        headers=tenant_b_headers,
        data={"conversation_id": conversation_id},
        files={"file": ("notes.txt", b"private\n", "text/plain")},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def test_chat_rejects_foreign_or_wrong_conversation_attachment_ids(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    conversation_a = await _create_conversation(client, tenant_a_headers, "upload-a")
    conversation_b = await _create_conversation(client, tenant_b_headers, "upload-b")
    conversation_a2 = await _create_conversation(client, tenant_a_headers, "upload-a2")
    uploaded = await client.post(
        "/api/v1/uploads/",
        headers=tenant_a_headers,
        data={"conversation_id": conversation_a},
        files={"file": ("notes.txt", b"tenant-private\n", "text/plain")},
    )
    artifact_id = uploaded.json()["artifact"]["id"]

    foreign = await client.post(
        f"/api/v1/conversations/{conversation_b}/chat",
        headers=tenant_b_headers,
        json={"content": "use it", "attachment_artifact_ids": [artifact_id]},
    )
    wrong_conversation = await client.post(
        f"/api/v1/conversations/{conversation_a2}/chat",
        headers=tenant_a_headers,
        json={"content": "use it", "attachment_artifact_ids": [artifact_id]},
    )

    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"
    assert wrong_conversation.status_code == 404
    assert wrong_conversation.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"


async def test_chat_rejects_unavailable_attachment_artifact(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)
    uploaded = await client.post(
        "/api/v1/uploads/",
        headers=tenant_a_headers,
        data={"conversation_id": conversation_id},
        files={"file": ("notes.txt", b"soon unavailable\n", "text/plain")},
    )
    artifact_id = uploaded.json()["artifact"]["id"]
    async with _async_session_factory() as db:
        artifact = (
            await db.execute(select(Artifact).where(Artifact.id == uuid.UUID(artifact_id)))
        ).scalar_one()
        artifact.state = "deleted"
        await db.commit()

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/chat",
        headers=tenant_a_headers,
        json={"content": "use it", "attachment_artifact_ids": [artifact_id]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ARTIFACT_NOT_ATTACHABLE"


@pytest.mark.parametrize(
    "filename",
    [
        "../secret.txt",
        "..\\secret.txt",
        "/absolute.txt",
        ".env",
        "   ",
    ],
)
async def test_upload_rejects_unsafe_filenames(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    filename: str,
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)

    response = await client.post(
        "/api/v1/uploads/",
        headers=tenant_a_headers,
        data={"conversation_id": conversation_id},
        files={"file": (filename, b"safe text\n", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_upload_rejects_oversized_content(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "artifact_max_file_bytes", 4)
    conversation_id = await _create_conversation(client, tenant_a_headers)

    response = await client.post(
        "/api/v1/uploads/",
        headers=tenant_a_headers,
        data={"conversation_id": conversation_id},
        files={"file": ("too-large.txt", b"too large", "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"


async def test_upload_rejects_binary_disallowed_content(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)

    response = await client.post(
        "/api/v1/uploads/",
        headers=tenant_a_headers,
        data={"conversation_id": conversation_id},
        files={"file": ("payload.bin", b"\x00\x01\x02\x03", "application/octet-stream")},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_UPLOAD_TYPE"


async def test_upload_rejects_invalid_utf8_text(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)

    response = await client.post(
        "/api/v1/uploads/",
        headers=tenant_a_headers,
        data={"conversation_id": conversation_id},
        files={"file": ("bad.txt", b"\xff\xfe", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_UPLOAD_TYPE"


async def test_upload_quota_is_serialized_across_concurrent_requests(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "artifact_tenant_quota_bytes", 15)
    conversation_id = await _create_conversation(client, tenant_a_headers)

    async def upload(filename: str):
        return await client.post(
            "/api/v1/uploads/",
            headers=tenant_a_headers,
            data={"conversation_id": conversation_id},
            files={"file": (filename, b"1234567890", "text/plain")},
        )

    first, second = await asyncio.gather(upload("a.txt"), upload("b.txt"))

    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [201, 409]
    quota_response = first if first.status_code == 409 else second
    assert quota_response.json()["error"]["code"] == "UPLOAD_QUOTA_EXCEEDED"


async def test_available_tools_endpoint_is_user_readable_for_chat_picker(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    response = await client.get(
        "/api/v1/tools/available?limit=200&offset=0",
        headers=tenant_a_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(["items", "total", "limit", "offset", "next"]).issubset(payload)
    assert any(
        item.get("function", {}).get("name") == "code_as_action"
        for item in payload["items"]
    )
