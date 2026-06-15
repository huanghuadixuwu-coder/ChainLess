"""W9 three-tenant concurrency and isolation proof."""

from __future__ import annotations

import asyncio
import json
import math
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import pytest
import redis.asyncio as aioredis
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update

from app.api.deps import _async_session_factory
from app.config import settings
from app.core.ops.health import collect_operational_health, write_worker_heartbeat
from app.core.proactive import cancel_task, list_tasks
from app.core.tools.mcp.manager import mcp_manager
from app.main import app_state
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_service import decode_token
from scripts.assert_test_environment import assert_isolated_test_environment

pytestmark = pytest.mark.asyncio

PRODUCT_TIMEOUT_SECONDS = 5.0
P95_LIMIT_MS = 1000.0


@dataclass
class TenantSession:
    index: int
    name: str
    username: str
    headers: dict[str, str]
    tenant_id: str
    user_id: str


@dataclass
class TenantResources:
    tenant: TenantSession
    conversation_id: str = ""
    artifact_id: str = ""
    provider_name: str = ""
    channel_label: str = ""
    agent_id: str = ""
    memory_id: str = ""
    skill_id: str = ""
    skill_trigger: str = ""
    proactive_task_id: str = ""
    mcp_server_name: str = ""
    markers: list[str] = field(default_factory=list)


@dataclass
class TimedResult:
    label: str
    latency_ms: float
    count_for_p95: bool = True


class DeterministicGateway:
    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        yield {
            "type": "text",
            "content": f"w9-chat-ok tenant={tenant_id} provider={provider}",
        }

    async def embed(self, provider, texts, *, tenant_id=None):
        return [[0.0] * 1536 for _ in texts]


class DummySandboxManager:
    pool_size = 0

    async def get_proxy_health(self):
        return {"pool_size": 0, "total_containers": 0}


async def test_three_tenants_concurrently_isolate_every_v1_resource_family(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await assert_isolated_test_environment()
    prefix = f"w9-{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(app_state, "llm_gateway", DeterministicGateway())
    monkeypatch.setattr(app_state, "sandbox_manager", DummySandboxManager())
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    await write_worker_heartbeat(redis_client)
    await redis_client.aclose()
    await collect_operational_health(DummySandboxManager())

    tenants = [await _register_admin_tenant(client, prefix, index) for index in range(3)]
    resources: list[TenantResources] = []
    timings: list[TimedResult] = []

    try:
        tenant_results = await asyncio.gather(
            *[_run_tenant_flow(client, tenant, prefix) for tenant in tenants]
        )
        for resource, tenant_timings in tenant_results:
            resources.append(resource)
            timings.extend(tenant_timings)
        timings.extend(await _run_latency_probe(client, resources))

        a, b, c = resources
        await _register_source_mcp(client, a, prefix)
        await _assert_cross_tenant_denials(client, source=a, other=b)
        await _assert_same_resource_names_do_not_cross_mutate(client, a, b, c)
        await _assert_metrics_and_errors_are_secret_free(client, resources)

        p95_ms = _p95([item.latency_ms for item in timings if item.count_for_p95])
        assert p95_ms < P95_LIMIT_MS, {
            "p95_ms": p95_ms,
            "slowest_counted": sorted(
                (
                    (item.label, round(item.latency_ms, 2))
                    for item in timings
                    if item.count_for_p95
                ),
                key=lambda item: item[1],
                reverse=True,
            )[:5],
        }
    finally:
        await _cleanup_resources(client, resources)
        await _delete_test_tenants(prefix)
        await _assert_no_test_residue(prefix)


async def _register_admin_tenant(
    client: AsyncClient,
    prefix: str,
    index: int,
) -> TenantSession:
    suffix = uuid.uuid4().hex
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": f"{prefix}-tenant-{index}-{suffix}",
            "username": f"admin-{index}-{suffix}",
            "password": "secret123",
        },
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    payload = decode_token(token)
    async with _async_session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == uuid.UUID(payload["user_id"]))
            .values(role="admin")
        )
        await db.commit()
    return TenantSession(
        index=index,
        name=f"{prefix}-tenant-{index}-{suffix}",
        username=f"admin-{index}-{suffix}",
        headers={"Authorization": f"Bearer {token}"},
        tenant_id=payload["tenant_id"],
        user_id=payload["user_id"],
    )


async def _run_tenant_flow(
    client: AsyncClient,
    tenant: TenantSession,
    prefix: str,
) -> tuple[TenantResources, list[TimedResult]]:
    resource = TenantResources(tenant=tenant)
    timings: list[TimedResult] = []

    async def timed(
        label: str,
        operation: Callable[[], Awaitable[None]],
        *,
        count_for_p95: bool = True,
    ) -> None:
        started = time.perf_counter()
        await asyncio.wait_for(operation(), timeout=PRODUCT_TIMEOUT_SECONDS)
        timings.append(
            TimedResult(
                f"tenant-{tenant.index}:{label}",
                (time.perf_counter() - started) * 1000,
                count_for_p95=count_for_p95,
            )
        )

    await asyncio.gather(
        timed(
            "conversation-upload-chat-artifact",
            lambda: _conversation_flow(client, resource, prefix),
            count_for_p95=False,
        ),
        timed("provider", lambda: _provider_flow(client, resource, prefix), count_for_p95=False),
        timed("channel", lambda: _channel_flow(client, resource, prefix), count_for_p95=False),
        timed("memory", lambda: _memory_flow(client, resource, prefix), count_for_p95=False),
        timed("tool-config", lambda: _tool_flow(client, resource), count_for_p95=False),
        timed("proactive", lambda: _proactive_flow(client, resource, prefix), count_for_p95=False),
    )
    await timed("agent", lambda: _agent_flow(client, resource, prefix), count_for_p95=False)
    await timed("skill", lambda: _skill_flow(client, resource, prefix), count_for_p95=False)
    await timed("system-health", lambda: _get_and_assert(client, resource, "/api/v1/system/health"))
    await timed(
        "system-metrics",
        lambda: _get_and_assert(client, resource, "/api/v1/system/metrics"),
        count_for_p95=False,
    )
    await timed(
        "eval-suites",
        lambda: _get_and_assert(client, resource, "/api/v1/eval/suites?limit=1"),
        count_for_p95=False,
    )
    await timed(
        "audit-list",
        lambda: _get_and_assert(client, resource, "/api/v1/audit/?limit=5"),
        count_for_p95=False,
    )

    return resource, timings


async def _run_latency_probe(
    client: AsyncClient,
    resources: list[TenantResources],
) -> list[TimedResult]:
    timings: list[TimedResult] = []

    async def timed(resource: TenantResources, label: str, path: str) -> None:
        started = time.perf_counter()
        response = await asyncio.wait_for(
            client.get(path, headers=resource.tenant.headers),
            timeout=PRODUCT_TIMEOUT_SECONDS,
        )
        _assert_ok(response, 200)
        timings.append(
            TimedResult(
                f"tenant-{resource.tenant.index}:latency:{label}",
                (time.perf_counter() - started) * 1000,
            )
        )

    probes = [
        ("auth-me", "/api/v1/auth/me"),
        ("conversations", "/api/v1/conversations/?limit=1"),
        ("providers", "/api/v1/llm-providers/?limit=1"),
        ("agents", "/api/v1/agents/?limit=1"),
        ("memories", "/api/v1/memories/?limit=1"),
        ("skills", "/api/v1/skills/?limit=1"),
        ("tools", "/api/v1/tools/?limit=200"),
        ("proactive", "/api/v1/proactive-tasks?limit=1"),
        ("health", "/api/v1/system/health"),
    ]
    await asyncio.gather(
        *[
            timed(resource, label, path)
            for resource in resources
            for label, path in probes
        ]
    )
    return timings


async def _conversation_flow(
    client: AsyncClient,
    resource: TenantResources,
    prefix: str,
) -> None:
    marker = f"{prefix}-chat-{resource.tenant.index}"
    created = await client.post(
        "/api/v1/conversations/",
        headers=resource.tenant.headers,
        json={"title": marker},
    )
    _assert_ok(created, 200)
    resource.conversation_id = created.json()["id"]
    resource.markers.append(marker)

    uploaded = await client.post(
        "/api/v1/uploads/",
        headers=resource.tenant.headers,
        data={"conversation_id": resource.conversation_id},
        files={"file": (f"{marker}.txt", f"{marker} private upload\n".encode(), "text/plain")},
    )
    _assert_ok(uploaded, 201)
    resource.artifact_id = uploaded.json()["artifact"]["id"]

    chatted = await client.post(
        f"/api/v1/conversations/{resource.conversation_id}/chat",
        headers=resource.tenant.headers,
        json={
            "content": f"use attachment for {marker}",
            "attachment_artifact_ids": [resource.artifact_id],
        },
    )
    _assert_ok(chatted, 200)
    events = _parse_sse(chatted.text)
    text = "".join(data.get("delta", "") for name, data in events if name == "text")
    assert "w9-chat-ok" in text

    listed = await client.get(
        f"/api/v1/artifacts/?conversation_id={resource.conversation_id}",
        headers=resource.tenant.headers,
    )
    _assert_ok(listed, 200)
    assert listed.json()["items"][0]["id"] == resource.artifact_id


async def _provider_flow(
    client: AsyncClient,
    resource: TenantResources,
    prefix: str,
) -> None:
    resource.provider_name = f"{prefix}-provider-{resource.tenant.index}"
    created = await client.post(
        "/api/v1/llm-providers/",
        headers=resource.tenant.headers,
        json={
            "name": resource.provider_name,
            "api_base": f"https://provider-{resource.tenant.index}.example/v1",
            "api_key": f"sk-{prefix}-{resource.tenant.index}",
            "model": "w9-model",
            "embedding_model": "embedding-3",
            "is_default": True,
        },
    )
    _assert_ok(created, 201)
    listed = await client.get("/api/v1/llm-providers/?limit=100", headers=resource.tenant.headers)
    _assert_ok(listed, 200)
    assert [item for item in listed.json()["items"] if item["name"] == resource.provider_name]
    assert f"sk-{prefix}" not in listed.text


async def _channel_flow(
    client: AsyncClient,
    resource: TenantResources,
    prefix: str,
) -> None:
    resource.channel_label = f"{prefix}-channel-{resource.tenant.index}"
    created = await client.post(
        "/api/v1/channels",
        headers=resource.tenant.headers,
        json={
            "channel_type": "feishu",
            "config": {
                "label": resource.channel_label,
                "webhook_url": f"https://feishu.example/{prefix}/{resource.tenant.index}",
                "secret": f"channel-secret-{prefix}-{resource.tenant.index}",
            },
            "enabled": True,
        },
    )
    _assert_ok(created, 201)
    assert created.json()["config"]["label"] == resource.channel_label
    assert "channel-secret" not in created.text


async def _agent_flow(
    client: AsyncClient,
    resource: TenantResources,
    prefix: str,
) -> None:
    created = await client.post(
        "/api/v1/agents/",
        headers=resource.tenant.headers,
        json={
            "name": f"{prefix}-agent-{resource.tenant.index}",
            "system_prompt": f"{prefix} active prompt {resource.tenant.index}",
            "is_active": True,
        },
    )
    _assert_ok(created, 200)
    resource.agent_id = created.json()["id"]


async def _memory_flow(
    client: AsyncClient,
    resource: TenantResources,
    prefix: str,
) -> None:
    memory_name = f"{prefix}-memory-{resource.tenant.index}"
    created = await client.post(
        "/api/v1/memories/",
        headers=resource.tenant.headers,
        json={
            "type": "user",
            "name": memory_name,
            "content": f"{prefix} private memory {resource.tenant.index}",
            "tags": [prefix, f"tenant-{resource.tenant.index}"],
        },
    )
    _assert_ok(created, 201)
    resource.memory_id = created.json()["id"]
    resource.markers.append(memory_name)


async def _skill_flow(
    client: AsyncClient,
    resource: TenantResources,
    prefix: str,
) -> None:
    resource.skill_trigger = f"{prefix}-trigger-{resource.tenant.index}"
    created = await client.post(
        "/api/v1/skills/",
        headers=resource.tenant.headers,
        json={
            "name": f"{prefix}-skill-{resource.tenant.index}",
            "description": "W9 isolation skill",
            "trigger_terms": [resource.skill_trigger],
            "enabled": True,
        },
    )
    _assert_ok(created, 201)
    resource.skill_id = created.json()["id"]


async def _tool_flow(client: AsyncClient, resource: TenantResources) -> None:
    enabled = resource.tenant.index != 0
    risk = "safe" if resource.tenant.index == 1 else "risky"
    updated = await client.patch(
        "/api/v1/tools/shell_exec/configuration",
        headers=resource.tenant.headers,
        json={"enabled": enabled, "risk_override": risk},
    )
    _assert_ok(updated, 200)
    listed = await client.get("/api/v1/tools/?limit=200", headers=resource.tenant.headers)
    _assert_ok(listed, 200)
    shell = next(item for item in listed.json()["items"] if item["function"]["name"] == "shell_exec")
    assert shell["enabled"] is enabled
    assert shell["risk"] == risk


async def _proactive_flow(
    client: AsyncClient,
    resource: TenantResources,
    prefix: str,
) -> None:
    prompt = f"{prefix}-proactive-{resource.tenant.index}"
    created = await client.post(
        "/api/v1/proactive-tasks",
        headers=resource.tenant.headers,
        json={
            "type": "cron",
            "cron_expr": "0 9 * * *",
            "agent_id": "default",
            "prompt": prompt,
            "channel_type": "feishu",
            "enabled": False,
            "authorized_tools": ["weather_get"],
        },
    )
    _assert_ok(created, 201)
    resource.proactive_task_id = created.json()["task_id"]
    resource.markers.append(prompt)


async def _get_and_assert(
    client: AsyncClient,
    resource: TenantResources,
    path: str,
) -> None:
    response = await client.get(path, headers=resource.tenant.headers)
    _assert_ok(response, 200)
    if path == "/api/v1/system/metrics":
        assert "chainless_db_up" in response.text


async def _register_source_mcp(
    client: AsyncClient,
    resource: TenantResources,
    prefix: str,
) -> None:
    resource.mcp_server_name = f"{prefix}-mcp-{resource.tenant.index}"
    registered = await client.post(
        "/api/v1/tools/",
        headers=resource.tenant.headers,
        json={
            "name": resource.mcp_server_name,
            "tool_type": "mcp",
            "config": {
                "command": "python",
                "args": ["scripts/mcp_echo_server.py"],
                "env": {},
            },
        },
    )
    _assert_ok(registered, 201)
    tool_name = f"mcp__{resource.mcp_server_name}__echo"
    assert registered.json()["tools"][0]["function"]["name"] == tool_name
    tested = await client.post(
        f"/api/v1/tools/{resource.mcp_server_name}/test",
        headers=resource.tenant.headers,
        json={"tool_name": "echo", "args": {"text": "w9-mcp-owner"}},
    )
    _assert_ok(tested, 200)


async def _assert_cross_tenant_denials(
    client: AsyncClient,
    *,
    source: TenantResources,
    other: TenantResources,
) -> None:
    headers = other.tenant.headers
    source_markers = [source.tenant.name, *source.markers]
    checks = [
        await client.get(f"/api/v1/conversations/{source.conversation_id}", headers=headers),
        await client.delete(f"/api/v1/conversations/{source.conversation_id}", headers=headers),
        await client.get(
            f"/api/v1/artifacts/?conversation_id={source.conversation_id}",
            headers=headers,
        ),
        await client.get(f"/api/v1/artifacts/{source.artifact_id}", headers=headers),
        await client.get(f"/api/v1/llm-providers/{source.provider_name}", headers=headers),
        await client.put(
            f"/api/v1/llm-providers/{source.provider_name}",
            headers=headers,
            json={"model": "cross-tenant-model"},
        ),
        await client.post(
            f"/api/v1/llm-providers/{source.provider_name}/default",
            headers=headers,
        ),
        await client.delete(f"/api/v1/llm-providers/{source.provider_name}", headers=headers),
        await client.get(f"/api/v1/agents/{source.agent_id}", headers=headers),
        await client.put(
            f"/api/v1/agents/{source.agent_id}",
            headers=headers,
            json={"name": "cross-tenant-agent"},
        ),
        await client.delete(f"/api/v1/agents/{source.agent_id}", headers=headers),
        await client.put(
            f"/api/v1/memories/{source.memory_id}",
            headers=headers,
            json={"content": "cross tenant takeover"},
        ),
        await client.get(f"/api/v1/skills/{source.skill_id}", headers=headers),
        await client.put(
            f"/api/v1/skills/{source.skill_id}",
            headers=headers,
            json={"name": "cross-tenant-skill"},
        ),
        await client.delete(f"/api/v1/skills/{source.skill_id}", headers=headers),
        await client.delete(f"/api/v1/proactive-tasks/{source.proactive_task_id}", headers=headers),
        await client.post(
            f"/api/v1/tools/{source.mcp_server_name}/test",
            headers=headers,
            json={"tool_name": "echo", "args": {"text": "cross-mcp"}},
        ),
        await client.delete(f"/api/v1/tools/{source.mcp_server_name}", headers=headers),
    ]
    for response in checks:
        assert response.status_code == 404, response.text
        assert not any(marker in response.text for marker in source_markers)
    source_checks = [
        await client.get(
            f"/api/v1/llm-providers/{source.provider_name}",
            headers=source.tenant.headers,
        ),
        await client.get(f"/api/v1/agents/{source.agent_id}", headers=source.tenant.headers),
        await client.get(f"/api/v1/skills/{source.skill_id}", headers=source.tenant.headers),
    ]
    for response in source_checks:
        _assert_ok(response, 200)

    own_conversation = await client.post(
        "/api/v1/conversations/",
        headers=headers,
        json={"title": f"{other.tenant.name}-attachment-negative"},
    )
    _assert_ok(own_conversation, 200)
    cross_attach = await client.post(
        f"/api/v1/conversations/{own_conversation.json()['id']}/chat",
        headers=headers,
        json={
            "content": "try source artifact",
            "attachment_artifact_ids": [source.artifact_id],
        },
    )
    assert cross_attach.status_code == 404
    assert cross_attach.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"

    listed_tools = await client.get("/api/v1/tools/?limit=200", headers=headers)
    _assert_ok(listed_tools, 200)
    assert f"mcp__{source.mcp_server_name}__echo" not in listed_tools.text

    skill_match = await client.post(
        "/api/v1/skills/match",
        headers=headers,
        json={"text": f"please run {source.skill_trigger}"},
    )
    _assert_ok(skill_match, 200)
    assert skill_match.json()["items"] == []

    proactive_list = await client.get("/api/v1/proactive-tasks?limit=100", headers=headers)
    _assert_ok(proactive_list, 200)
    assert source.proactive_task_id not in proactive_list.text
    assert not any(marker in proactive_list.text for marker in source.markers)


async def _assert_same_resource_names_do_not_cross_mutate(
    client: AsyncClient,
    a: TenantResources,
    b: TenantResources,
    c: TenantResources,
) -> None:
    b_channel = await client.get("/api/v1/channels/feishu", headers=b.tenant.headers)
    _assert_ok(b_channel, 200)
    assert b_channel.json()["config"]["label"] == b.channel_label
    assert a.channel_label not in b_channel.text

    a_tools = await client.get("/api/v1/tools/?limit=200", headers=a.tenant.headers)
    b_tools = await client.get("/api/v1/tools/?limit=200", headers=b.tenant.headers)
    c_tools = await client.get("/api/v1/tools/?limit=200", headers=c.tenant.headers)
    for response in (a_tools, b_tools, c_tools):
        _assert_ok(response, 200)
    a_shell = _tool_by_name(a_tools.json()["items"], "shell_exec")
    b_shell = _tool_by_name(b_tools.json()["items"], "shell_exec")
    c_shell = _tool_by_name(c_tools.json()["items"], "shell_exec")
    assert a_shell["enabled"] is False
    assert b_shell["enabled"] is True
    assert b_shell["risk"] == "safe"
    assert c_shell["enabled"] is True
    assert c_shell["risk"] == "risky"


async def _assert_metrics_and_errors_are_secret_free(
    client: AsyncClient,
    resources: list[TenantResources],
) -> None:
    for resource in resources:
        metrics = await client.get("/api/v1/system/metrics", headers=resource.tenant.headers)
        _assert_ok(metrics, 200)
        forbidden = [
            resource.tenant.name,
            resource.tenant.tenant_id,
            resource.tenant.user_id,
            resource.provider_name,
            resource.channel_label,
            "channel-secret",
            "sk-",
        ]
        assert not any(value and value in metrics.text for value in forbidden)


async def _cleanup_resources(
    client: AsyncClient,
    resources: list[TenantResources],
) -> None:
    for resource in resources:
        headers = resource.tenant.headers
        if resource.mcp_server_name:
            await mcp_manager.unregister(resource.mcp_server_name, resource.tenant.tenant_id)
        for task in await list_tasks(resource.tenant.tenant_id):
            await cancel_task(task.task_id, resource.tenant.tenant_id)
        if resource.proactive_task_id:
            await client.delete(f"/api/v1/proactive-tasks/{resource.proactive_task_id}", headers=headers)
        if resource.conversation_id:
            await client.delete(f"/api/v1/conversations/{resource.conversation_id}?purge=true", headers=headers)
        if resource.memory_id:
            await client.delete(f"/api/v1/memories/{resource.memory_id}", headers=headers)
        if resource.skill_id:
            await client.delete(f"/api/v1/skills/{resource.skill_id}", headers=headers)
        if resource.agent_id:
            await client.delete(f"/api/v1/agents/{resource.agent_id}", headers=headers)
        if resource.provider_name:
            await client.delete(f"/api/v1/llm-providers/{resource.provider_name}", headers=headers)


async def _delete_test_tenants(prefix: str) -> None:
    await assert_isolated_test_environment()
    async with _async_session_factory() as db:
        tenant_ids = list(
            (
                await db.execute(
                    select(Tenant.id).where(Tenant.name.like(f"{prefix}-%"))
                )
            ).scalars()
        )
        for tenant_id in tenant_ids:
            _safe_remove_test_dir(Path(settings.memory_base_path) / str(tenant_id))
            _safe_remove_test_dir(Path(settings.artifact_base_path) / str(tenant_id))
        if tenant_ids:
            await db.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
            await db.commit()
    for task in await list_tasks():
        if prefix in (task.prompt or ""):
            await cancel_task(task.task_id, task.tenant_id)


async def _assert_no_test_residue(prefix: str) -> None:
    async with _async_session_factory() as db:
        remaining = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Tenant)
                    .where(Tenant.name.like(f"{prefix}-%"))
                )
            ).scalar()
            or 0
        )
    assert remaining == 0
    assert not any(prefix in (task.prompt or "") for task in await list_tasks())


def _safe_remove_test_dir(path: Path) -> None:
    resolved = path.resolve()
    allowed_roots = [
        Path(settings.memory_base_path).resolve(),
        Path(settings.artifact_base_path).resolve(),
    ]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise RuntimeError(f"Refusing to remove path outside test roots: {resolved}")
    if path.exists():
        shutil.rmtree(path)


def _assert_ok(response, status_code: int) -> None:
    assert response.status_code == status_code, response.text
    assert response.status_code < 500


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in text.strip().split("\n\n"):
        event_name = ""
        data: dict = {}
        for line in frame.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        if event_name:
            events.append((event_name, data))
    return events


def _tool_by_name(items: list[dict], name: str) -> dict:
    return next(item for item in items if item["function"]["name"] == name)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
    return ordered[index]
