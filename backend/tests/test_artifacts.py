"""Conversation file artifact and diff contract tests."""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.artifacts.service import read_artifact_content
from app.main import app_state
from app.models.artifact import Artifact

pytestmark = pytest.mark.asyncio


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in text.strip().split("\n\n"):
        event_name = ""
        data = {}
        for line in frame.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        if event_name:
            events.append((event_name, data))
    return events


async def _create_conversation(
    client: AsyncClient,
    headers: dict[str, str],
    title: str,
) -> str:
    response = await client.post(
        "/api/v1/conversations/",
        headers=headers,
        json={"title": title},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_chat_file_write_emits_persisted_artifact_and_real_diff(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = f"w6/{uuid.uuid4().hex}.txt"

    class FileWriteGateway:
        calls = 0

        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "tool_call",
                    "index": 0,
                    "id": "file-write-call",
                    "name": "file_write",
                    "arguments": json.dumps({"path": path, "content": "answer = 42\n"}),
                }
            else:
                yield {"type": "text", "content": "file written"}

    monkeypatch.setattr(app_state, "llm_gateway", FileWriteGateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())
    conv_id = await _create_conversation(client, tenant_a_headers, "artifact-stream")

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/chat",
        headers=tenant_a_headers,
        json={"content": "write a file"},
    )
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    tool_result = next(data for name, data in events if name == "tool_result")
    artifacts = tool_result["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["path"] == path
    assert artifacts[0]["state"] == "available"
    assert artifacts[0]["has_content"] is True
    assert artifacts[0]["has_diff"] is True

    artifact_id = artifacts[0]["id"]
    listed = await client.get(
        f"/api/v1/artifacts/?conversation_id={conv_id}",
        headers=tenant_a_headers,
    )
    content = await client.get(f"/api/v1/artifacts/{artifact_id}/content", headers=tenant_a_headers)
    diff = await client.get(f"/api/v1/artifacts/{artifact_id}/diff", headers=tenant_a_headers)

    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["id"] == artifact_id
    assert content.status_code == 200, content.text
    assert content.json()["content"] == "answer = 42\n"
    assert diff.status_code == 200, diff.text
    assert f"+++ b/{path}" in diff.json()["content"]
    assert "+answer = 42" in diff.json()["content"]


async def test_artifact_list_survives_reload_and_purge_removes_storage(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = f"w6/{uuid.uuid4().hex}.txt"

    class Gateway:
        calls = 0

        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "tool_call",
                    "index": 0,
                    "id": "persist-call",
                    "name": "file_write",
                    "arguments": json.dumps({"path": path, "content": "persist me\n"}),
                }
            else:
                yield {"type": "text", "content": "done"}

    monkeypatch.setattr(app_state, "llm_gateway", Gateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())
    conv_id = await _create_conversation(client, tenant_a_headers, "artifact-reload")

    written = await client.post(
        f"/api/v1/conversations/{conv_id}/chat",
        headers=tenant_a_headers,
        json={"content": "write"},
    )
    artifact_id = next(
        data for name, data in _parse_sse(written.text) if name == "tool_result"
    )["artifacts"][0]["id"]

    first_list = await client.get(
        f"/api/v1/artifacts/?conversation_id={conv_id}",
        headers=tenant_a_headers,
    )
    second_list = await client.get(
        f"/api/v1/artifacts/?conversation_id={conv_id}",
        headers=tenant_a_headers,
    )
    assert first_list.status_code == 200
    assert second_list.status_code == 200
    assert first_list.json()["items"][0]["id"] == second_list.json()["items"][0]["id"]

    async with _async_session_factory() as db:
        artifact = (
            await db.execute(select(Artifact).where(Artifact.id == uuid.UUID(artifact_id)))
        ).scalar_one()
        stored_content = await read_artifact_content(artifact, content_kind="content")
    assert stored_content == "persist me\n"

    purged = await client.delete(
        f"/api/v1/conversations/{conv_id}?purge=true",
        headers=tenant_a_headers,
    )
    assert purged.status_code == 204

    async with _async_session_factory() as db:
        remaining = (
            await db.execute(select(Artifact).where(Artifact.id == uuid.UUID(artifact_id)))
        ).scalar_one_or_none()
    assert remaining is None


async def test_artifacts_never_cross_tenant_or_user_boundaries(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = f"w6/{uuid.uuid4().hex}.txt"

    class Gateway:
        calls = 0

        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "tool_call",
                    "index": 0,
                    "id": "tenant-call",
                    "name": "file_write",
                    "arguments": json.dumps({"path": path, "content": "private\n"}),
                }
            else:
                yield {"type": "text", "content": "done"}

    monkeypatch.setattr(app_state, "llm_gateway", Gateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())
    conv_id = await _create_conversation(client, tenant_a_headers, "artifact-tenant")
    written = await client.post(
        f"/api/v1/conversations/{conv_id}/chat",
        headers=tenant_a_headers,
        json={"content": "write"},
    )
    artifact_id = next(
        data for name, data in _parse_sse(written.text) if name == "tool_result"
    )["artifacts"][0]["id"]

    cross_list = await client.get(
        f"/api/v1/artifacts/?conversation_id={conv_id}",
        headers=tenant_b_headers,
    )
    cross_read = await client.get(
        f"/api/v1/artifacts/{artifact_id}",
        headers=tenant_b_headers,
    )

    assert cross_list.status_code == 404
    assert cross_list.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert cross_read.status_code == 404
    assert cross_read.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"
