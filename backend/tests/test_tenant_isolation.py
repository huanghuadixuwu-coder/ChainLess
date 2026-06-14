"""Tenant isolation tests for V1 resource families."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.api.deps import _async_session_factory
from app.models.user import User
from app.services.auth_service import decode_token


pytestmark = pytest.mark.asyncio


async def _promote_to_admin(headers: dict[str, str]) -> None:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()


async def test_conversations_are_hidden_across_tenants(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "tenant-a-private"},
    )
    assert created.status_code == 200, created.text
    conv_id = created.json()["id"]

    cross_read = await client.get(
        f"/api/v1/conversations/{conv_id}",
        headers=tenant_b_headers,
    )
    cross_delete = await client.delete(
        f"/api/v1/conversations/{conv_id}",
        headers=tenant_b_headers,
    )

    assert cross_read.status_code == 404
    assert cross_read.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert cross_delete.status_code == 404
    assert cross_delete.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def test_agents_are_hidden_across_tenants(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    await _promote_to_admin(tenant_a_headers)
    await _promote_to_admin(tenant_b_headers)

    created = await client.post(
        "/api/v1/agents/",
        headers=tenant_a_headers,
        json={"name": "tenant-a-agent"},
    )
    assert created.status_code == 200, created.text
    agent_id = created.json()["id"]

    cross_read = await client.get(f"/api/v1/agents/{agent_id}", headers=tenant_b_headers)

    assert cross_read.status_code == 404
    assert cross_read.json()["error"]["code"] == "AGENT_NOT_FOUND"


async def test_memories_are_hidden_across_tenants(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    await _promote_to_admin(tenant_a_headers)
    await _promote_to_admin(tenant_b_headers)

    created = await client.post(
        "/api/v1/memories/",
        headers=tenant_a_headers,
        json={
            "type": "user",
            "name": "tenant-a-memory",
            "content": "secret tenant memory",
            "tags": ["tenant-a"],
        },
    )
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]

    cross_update = await client.put(
        f"/api/v1/memories/{memory_id}",
        headers=tenant_b_headers,
        json={"content": "takeover"},
    )

    assert cross_update.status_code == 404
    assert cross_update.json()["error"]["code"] == "MEMORY_NOT_FOUND"


async def test_provider_registry_is_tenant_filtered(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    await _promote_to_admin(tenant_a_headers)
    await _promote_to_admin(tenant_b_headers)

    created = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "tenant-a-provider",
            "api_base": "https://example.com/v1",
            "api_key": "secret",
            "model": "test-model",
        },
    )
    assert created.status_code == 201, created.text

    tenant_b_list = await client.get("/api/v1/llm-providers/", headers=tenant_b_headers)

    assert tenant_b_list.status_code == 200
    assert tenant_b_list.json()["items"] == []


async def test_proactive_tasks_are_hidden_across_tenants(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    await _promote_to_admin(tenant_a_headers)
    await _promote_to_admin(tenant_b_headers)

    created = await client.post(
        "/api/v1/proactive-tasks",
        headers=tenant_a_headers,
        json={
            "type": "cron",
            "cron_expr": "0 9 * * *",
            "agent_id": "default",
            "prompt": "tenant-a-only",
            "channel_type": "feishu",
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["task_id"]

    tenant_b_list = await client.get("/api/v1/proactive-tasks", headers=tenant_b_headers)
    tenant_b_delete = await client.delete(
        f"/api/v1/proactive-tasks/{task_id}",
        headers=tenant_b_headers,
    )

    assert tenant_b_list.status_code == 200
    assert all(item["task_id"] != task_id for item in tenant_b_list.json()["items"])
    assert tenant_b_delete.status_code == 404
    assert tenant_b_delete.json()["error"]["code"] == "TASK_NOT_FOUND"
