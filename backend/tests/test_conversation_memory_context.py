"""Conversation/session context privacy regressions."""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient

from app.api.deps import _async_session_factory
from app.core.capabilities.service import create_candidate
from app.main import app_state
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


class _Gateway:
    async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
        _ = (provider, messages, tools, max_tokens, tenant_id)
        yield {"type": "text", "content": "assistant response"}

    async def embed(self, provider, texts, tenant_id=None):
        _ = (provider, tenant_id)
        vector = [0.0] * 1536
        vector[0] = 1.0
        return [vector for _ in texts]


def _identity(headers: dict[str, str]) -> dict[str, str]:
    return decode_token(headers["Authorization"].split(" ", 1)[1])


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


async def _register_same_tenant_user(
    client: AsyncClient,
    tenant_name: str,
) -> dict[str, str]:
    suffix = uuid.uuid4().hex
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": tenant_name,
            "username": f"user-{suffix}",
            "password": "secret123",
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _seed_memory_candidate(headers: dict[str, str], marker: str) -> uuid.UUID:
    identity = _identity(headers)
    async with _async_session_factory() as db:
        candidate = await create_candidate(
            db,
            tenant_id=uuid.UUID(identity["tenant_id"]),
            user_id=uuid.UUID(identity["user_id"]),
            candidate_type="memory",
            title=f"Owner private memory {marker}",
            body=f"Owner private memory body {marker}",
            source_run_id=f"run-{uuid.uuid4().hex}",
            source_kind="conversation",
            dedupe_key=f"memory:{uuid.uuid4().hex}",
            evidence={"source_evidence": ["owner asked to remember this"]},
            payload={
                "memory_type": "project",
                "memory_text": f"Owner-only memory marker {marker}",
                "tags": [marker],
            },
        )
        await db.commit()
        await db.refresh(candidate)
        return candidate.id


async def test_chat_context_excludes_same_tenant_other_user_accepted_private_memory(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_state, "llm_gateway", _Gateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())
    tenant_name = f"conversation-memory-{uuid.uuid4().hex}"
    owner_headers = await _register_same_tenant_user(client, tenant_name)
    same_tenant_other = await _register_same_tenant_user(client, tenant_name)
    marker = f"owner-memory-{uuid.uuid4().hex}"
    candidate_id = await _seed_memory_candidate(owner_headers, marker)

    accepted = await client.post(
        f"/api/v1/capability-candidates/{candidate_id}/accept",
        headers=owner_headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["metadata"]["target"]["memory_id"]

    created = await client.post(
        "/api/v1/conversations/",
        headers=same_tenant_other,
        json={"title": "memory context isolation"},
    )
    assert created.status_code == 200, created.text

    chat = await client.post(
        f"/api/v1/conversations/{created.json()['id']}/chat",
        headers=same_tenant_other,
        json={"content": f"Please use {marker} if available."},
    )

    assert chat.status_code == 200, chat.text
    context_events = [data for name, data in _parse_sse(chat.text) if name == "context"]
    assert context_events
    assert context_events[0]["memory_count"] == 0
    assert marker not in json.dumps(context_events[0])
