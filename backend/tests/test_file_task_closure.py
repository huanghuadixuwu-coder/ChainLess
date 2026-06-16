"""W12 file task closure contract tests."""

from __future__ import annotations

import json
from pathlib import Path
import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.artifacts import capture_file_write_artifact
from app.core.tools.builtin import file_ops
from app.main import app_state
from app.models.artifact import Artifact
from app.models.conversation import Conversation

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
    title: str = "w12-file-task-closure",
) -> str:
    response = await client.post(
        "/api/v1/conversations/",
        headers=headers,
        json={"title": title},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _upload_text_artifact(
    client: AsyncClient,
    headers: dict[str, str],
    conversation_id: str,
    *,
    filename: str,
    content: bytes,
    content_type: str = "text/plain",
) -> dict:
    response = await client.post(
        "/api/v1/uploads/",
        headers=headers,
        data={"conversation_id": conversation_id},
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 201, response.text
    return response.json()["artifact"]


async def test_artifact_download_returns_bytes_headers_and_enforces_tenant_boundary(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)
    artifact = await _upload_text_artifact(
        client,
        tenant_a_headers,
        conversation_id,
        filename="w12-download.txt",
        content=b"download me\n",
    )

    response = await client.get(
        f"/api/v1/artifacts/{artifact['id']}/download",
        headers=tenant_a_headers,
    )

    assert response.status_code == 200, response.text
    assert response.content == b"download me\n"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "w12-download.txt" in response.headers["content-disposition"]
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-length"] == str(len(b"download me\n"))

    foreign = await client.get(
        f"/api/v1/artifacts/{artifact['id']}/download",
        headers=tenant_b_headers,
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"


async def test_artifact_download_uses_ascii_fallback_for_non_ascii_workspace_path(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)
    async with _async_session_factory() as db:
        conversation = (
            await db.execute(
                select(Conversation).where(Conversation.id == uuid.UUID(conversation_id))
            )
        ).scalar_one()

    artifacts = await capture_file_write_artifact(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        run_id="w12-non-ascii-download",
        tool_call_id="tool-non-ascii-download",
        workspace_path="outputs/报告.txt",
        before_content=None,
        after_content="download unicode name\n",
    )
    artifact_id = artifacts[0]["id"]

    response = await client.get(
        f"/api/v1/artifacts/{artifact_id}/download",
        headers=tenant_a_headers,
    )

    assert response.status_code == 200, response.text
    disposition = response.headers["content-disposition"]
    fallback = disposition.split("filename=", 1)[1].split(";", 1)[0]
    fallback.encode("ascii")
    assert "报告" not in fallback
    assert "filename*=UTF-8''" in disposition
    assert "%E6%8A%A5%E5%91%8A.txt" in disposition


async def test_conversation_detail_returns_sent_attachment_metadata(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)
    artifact = await _upload_text_artifact(
        client,
        tenant_a_headers,
        conversation_id,
        filename="w12-attached.txt",
        content=b"attachment metadata\n",
    )

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {"type": "text", "content": "attachment accepted"}

    monkeypatch.setattr(app_state, "llm_gateway", Gateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/chat",
        headers=tenant_a_headers,
        json={
            "content": "Use the attached file.",
            "attachment_artifact_ids": [artifact["id"]],
        },
    )
    assert response.status_code == 200, response.text

    detail = await client.get(
        f"/api/v1/conversations/{conversation_id}",
        headers=tenant_a_headers,
    )
    assert detail.status_code == 200, detail.text
    user_message = next(
        message
        for message in detail.json()["messages"]
        if message["role"] == "user" and message["content"] == "Use the attached file."
    )

    assert user_message["attachments"][0]["id"] == artifact["id"]
    assert user_message["attachments"][0]["path"] == "uploads/w12-attached.txt"
    assert user_message["attachments"][0]["state"] == "available"
    assert user_message["attachments"][0]["operation"] == "upload"
    assert (
        user_message["attachments"][0]["download_url"]
        == f"/api/v1/artifacts/{artifact['id']}/download"
    )


async def test_run_workspace_materializes_upload_and_file_tools_are_run_scoped(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    from app.core.artifacts.workspace import prepare_run_workspace

    conversation_id = await _create_conversation(client, tenant_a_headers)
    uploaded = await _upload_text_artifact(
        client,
        tenant_a_headers,
        conversation_id,
        filename="w12-input.txt",
        content=b"run scoped input\n",
    )
    async with _async_session_factory() as db:
        artifact = (
            await db.execute(
                select(Artifact).where(Artifact.id == uuid.UUID(uploaded["id"]))
            )
        ).scalar_one()
        run_workspace = await prepare_run_workspace(
            run_id="w12-run",
            artifacts=[artifact],
            root=tmp_path / "workspace",
        )

    input_path = run_workspace.input_paths[str(artifact.id)]
    result = await file_ops.execute(
        "file_read",
        {"path": input_path},
        context={"workspace_base": str(run_workspace.base_path)},
    )

    assert result == "run scoped input\n"
    assert input_path.startswith("input/")


async def test_file_list_does_not_expose_stale_global_workspace_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_base = workspace_root / "runs" / "w12-isolated"
    run_base.mkdir(parents=True)
    (workspace_root / "stale-w6-output.txt").write_text("old test file\n", encoding="utf-8")
    (run_base / "current.txt").write_text("current run\n", encoding="utf-8")
    monkeypatch.setattr(file_ops, "_ALLOWED_BASE", str(workspace_root))

    result = await file_ops.execute(
        "file_list",
        {"path": "."},
        context={"workspace_base": str(run_base)},
    )

    assert "current.txt" in result
    assert "stale-w6-output.txt" not in result


async def test_chat_attachment_is_readable_through_file_read_tool(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(client, tenant_a_headers)
    uploaded = await _upload_text_artifact(
        client,
        tenant_a_headers,
        conversation_id,
        filename="w12-runtime.txt",
        content=b"runtime file fact: amber fox\n",
    )

    class Gateway:
        calls = 0

        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            self.calls += 1
            if self.calls == 1:
                joined = "\n".join(str(message.get("content", "")) for message in messages)
                match = re.search(
                    rf"input/{re.escape(uploaded['id'])}/w12-runtime\.txt",
                    joined,
                )
                if not match:
                    yield {"type": "text", "content": "no materialized path"}
                    return
                yield {
                    "type": "tool_call",
                    "index": 0,
                    "id": "w12-file-read",
                    "name": "file_read",
                    "arguments": json.dumps({"path": match.group(0)}),
                }
                return

            tool_message = next(
                message for message in reversed(messages) if message.get("role") == "tool"
            )
            yield {
                "type": "text",
                "content": f"read via file_read: {tool_message['content']}",
            }

    gateway = Gateway()
    monkeypatch.setattr(app_state, "llm_gateway", gateway)
    monkeypatch.setattr(app_state, "sandbox_manager", object())

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/chat",
        headers=tenant_a_headers,
        json={
            "content": "Read the uploaded file through file_read.",
            "attachment_artifact_ids": [uploaded["id"]],
        },
    )

    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert ("tool_call", {
        "id": "w12-file-read",
        "name": "file_read",
        "args": {"path": f"input/{uploaded['id']}/w12-runtime.txt"},
        "risk": "safe",
        "status": "started",
    }) in events
    tool_result = next(data for name, data in events if name == "tool_result")
    assert tool_result["name"] == "file_read"
    assert "runtime file fact: amber fox" in tool_result["result"]
    assert "read via file_read: runtime file fact: amber fox" in response.text


async def test_attachment_materialization_failure_fails_closed_before_llm_call(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import conversation_stream_service

    conversation_id = await _create_conversation(client, tenant_a_headers)
    uploaded = await _upload_text_artifact(
        client,
        tenant_a_headers,
        conversation_id,
        filename="w12-fail-closed.txt",
        content=b"must not reach llm\n",
    )

    async def fail_prepare_run_workspace(**kwargs):
        raise RuntimeError("materialization exploded")

    monkeypatch.setattr(
        conversation_stream_service,
        "prepare_run_workspace",
        fail_prepare_run_workspace,
        raising=False,
    )

    class Gateway:
        calls = 0

        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            self.calls += 1
            yield {"type": "text", "content": "should not run"}

    gateway = Gateway()
    monkeypatch.setattr(app_state, "llm_gateway", gateway)
    monkeypatch.setattr(app_state, "sandbox_manager", object())

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/chat",
        headers=tenant_a_headers,
        json={
            "content": "Read the attached file.",
            "attachment_artifact_ids": [uploaded["id"]],
        },
    )

    assert response.status_code == 200, response.text
    assert gateway.calls == 0
    assert "ATTACHMENT_MATERIALIZATION_FAILED" in response.text
    assert "should not run" not in response.text
