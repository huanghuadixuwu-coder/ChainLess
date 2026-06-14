"""Canonical SSE contract tests."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.sse import sse_error, sse_event
from app.core.artifacts import ToolExecutionResult
from app.core.agent.code_executor import CODE_AS_ACTION_TOOL
from app.core.agent.engine import run_agent
from app.models.conversation import Message
from app.models.tool_confirmation import ToolConfirmation
from app.services.auth_service import decode_token
from app.services.conversation_stream_service import (
    build_chat_stream_response,
    persist_confirmation_required,
    public_agent_event,
)


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


def test_sse_helper_formats_canonical_events_and_error_envelope() -> None:
    assert sse_event("text", {"delta": "hi"}, event_id="1") == (
        'id: 1\nevent: text\ndata: {"delta": "hi"}\n\n'
    )

    error_frame = sse_error("AGENT_ERROR", "Agent failed")
    event_name, data = _parse_sse(error_frame)[0]
    assert event_name == "error"
    assert data == {
        "error": {
            "code": "AGENT_ERROR",
            "message": "Agent failed",
            "detail": None,
        }
    }


def test_internal_agent_events_map_to_public_canonical_events() -> None:
    tool_call = public_agent_event({
        "type": "tool_call_start",
        "tool_call_id": "call-1",
        "name": "weather_get",
        "args": {"city": "Wuxi"},
        "risk": "safe",
    })
    tool_error = public_agent_event({
        "type": "tool_error",
        "tool_call_id": "call-2",
        "name": "weather_get",
        "error": "network",
        "consecutive": 1,
    })

    assert tool_call == (
        "tool_call",
        {
            "id": "call-1",
            "name": "weather_get",
            "args": {"city": "Wuxi"},
            "risk": "safe",
            "status": "started",
        },
    )
    assert tool_error == (
        "tool_result",
        {
            "id": "call-2",
            "name": "weather_get",
            "error": "network",
            "consecutive": 1,
            "status": "error",
        },
    )


@pytest.mark.asyncio
async def test_code_as_action_emits_sandbox_events() -> None:
    class FakeGateway:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "tool_call",
                    "index": 0,
                    "id": "call-code",
                    "name": "code_as_action",
                    "arguments": '{"script": "print(6 * 7)"}',
                }
            else:
                yield {"type": "text", "content": "done"}

    class FakeSandbox:
        async def execute_disposable_parent(self, **kwargs) -> dict:
            return {
                "container_id": "sandbox-1",
                "deleted": True,
                "active_container_ids": [],
                "cleanup_errors": [],
                "stdout": "42",
                "stderr": "",
            }

    events = [
        event
        async for event in run_agent(
            FakeGateway(),
            FakeSandbox(),
            "default",
            [{"role": "user", "content": "run code"}],
            tools=[CODE_AS_ACTION_TOOL],
            tenant_id="tenant-a",
        )
    ]

    event_types = [event["type"] for event in events]
    assert "sandbox" in event_types
    assert "sandbox_output" in event_types
    assert any(event.get("data") == "42" for event in events)
    assert any(event["type"] == "tool_result" and "42" in event["result"] for event in events)


@pytest.mark.asyncio
async def test_code_as_action_artifact_event_is_not_added_to_llm_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.agent import engine

    class Gateway:
        calls = 0

        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "tool_call",
                    "index": 0,
                    "id": "code",
                    "name": "code_as_action",
                    "arguments": '{"script":"print(42)"}',
                }
            else:
                yield {"type": "text", "content": "done"}

    async def fake_stream(*args, **kwargs):
        yield {"type": "sandbox_output", "stream": "stdout", "data": "42"}
        yield {
            "type": "sandbox_output",
            "stream": "artifact",
            "data": '{"artifact_path":"/workspace/internal"}',
        }

    monkeypatch.setattr(engine, "stream_code_as_action", fake_stream)
    events = [
        event
        async for event in run_agent(
            Gateway(),
            object(),
            "default",
            [{"role": "user", "content": "run"}],
            tools=[CODE_AS_ACTION_TOOL],
            tenant_id="tenant-a",
        )
    ]

    assert any(event.get("stream") == "artifact" for event in events)
    tool_result = next(event for event in events if event["type"] == "tool_result")
    assert tool_result["result"] == "42"


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ['{"script":', '["not", "an", "object"]'])
async def test_malformed_tool_arguments_become_tool_errors_and_trip_circuit_breaker(
    arguments: str,
) -> None:
    class FakeGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {
                "type": "tool_call",
                "index": 0,
                "id": f"call-{len(messages)}",
                "name": "code_as_action",
                "arguments": arguments,
            }

    events = [
        event
        async for event in run_agent(
            FakeGateway(),
            object(),
            "default",
            [{"role": "user", "content": "bad args"}],
            tools=[CODE_AS_ACTION_TOOL],
            tenant_id="tenant-a",
        )
    ]

    tool_errors = [event for event in events if event["type"] == "tool_error"]
    assert [event["consecutive"] for event in tool_errors] == [1, 2, 3]
    assert all("invalid tool arguments" in event["error"] for event in tool_errors)
    assert any(
        event.get("type") == "error" and event.get("code") == "CIRCUIT_BREAKER"
        for event in events
    )


@pytest.mark.asyncio
async def test_chat_endpoint_emits_canonical_events_and_persists_once(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.deps import _async_session_factory
    from app.main import app_state

    class FakeGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {"type": "text", "content": "hello"}

    class FakeSandbox:
        pass

    monkeypatch.setattr(app_state, "llm_gateway", FakeGateway())
    monkeypatch.setattr(app_state, "sandbox_manager", FakeSandbox())

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "sse-test"},
    )
    assert created.status_code == 200, created.text
    conv_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/chat",
        headers=tenant_a_headers,
        json={"content": "hi"},
    )

    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    event_names = [name for name, _ in events]
    assert event_names == ["context", "text", "done"]
    assert events[0][1]["memory_count"] == 0
    assert events[0][1]["agent"]["name"] == "default"
    assert "tool_call_start" not in response.text
    assert "tool_error" not in response.text

    async with _async_session_factory() as db:
        rows = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == uuid.UUID(conv_id))
                .order_by(Message.created_at.asc())
            )
        ).scalars().all()

    assistant_messages = [row for row in rows if row.role == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0].content == "hello"


@pytest.mark.asyncio
async def test_disconnected_stream_does_not_persist_partial_assistant(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    class FakeGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {"type": "text", "content": "partial"}

    class FakeSandbox:
        pass

    class DisconnectedRequest:
        async def is_disconnected(self) -> bool:
            return True

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "disconnect-test"},
    )
    assert created.status_code == 200, created.text
    conv_id = uuid.UUID(created.json()["id"])

    async with _async_session_factory() as db:
        response = await build_chat_stream_response(
            FakeGateway(),
            FakeSandbox(),
            db,
            conv_id,
            [{"role": "user", "content": "hi"}],
            DisconnectedRequest(),
            tenant_id="tenant-a",
        )
        chunks = [chunk async for chunk in response.body_iterator]

    assert chunks == []

    async with _async_session_factory() as db:
        rows = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conv_id)
                .order_by(Message.created_at.asc())
            )
        ).scalars().all()

    assert [row.role for row in rows if row.role == "assistant"] == []


@pytest.mark.asyncio
async def test_disconnected_stream_cancels_running_agent_task(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    started = asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            if False:
                yield {}

    class DisconnectedAfterStart:
        async def is_disconnected(self) -> bool:
            await started.wait()
            return True

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "disconnect-cancel-test"},
    )
    assert created.status_code == 200, created.text
    token = tenant_a_headers["Authorization"].removeprefix("Bearer ")
    tenant_id = decode_token(token)["tenant_id"]

    async with _async_session_factory() as db:
        response = await build_chat_stream_response(
            BlockingGateway(),
            object(),
            db,
            uuid.UUID(created.json()["id"]),
            [{"role": "user", "content": "hi"}],
            DisconnectedAfterStart(),
            tenant_id=tenant_id,
        )
        assert [chunk async for chunk in response.body_iterator] == []

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_confirmation_requires_pending_record_and_ignores_client_tool_payload(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.deps import _async_session_factory
    from app.main import app_state
    import app.services.conversation_stream_service as stream_service

    executed: list[tuple[str, dict]] = []

    class FakeGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {"type": "text", "content": "resumed"}

    async def fake_execute(tool_name, args, sandbox, **kwargs):
        executed.append((tool_name, args))
        return "ok"

    monkeypatch.setattr(app_state, "llm_gateway", FakeGateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())
    monkeypatch.setattr(stream_service, "execute_confirmed_tool", fake_execute)

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "confirm-owner"},
    )
    conv_id = uuid.UUID(created.json()["id"])

    direct = await client.post(
        f"/api/v1/conversations/{conv_id}/confirm",
        headers=tenant_a_headers,
        json={
            "tool_call_id": "missing",
            "decision": "approve",
            "tool_name": "shell_exec",
            "args": {"script": "malicious"},
        },
    )
    assert direct.status_code == 422
    assert executed == []

    async with _async_session_factory() as db:
        await persist_confirmation_required(
            db,
            conv_id,
            tool_call_id="real-call",
            tool_name="shell_exec",
            args={"script": "server-owned"},
            risk="destructive",
            timeout_s=30,
        )

    approved = await client.post(
        f"/api/v1/conversations/{conv_id}/confirm",
        headers=tenant_a_headers,
        json={
            "tool_call_id": "real-call",
            "decision": "approve",
            "tool_name": "code_as_action",
            "args": {"script": "client-overwrite"},
        },
    )
    assert approved.status_code == 200, approved.text
    assert executed == [("shell_exec", {"script": "server-owned"})]

    async with _async_session_factory() as db:
        confirmation = (
            await db.execute(
                select(ToolConfirmation).where(
                    ToolConfirmation.conversation_id == conv_id,
                    ToolConfirmation.tool_call_id == "real-call",
                )
            )
        ).scalar_one()
    assert confirmation.status == "approved"


@pytest.mark.asyncio
async def test_confirmation_concurrent_replay_executes_at_most_once(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.deps import _async_session_factory
    from app.main import app_state
    import app.services.conversation_stream_service as stream_service

    executions = 0
    release = asyncio.Event()

    class FakeGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {"type": "text", "content": "resumed"}

    async def fake_execute(*args, **kwargs):
        nonlocal executions
        executions += 1
        await release.wait()
        return "ok"

    monkeypatch.setattr(app_state, "llm_gateway", FakeGateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())
    monkeypatch.setattr(stream_service, "execute_confirmed_tool", fake_execute)

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "confirm-replay"},
    )
    conv_id = uuid.UUID(created.json()["id"])
    async with _async_session_factory() as db:
        await persist_confirmation_required(
            db,
            conv_id,
            tool_call_id="single-use",
            tool_name="shell_exec",
            args={"script": "echo safe"},
            risk="destructive",
            timeout_s=30,
        )

    async def approve():
        return await client.post(
            f"/api/v1/conversations/{conv_id}/confirm",
            headers=tenant_a_headers,
            json={"tool_call_id": "single-use", "decision": "approve"},
        )

    first = asyncio.create_task(approve())
    while executions == 0:
        await asyncio.sleep(0)
    second = await approve()
    release.set()
    first_response = await first

    assert sorted([first_response.status_code, second.status_code]) == [200, 422]
    assert executions == 1


@pytest.mark.asyncio
async def test_confirmation_tool_result_preserves_artifacts(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.deps import _async_session_factory
    from app.main import app_state
    import app.services.conversation_stream_service as stream_service

    artifact = {
        "id": str(uuid.uuid4()),
        "path": "w6/confirmed.txt",
        "state": "available",
        "has_content": True,
        "has_diff": True,
    }

    class FakeGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {"type": "text", "content": "resumed"}

    async def fake_execute(*args, **kwargs):
        return ToolExecutionResult(content="confirmed write", artifacts=[artifact])

    monkeypatch.setattr(app_state, "llm_gateway", FakeGateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())
    monkeypatch.setattr(stream_service, "execute_confirmed_tool", fake_execute)

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "confirm-artifact"},
    )
    conv_id = uuid.UUID(created.json()["id"])
    async with _async_session_factory() as db:
        await persist_confirmation_required(
            db,
            conv_id,
            tool_call_id="artifact-confirmation",
            tool_name="file_write",
            args={"path": "w6/confirmed.txt", "content": "confirmed\n"},
            risk="destructive",
            timeout_s=30,
        )

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/confirm",
        headers=tenant_a_headers,
        json={"tool_call_id": "artifact-confirmation", "decision": "approve"},
    )

    assert response.status_code == 200, response.text
    tool_result = next(data for name, data in _parse_sse(response.text) if name == "tool_result")
    assert tool_result["result"] == "confirmed write"
    assert tool_result["artifacts"] == [artifact]
