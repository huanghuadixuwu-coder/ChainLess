"""Settings management authorization and tenant isolation."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.api.deps import _async_session_factory
from app.models.user import User
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


async def _promote(headers: dict[str, str]) -> None:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == uuid.UUID(payload["user_id"]))
            .values(role="admin")
        )
        await db.commit()


async def test_settings_routes_are_admin_only(
    client: AsyncClient, tenant_a_headers: dict[str, str]
) -> None:
    requests = [
        await client.get("/api/v1/llm-providers/", headers=tenant_a_headers),
        await client.post(
            "/api/v1/llm-providers/",
            headers=tenant_a_headers,
            json={"name": "x", "api_base": "https://example.test", "api_key": "secret", "model": "m"},
        ),
        await client.get("/api/v1/channels", headers=tenant_a_headers),
        await client.post(
            "/api/v1/channels",
            headers=tenant_a_headers,
            json={"channel_type": "feishu", "config": {"webhook_url": "https://open.feishu.cn/member-secret"}},
        ),
        await client.post("/api/v1/llm-providers/x/default", headers=tenant_a_headers),
        await client.post("/api/v1/llm-providers/x/test", headers=tenant_a_headers),
        await client.delete("/api/v1/llm-providers/x", headers=tenant_a_headers),
        await client.get("/api/v1/skills/", headers=tenant_a_headers),
        await client.post(
            "/api/v1/skills/",
            headers=tenant_a_headers,
            json={"name": "x", "trigger_terms": ["x"]},
        ),
        await client.post(
            "/api/v1/skills/match",
            headers=tenant_a_headers,
            json={"text": "x"},
        ),
        await client.get("/api/v1/eval/suites", headers=tenant_a_headers),
        await client.get("/api/v1/eval/status", headers=tenant_a_headers),
        await client.post(
            "/api/v1/eval/run",
            headers=tenant_a_headers,
            json={"suite": "basic", "dry_run": True},
        ),
        await client.post(
            "/api/v1/channels/feishu/test",
            headers=tenant_a_headers,
            json={"title": "x", "content": "x"},
        ),
        await client.get("/api/v1/agents/", headers=tenant_a_headers),
        await client.post(
            "/api/v1/agents/",
            headers=tenant_a_headers,
            json={"name": "x"},
        ),
        await client.get(f"/api/v1/agents/{uuid.uuid4()}", headers=tenant_a_headers),
        await client.put(
            f"/api/v1/agents/{uuid.uuid4()}",
            headers=tenant_a_headers,
            json={"name": "x"},
        ),
        await client.delete(f"/api/v1/agents/{uuid.uuid4()}", headers=tenant_a_headers),
        await client.get("/api/v1/tools/", headers=tenant_a_headers),
        await client.post(
            "/api/v1/tools/",
            headers=tenant_a_headers,
            json={
                "name": "x",
                "tool_type": "mcp",
                "config": {"command": "echo", "args": [], "env": {}},
            },
        ),
        await client.post(
            "/api/v1/tools/x/test",
            headers=tenant_a_headers,
            json={"tool_name": "x", "args": {}},
        ),
        await client.patch(
            "/api/v1/tools/x/configuration",
            headers=tenant_a_headers,
            json={"enabled": False},
        ),
        await client.delete("/api/v1/tools/x", headers=tenant_a_headers),
        await client.get("/api/v1/proactive-tasks", headers=tenant_a_headers),
        await client.post(
            "/api/v1/proactive-tasks",
            headers=tenant_a_headers,
            json={"cron_expr": "0 9 * * *", "prompt": "x", "channel_type": "feishu"},
        ),
        await client.get("/api/v1/proactive-tasks/runs", headers=tenant_a_headers),
        await client.delete("/api/v1/proactive-tasks/x", headers=tenant_a_headers),
        await client.get("/api/v1/memories/", headers=tenant_a_headers),
        await client.post(
            "/api/v1/memories/",
            headers=tenant_a_headers,
            json={"type": "user", "name": "x", "content": "x"},
        ),
        await client.get("/api/v1/memories/search?q=x", headers=tenant_a_headers),
        await client.post(
            "/api/v1/memories/merge",
            headers=tenant_a_headers,
            json={"task": "x"},
        ),
        await client.put(
            f"/api/v1/memories/{uuid.uuid4()}",
            headers=tenant_a_headers,
            json={"content": "x"},
        ),
        await client.delete(
            f"/api/v1/memories/{uuid.uuid4()}",
            headers=tenant_a_headers,
        ),
        await client.get("/api/v1/system/health", headers=tenant_a_headers),
        await client.get("/api/v1/system/metrics", headers=tenant_a_headers),
    ]
    assert all(response.status_code == 403 for response in requests)


async def test_provider_and_channel_are_tenant_isolated(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    await _promote(tenant_a_headers)
    await _promote(tenant_b_headers)
    provider = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "private-provider",
            "api_base": "https://provider.example/v1",
            "api_key": "tenant-a-key",
            "model": "tenant-a-model",
            "is_default": True,
        },
    )
    channel = await client.post(
        "/api/v1/channels",
        headers=tenant_a_headers,
        json={
            "channel_type": "feishu",
            "config": {"webhook_url": "https://open.feishu.cn/tenant-a-hook"},
        },
    )
    assert provider.status_code == 201, provider.text
    assert channel.status_code == 201, channel.text

    provider_list = await client.get("/api/v1/llm-providers/", headers=tenant_b_headers)
    channel_list = await client.get("/api/v1/channels", headers=tenant_b_headers)
    cross_test = await client.post(
        "/api/v1/llm-providers/private-provider/test", headers=tenant_b_headers
    )
    cross_channel_test = await client.post(
        "/api/v1/channels/feishu/test",
        headers=tenant_b_headers,
        json={"title": "x", "content": "x"},
    )
    assert provider_list.json()["items"] == []
    assert channel_list.json()["items"] == []
    assert cross_test.status_code == 404
    assert cross_channel_test.status_code == 404
