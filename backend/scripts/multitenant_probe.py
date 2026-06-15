"""HTTP W9 multi-tenant runtime probe for the isolated Docker test stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import shutil
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import delete, func, select, update

from app.api.deps import _async_session_factory
from app.config import settings
from app.core.proactive import cancel_task, list_tasks
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_service import decode_token
from scripts.assert_test_environment import assert_isolated_test_environment

PRODUCT_TIMEOUT_SECONDS = 8.0
P95_LIMIT_MS = 1000.0


@dataclass
class ProbeTenant:
    index: int
    name: str
    username: str
    token: str
    tenant_id: str
    user_id: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@dataclass
class ProbeResources:
    tenant: ProbeTenant
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


class ProbeFailure(Exception):
    pass


class MockRuntimeServer:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.calls: list[dict[str, Any]] = []
        self._server = ThreadingHTTPServer(("0.0.0.0", 0), self._handler_class())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def host_ip(self) -> str:
        return socket.gethostbyname(socket.gethostname())

    @property
    def openai_base_url(self) -> str:
        return f"http://{self.host_ip}:{self.port}/v1"

    @property
    def mcp_url(self) -> str:
        return f"http://{self.host_ip}:{self.port}/mcp"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def _handler_class(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):  # noqa: D401
                return

            def do_GET(self):  # noqa: N802
                if self.path.rstrip("/") == "/mcp/tools":
                    self._send_json(
                        {
                            "tools": [
                                {
                                    "name": "echo",
                                    "description": "Echo text for W9 probe.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"text": {"type": "string"}},
                                    },
                                }
                            ]
                        }
                    )
                    return
                self._send_json({"error": "not found"}, status=404)

            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("content-length", "0") or "0"))
                body = json.loads(raw.decode() or "{}")
                outer.calls.append({"path": self.path, "body": body})
                if self.path.endswith("/embeddings"):
                    self._send_json(
                        {
                            "object": "list",
                            "data": [
                                {
                                    "object": "embedding",
                                    "index": 0,
                                    "embedding": [0.0] * 1536,
                                }
                            ],
                            "model": body.get("model") or "embedding-3",
                        }
                    )
                    return
                if self.path.endswith("/chat/completions"):
                    content = f"w9-probe-chat-ok:{outer.prefix}"
                    if body.get("stream"):
                        payload = _openai_stream_payload(content, body.get("model") or "w9-probe")
                        self._send_bytes(payload.encode(), "text/event-stream")
                    else:
                        self._send_json(
                            {
                                "id": "chatcmpl-w9-probe",
                                "object": "chat.completion",
                                "created": int(time.time()),
                                "model": body.get("model") or "w9-probe",
                                "choices": [
                                    {
                                        "index": 0,
                                        "message": {"role": "assistant", "content": content},
                                        "finish_reason": "stop",
                                    }
                                ],
                            }
                        )
                    return
                if self.path.rstrip("/") == "/mcp/call":
                    self._send_json({"content": [body.get("arguments", {}).get("text", "")]})
                    return
                self._send_json({"error": "not found"}, status=404)

            def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
                self._send_bytes(
                    json.dumps(payload, separators=(",", ":")).encode(),
                    "application/json",
                    status,
                )

            def _send_bytes(
                self,
                payload: bytes,
                content_type: str,
                status: int = 200,
            ) -> None:
                self.send_response(status)
                self.send_header("content-type", content_type)
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return Handler


def _openai_stream_payload(content: str, model: str) -> str:
    base = {
        "id": "chatcmpl-w9-probe",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
    }
    return "\n\n".join(
        [
            "data: "
            + json.dumps(
                {**base, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]}
            ),
            "data: "
            + json.dumps(
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            ),
            "data: [DONE]",
            "",
        ]
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--tenants", type=int, default=3)
    parser.add_argument("--parallel-per-tenant", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.tenants < 3:
        raise ProbeFailure("--tenants must be at least 3")
    if args.parallel_per_tenant < 5:
        raise ProbeFailure("--parallel-per-tenant must be at least 5")

    await assert_isolated_test_environment()
    base_url = args.base_url.rstrip("/")
    prefix = f"w9-probe-{uuid.uuid4().hex[:12]}"
    mock = MockRuntimeServer(prefix)
    mock.start()

    checks: list[str] = []
    failures: list[str] = []
    timings: list[tuple[str, float, bool]] = []
    resources: list[ProbeResources] = []
    tenants: list[ProbeTenant] = []

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        try:
            await _wait_for_server(client)
            tenants = [
                await _register_admin_tenant(client, prefix, index)
                for index in range(args.tenants)
            ]
            for tenant in tenants:
                resource = ProbeResources(tenant=tenant)
                await _create_provider(client, resource, prefix, mock.openai_base_url)
                resources.append(resource)

            tenant_results = await asyncio.gather(
                *[
                    _tenant_runtime_flow(client, resource, prefix)
                    for resource in resources
                ]
            )
            for tenant_checks, tenant_timings in tenant_results:
                checks.extend(tenant_checks)
                timings.extend(tenant_timings)

            latency_results = await _latency_probe(client, resources)
            checks.extend([item[0] for item in latency_results])
            timings.extend(latency_results)

            checks.extend(await _register_and_check_mcp(client, resources[0], resources[1], mock.mcp_url))
            checks.extend(await _cross_tenant_matrix(client, resources[0], resources[1]))
            checks.extend(await _metrics_are_secret_free(client, resources, prefix))
        except Exception as exc:
            failures.append(str(exc))
        finally:
            cleanup_failures = await _cleanup(client, resources, prefix)
            failures.extend(cleanup_failures)
            mock.close()

    counted = [latency for _, latency, count in timings if count]
    p95_ms = _p95(counted)
    if p95_ms >= P95_LIMIT_MS:
        failures.append(f"p95 latency {p95_ms:.2f}ms exceeded {P95_LIMIT_MS:.0f}ms")

    result = {
        "ok": not failures,
        "prefix": prefix,
        "tenant_count": len(tenants),
        "checks": checks,
        "check_count": len(checks),
        "p95_ms": round(p95_ms, 2),
        "slowest": sorted(
            [
                {"label": label, "latency_ms": round(latency, 2)}
                for label, latency, count in timings
                if count
            ],
            key=lambda item: item["latency_ms"],
            reverse=True,
        )[:5],
        "mock_calls": len(mock.calls),
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result["ok"] else 1


async def _wait_for_server(client: httpx.AsyncClient) -> None:
    deadline = time.monotonic() + 30
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = await client.get("/api/v1/health")
            if response.status_code == 200:
                return
            last_error = response.text
        except Exception as exc:
            last_error = str(exc)
        await asyncio.sleep(1)
    raise ProbeFailure(f"backend-test-server did not become healthy: {last_error}")


async def _register_admin_tenant(
    client: httpx.AsyncClient,
    prefix: str,
    index: int,
) -> ProbeTenant:
    suffix = uuid.uuid4().hex
    tenant_name = f"{prefix}-tenant-{index}-{suffix}"
    username = f"admin-{index}-{suffix}"
    response = await client.post(
        "/api/v1/auth/register",
        json={"tenant_name": tenant_name, "username": username, "password": "secret123"},
    )
    _expect(response, 200, "register tenant")
    token = response.json()["access_token"]
    payload = decode_token(token)
    async with _async_session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == uuid.UUID(payload["user_id"]))
            .values(role="admin")
        )
        await db.commit()
    return ProbeTenant(
        index=index,
        name=tenant_name,
        username=username,
        token=token,
        tenant_id=payload["tenant_id"],
        user_id=payload["user_id"],
    )


async def _tenant_runtime_flow(
    client: httpx.AsyncClient,
    resource: ProbeResources,
    prefix: str,
) -> tuple[list[str], list[tuple[str, float, bool]]]:
    checks: list[str] = []
    timings: list[tuple[str, float, bool]] = []

    async def timed(label: str, fn: Callable[[], Awaitable[str]], count: bool = False) -> None:
        started = time.perf_counter()
        check = await asyncio.wait_for(fn(), timeout=PRODUCT_TIMEOUT_SECONDS)
        timings.append((f"tenant-{resource.tenant.index}:{label}", (time.perf_counter() - started) * 1000, count))
        checks.append(check)

    await asyncio.gather(
        timed("chat-upload-artifact", lambda: _conversation_chat(client, resource, prefix)),
        timed("memory", lambda: _memory(client, resource, prefix)),
        timed("channel", lambda: _channel(client, resource, prefix)),
        timed("agent", lambda: _agent(client, resource, prefix)),
        timed("tool-config", lambda: _tool_config(client, resource)),
        timed("proactive", lambda: _proactive(client, resource, prefix)),
        timed("skill", lambda: _skill(client, resource, prefix)),
    )
    return checks, timings


async def _create_provider(
    client: httpx.AsyncClient,
    resource: ProbeResources,
    prefix: str,
    api_base: str,
) -> str:
    resource.provider_name = f"{prefix}-provider-{resource.tenant.index}"
    response = await client.post(
        "/api/v1/llm-providers/",
        headers=resource.tenant.headers,
        json={
            "name": resource.provider_name,
            "api_base": api_base,
            "api_key": f"sk-{prefix}-{resource.tenant.index}",
            "model": "w9-probe-model",
            "embedding_model": "embedding-3",
            "is_default": True,
        },
    )
    _expect(response, 201, "provider create")
    return "provider:create"


async def _conversation_chat(
    client: httpx.AsyncClient,
    resource: ProbeResources,
    prefix: str,
) -> str:
    marker = f"{prefix}-chat-{resource.tenant.index}"
    created = await client.post(
        "/api/v1/conversations/",
        headers=resource.tenant.headers,
        json={"title": marker},
    )
    _expect(created, 200, "conversation create")
    resource.conversation_id = created.json()["id"]
    resource.markers.append(marker)
    uploaded = await client.post(
        "/api/v1/uploads/",
        headers=resource.tenant.headers,
        data={"conversation_id": resource.conversation_id},
        files={"file": (f"{marker}.txt", f"{marker} private upload\n", "text/plain")},
    )
    _expect(uploaded, 201, "upload")
    resource.artifact_id = uploaded.json()["artifact"]["id"]
    chatted = await client.post(
        f"/api/v1/conversations/{resource.conversation_id}/chat",
        headers=resource.tenant.headers,
        json={
            "content": f"use attachment {marker}",
            "attachment_artifact_ids": [resource.artifact_id],
        },
    )
    _expect(chatted, 200, "chat")
    if "w9-probe-chat-ok" not in chatted.text:
        raise ProbeFailure("chat did not use mock provider")
    return "chat:upload-artifact"


async def _memory(client: httpx.AsyncClient, resource: ProbeResources, prefix: str) -> str:
    response = await client.post(
        "/api/v1/memories/",
        headers=resource.tenant.headers,
        json={
            "type": "user",
            "name": f"{prefix}-memory-{resource.tenant.index}",
            "content": f"{prefix} memory {resource.tenant.index}",
            "tags": [prefix],
        },
    )
    _expect(response, 201, "memory create")
    resource.memory_id = response.json()["id"]
    return "memory:create"


async def _channel(client: httpx.AsyncClient, resource: ProbeResources, prefix: str) -> str:
    resource.channel_label = f"{prefix}-channel-{resource.tenant.index}"
    response = await client.post(
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
    _expect(response, 201, "channel create")
    if "channel-secret" in response.text:
        raise ProbeFailure("channel secret leaked")
    return "channel:create"


async def _agent(client: httpx.AsyncClient, resource: ProbeResources, prefix: str) -> str:
    response = await client.post(
        "/api/v1/agents/",
        headers=resource.tenant.headers,
        json={"name": f"{prefix}-agent-{resource.tenant.index}", "is_active": True},
    )
    _expect(response, 200, "agent create")
    resource.agent_id = response.json()["id"]
    return "agent:create"


async def _tool_config(client: httpx.AsyncClient, resource: ProbeResources) -> str:
    response = await client.patch(
        "/api/v1/tools/shell_exec/configuration",
        headers=resource.tenant.headers,
        json={"enabled": resource.tenant.index != 0, "risk_override": "safe"},
    )
    _expect(response, 200, "tool config")
    return "tool:config"


async def _proactive(client: httpx.AsyncClient, resource: ProbeResources, prefix: str) -> str:
    prompt = f"{prefix}-proactive-{resource.tenant.index}"
    response = await client.post(
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
    _expect(response, 201, "proactive create")
    resource.proactive_task_id = response.json()["task_id"]
    resource.markers.append(prompt)
    return "proactive:create"


async def _skill(client: httpx.AsyncClient, resource: ProbeResources, prefix: str) -> str:
    resource.skill_trigger = f"{prefix}-trigger-{resource.tenant.index}"
    response = await client.post(
        "/api/v1/skills/",
        headers=resource.tenant.headers,
        json={
            "name": f"{prefix}-skill-{resource.tenant.index}",
            "trigger_terms": [resource.skill_trigger],
            "enabled": True,
        },
    )
    _expect(response, 201, "skill create")
    resource.skill_id = response.json()["id"]
    return "skill:create"


async def _latency_probe(
    client: httpx.AsyncClient,
    resources: list[ProbeResources],
) -> list[tuple[str, float, bool]]:
    probes = [
        ("auth-me", "/api/v1/auth/me"),
        ("conversations", "/api/v1/conversations/?limit=1"),
        ("providers", "/api/v1/llm-providers/?limit=1"),
        ("tools", "/api/v1/tools/?limit=200"),
        ("proactive", "/api/v1/proactive-tasks?limit=1"),
        ("health", "/api/v1/system/health"),
    ]
    timings: list[tuple[str, float, bool]] = []

    async def timed(resource: ProbeResources, label: str, path: str) -> None:
        started = time.perf_counter()
        response = await client.get(path, headers=resource.tenant.headers)
        _expect(response, 200, f"latency {label}")
        timings.append((f"tenant-{resource.tenant.index}:latency:{label}", (time.perf_counter() - started) * 1000, True))

    await asyncio.gather(
        *[
            timed(resource, label, path)
            for resource in resources
            for label, path in probes
        ]
    )
    return timings


async def _register_and_check_mcp(
    client: httpx.AsyncClient,
    source: ProbeResources,
    other: ProbeResources,
    mcp_url: str,
) -> list[str]:
    source.mcp_server_name = f"mcp-{uuid.uuid4().hex[:10]}"
    registered = await client.post(
        "/api/v1/tools/",
        headers=source.tenant.headers,
        json={
            "name": source.mcp_server_name,
            "tool_type": "mcp",
            "config": {"transport": "http", "url": mcp_url},
        },
    )
    _expect(registered, 201, "mcp register")
    tool_name = f"mcp__{source.mcp_server_name}__echo"
    tested = await client.post(
        f"/api/v1/tools/{source.mcp_server_name}/test",
        headers=source.tenant.headers,
        json={"tool_name": "echo", "args": {"text": "mcp-ok"}},
    )
    _expect(tested, 200, "mcp source test")
    other_list = await client.get("/api/v1/tools/?limit=200", headers=other.tenant.headers)
    _expect(other_list, 200, "mcp other list")
    if tool_name in other_list.text:
        raise ProbeFailure("MCP tool leaked across tenants")
    other_test = await client.post(
        f"/api/v1/tools/{source.mcp_server_name}/test",
        headers=other.tenant.headers,
        json={"tool_name": "echo", "args": {"text": "cross"}},
    )
    _expect(other_test, 404, "mcp other test denied")
    return ["mcp:tenant-scoped-register-test-list-deny"]


async def _cross_tenant_matrix(
    client: httpx.AsyncClient,
    source: ProbeResources,
    other: ProbeResources,
) -> list[str]:
    checks = [
        await client.get(f"/api/v1/conversations/{source.conversation_id}", headers=other.tenant.headers),
        await client.get(f"/api/v1/artifacts/{source.artifact_id}", headers=other.tenant.headers),
        await client.get(f"/api/v1/llm-providers/{source.provider_name}", headers=other.tenant.headers),
        await client.put(
            f"/api/v1/llm-providers/{source.provider_name}",
            headers=other.tenant.headers,
            json={"model": "cross-tenant-model"},
        ),
        await client.post(
            f"/api/v1/llm-providers/{source.provider_name}/default",
            headers=other.tenant.headers,
        ),
        await client.delete(
            f"/api/v1/llm-providers/{source.provider_name}",
            headers=other.tenant.headers,
        ),
        await client.get(f"/api/v1/agents/{source.agent_id}", headers=other.tenant.headers),
        await client.put(
            f"/api/v1/agents/{source.agent_id}",
            headers=other.tenant.headers,
            json={"name": "cross-tenant-agent"},
        ),
        await client.delete(f"/api/v1/agents/{source.agent_id}", headers=other.tenant.headers),
        await client.put(
            f"/api/v1/memories/{source.memory_id}",
            headers=other.tenant.headers,
            json={"content": "takeover"},
        ),
        await client.get(f"/api/v1/skills/{source.skill_id}", headers=other.tenant.headers),
        await client.put(
            f"/api/v1/skills/{source.skill_id}",
            headers=other.tenant.headers,
            json={"name": "cross-tenant-skill"},
        ),
        await client.delete(f"/api/v1/skills/{source.skill_id}", headers=other.tenant.headers),
        await client.delete(f"/api/v1/proactive-tasks/{source.proactive_task_id}", headers=other.tenant.headers),
    ]
    for response in checks:
        _expect(response, 404, "cross tenant denied")
        if source.tenant.name in response.text:
            raise ProbeFailure("cross-tenant error leaked source tenant name")
    source_checks = [
        await client.get(
            f"/api/v1/llm-providers/{source.provider_name}",
            headers=source.tenant.headers,
        ),
        await client.get(f"/api/v1/agents/{source.agent_id}", headers=source.tenant.headers),
        await client.get(f"/api/v1/skills/{source.skill_id}", headers=source.tenant.headers),
    ]
    for response in source_checks:
        _expect(response, 200, "source resource survived cross-tenant mutation denial")
    return ["cross-tenant:conversation-artifact-provider-agent-memory-skill-proactive-mutations-denied"]


async def _metrics_are_secret_free(
    client: httpx.AsyncClient,
    resources: list[ProbeResources],
    prefix: str,
) -> list[str]:
    for resource in resources:
        response = await client.get("/api/v1/system/metrics", headers=resource.tenant.headers)
        _expect(response, 200, "metrics")
        forbidden = [
            prefix,
            resource.tenant.tenant_id,
            resource.tenant.user_id,
            resource.provider_name,
            resource.channel_label,
            "sk-",
            "channel-secret",
        ]
        if any(value and value in response.text for value in forbidden):
            raise ProbeFailure("metrics leaked tenant data or secret material")
    return ["metrics:secret-free"]


async def _cleanup(
    client: httpx.AsyncClient,
    resources: list[ProbeResources],
    prefix: str,
) -> list[str]:
    failures: list[str] = []
    for resource in resources:
        for task in await list_tasks(resource.tenant.tenant_id):
            await cancel_task(task.task_id, resource.tenant.tenant_id)
        calls = []
        if resource.mcp_server_name:
            calls.append(("DELETE", f"/api/v1/tools/{resource.mcp_server_name}"))
        if resource.conversation_id:
            calls.append(("DELETE", f"/api/v1/conversations/{resource.conversation_id}?purge=true"))
        if resource.memory_id:
            calls.append(("DELETE", f"/api/v1/memories/{resource.memory_id}"))
        if resource.skill_id:
            calls.append(("DELETE", f"/api/v1/skills/{resource.skill_id}"))
        if resource.agent_id:
            calls.append(("DELETE", f"/api/v1/agents/{resource.agent_id}"))
        if resource.provider_name:
            calls.append(("DELETE", f"/api/v1/llm-providers/{resource.provider_name}"))
        for method, path in calls:
            try:
                await client.request(method, path, headers=resource.tenant.headers)
            except Exception as exc:
                failures.append(f"cleanup {method} {path}: {exc}")
    try:
        await _delete_test_tenants(prefix)
        await _assert_no_residue(prefix)
    except Exception as exc:
        failures.append(f"cleanup residue: {exc}")
    return failures


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


async def _assert_no_residue(prefix: str) -> None:
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
    if remaining:
        raise ProbeFailure(f"remaining tenants with prefix {prefix}: {remaining}")
    if any(prefix in (task.prompt or "") for task in await list_tasks()):
        raise ProbeFailure("remaining proactive task with probe prefix")


def _safe_remove_test_dir(path: Path) -> None:
    resolved = path.resolve()
    roots = [Path(settings.memory_base_path).resolve(), Path(settings.artifact_base_path).resolve()]
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise ProbeFailure(f"refusing to remove non-test path: {resolved}")
    if path.exists():
        shutil.rmtree(path)


def _expect(response: httpx.Response, status_code: int, label: str) -> None:
    if response.status_code != status_code:
        raise ProbeFailure(f"{label}: expected {status_code}, got {response.status_code}: {response.text[:500]}")
    if response.status_code >= 500:
        raise ProbeFailure(f"{label}: unexpected 5xx: {response.text[:500]}")


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
    return ordered[index]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
