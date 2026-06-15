"""W8 risky/destructive tool cancellation contract."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.conversation import Message
from app.models.tool_confirmation import ToolConfirmation
from app.services.conversation_stream_service import persist_confirmation_required

pytestmark = pytest.mark.asyncio


async def test_denied_tool_confirmation_cancels_execution_and_records_alternative(
    client,
    tenant_a_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.conversation_stream_service as stream_service
    from app.api.deps import _async_session_factory
    from app.main import app_state

    executed = False

    async def fail_if_executed(*args, **kwargs):
        nonlocal executed
        executed = True
        raise AssertionError("denied tool must not execute")

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {"type": "text", "content": "should not resume on deny"}

    monkeypatch.setattr(stream_service, "execute_confirmed_tool", fail_if_executed)
    monkeypatch.setattr(app_state, "llm_gateway", Gateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "deny-tool"},
    )
    assert created.status_code == 200, created.text
    conv_id = uuid.UUID(created.json()["id"])

    async with _async_session_factory() as db:
        await persist_confirmation_required(
            db,
            conv_id,
            tool_call_id="deny-call",
            tool_name="shell_exec",
            args={"command": "rm -rf /tmp/example"},
            risk="destructive",
            timeout_s=30,
        )

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/confirm",
        headers=tenant_a_headers,
        json={"tool_call_id": "deny-call", "decision": "deny"},
    )

    assert response.status_code == 200, response.text
    assert "event: done" in response.text
    assert executed is False
    async with _async_session_factory() as db:
        confirmation = (
            await db.execute(
                select(ToolConfirmation).where(
                    ToolConfirmation.conversation_id == conv_id,
                    ToolConfirmation.tool_call_id == "deny-call",
                )
            )
        ).scalar_one()
        messages = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conv_id)
                .order_by(Message.created_at)
            )
        ).scalars().all()

    assert confirmation.status == "denied"
    assert any("User denied destructive tool" in (message.content or "") for message in messages)
