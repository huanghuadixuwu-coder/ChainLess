"""Canonical API contract tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.api.deps import _async_session_factory
from app.main import app_state
from app.models.user import User
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


async def _promote_to_admin(headers: dict[str, str]) -> dict:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == uuid.UUID(payload["user_id"]))
            .values(role="admin")
        )
        await db.commit()
    return payload


async def test_missing_auth_uses_stable_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/conversations/")

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "AUTH_EXPIRED",
            "message": "Missing bearer token",
            "detail": None,
        }
    }


async def test_validation_errors_use_stable_error_envelope(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json={})

    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert isinstance(body["error"]["detail"], list)


async def test_not_found_uses_domain_error_code(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    response = await client.get(
        f"/api/v1/conversations/{uuid.uuid4()}",
        headers=tenant_a_headers,
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "CONVERSATION_NOT_FOUND",
            "message": "Conversation not found",
            "detail": None,
        }
    }


async def test_list_endpoints_use_canonical_pagination(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory
    from app.models.user import User
    from app.services.auth_service import decode_token

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()

    response = await client.get(
        "/api/v1/conversations/?limit=1&offset=0",
        headers=tenant_a_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "limit", "offset", "next"}
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert isinstance(body["items"], list)

    runs = await client.get(
        "/api/v1/proactive-tasks/runs?limit=1&offset=0",
        headers=tenant_a_headers,
    )
    assert runs.status_code == 200
    assert set(runs.json()) == {"items", "total", "limit", "offset", "next"}
    assert runs.json()["limit"] == 1


async def test_archived_conversation_can_be_explicitly_purged(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "purge-contract"},
    )
    conversation_id = created.json()["id"]

    archived = await client.delete(
        f"/api/v1/conversations/{conversation_id}",
        headers=tenant_a_headers,
    )
    purged = await client.delete(
        f"/api/v1/conversations/{conversation_id}?purge=true",
        headers=tenant_a_headers,
    )
    purged_again = await client.delete(
        f"/api/v1/conversations/{conversation_id}?purge=true",
        headers=tenant_a_headers,
    )

    assert archived.status_code == 204
    assert purged.status_code == 204
    assert purged_again.status_code == 404


async def test_unexpected_errors_use_stable_error_envelope(client: AsyncClient) -> None:
    from app.main import app

    route_path = f"/__test__/unexpected-error-{uuid.uuid4().hex}"

    async def _unexpected_error() -> None:
        raise RuntimeError("boom secret")

    app.add_api_route(route_path, _unexpected_error, methods=["GET"])

    response = await client.get(route_path)

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error",
            "detail": None,
        }
    }


async def test_tools_surface_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tools/")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_EXPIRED"


async def test_agent_admin_validation_contracts(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory
    from app.models.user import User
    from app.services.auth_service import decode_token

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()

    bad_limit = await client.get("/api/v1/agents/?limit=0", headers=tenant_a_headers)
    bad_offset = await client.get("/api/v1/agents/?offset=-1", headers=tenant_a_headers)
    too_large = await client.get("/api/v1/agents/?limit=101", headers=tenant_a_headers)
    bad_id = await client.get("/api/v1/agents/not-a-uuid", headers=tenant_a_headers)

    for response in (bad_limit, bad_offset, too_large, bad_id):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert response.json()["error"]["message"] == "Request validation failed"


async def test_agent_tool_and_proactive_admin_contracts_still_succeed(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory
    from app.models.user import User
    from app.services.auth_service import decode_token

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()

    created_agent = await client.post(
        "/api/v1/agents/",
        headers=tenant_a_headers,
        json={"name": "admin-agent"},
    )
    assert created_agent.status_code == 200, created_agent.text
    agent_id = created_agent.json()["id"]

    listed_agents = await client.get("/api/v1/agents/?limit=1&offset=0", headers=tenant_a_headers)
    read_agent = await client.get(f"/api/v1/agents/{agent_id}", headers=tenant_a_headers)
    updated_agent = await client.put(
        f"/api/v1/agents/{agent_id}",
        headers=tenant_a_headers,
        json={"name": "admin-agent-updated"},
    )
    deleted_agent = await client.delete(f"/api/v1/agents/{agent_id}", headers=tenant_a_headers)

    assert listed_agents.status_code == 200
    assert set(listed_agents.json()) == {"items", "total", "limit", "offset", "next"}
    assert read_agent.status_code == 200
    assert updated_agent.status_code == 200
    assert deleted_agent.status_code == 200

    tools = await client.get("/api/v1/tools/?limit=2&offset=0", headers=tenant_a_headers)
    missing_tool = await client.delete("/api/v1/tools/not-registered", headers=tenant_a_headers)
    assert tools.status_code == 200
    assert set(["items", "total", "limit", "offset", "next"]).issubset(tools.json())
    assert missing_tool.status_code == 404
    assert missing_tool.json()["error"]["code"] == "TOOL_NOT_FOUND"

    created_task = await client.post(
        "/api/v1/proactive-tasks",
        headers=tenant_a_headers,
        json={"cron_expr": "0 9 * * *", "prompt": "admin task", "channel_type": "feishu"},
    )
    assert created_task.status_code == 201, created_task.text
    task_id = created_task.json()["task_id"]

    listed_tasks = await client.get("/api/v1/proactive-tasks?limit=1&offset=0", headers=tenant_a_headers)
    runs = await client.get("/api/v1/proactive-tasks/runs?limit=1&offset=0", headers=tenant_a_headers)
    deleted_task = await client.delete(f"/api/v1/proactive-tasks/{task_id}", headers=tenant_a_headers)

    assert listed_tasks.status_code == 200
    assert set(listed_tasks.json()) == {"items", "total", "limit", "offset", "next"}
    assert runs.status_code == 200
    assert set(runs.json()) == {"items", "total", "limit", "offset", "next"}
    assert deleted_task.status_code == 200


async def test_auth_refresh_and_me_follow_stable_contract(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    refreshed = await client.post("/api/v1/auth/refresh", headers=tenant_a_headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["token_type"] == "bearer"

    token = refreshed.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert set(["tenant_id", "user_id", "username", "role"]).issubset(me.json())


async def test_disabled_user_cannot_login_or_refresh(client: AsyncClient) -> None:
    from app.api.deps import _async_session_factory
    from app.models.tenant import Tenant
    from app.models.user import User

    suffix = uuid.uuid4().hex
    tenant_name = f"disabled-{suffix}"
    username = f"user-{suffix}"
    password = "secret123"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"tenant_name": tenant_name, "username": username, "password": password},
    )
    assert registered.status_code == 200, registered.text
    token = registered.json()["access_token"]

    async with _async_session_factory() as db:
        tenant = (await db.execute(select(Tenant).where(Tenant.name == tenant_name))).scalar_one()
        user = (
            await db.execute(
                select(User).where(User.tenant_id == tenant.id, User.username == username)
            )
        ).scalar_one()
        user.preferences = {"disabled": True}
        await db.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"tenant_name": tenant_name, "username": username, "password": password},
    )
    refresh = await client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 401
    assert login.json()["error"]["code"] == "AUTH_FAILED"
    assert refresh.status_code == 401
    assert refresh.json()["error"]["code"] == "AUTH_EXPIRED"


async def test_channel_and_tool_routes_have_pagination_and_error_contracts(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory
    from app.models.user import User
    from app.services.auth_service import decode_token

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()

    channels = await client.get("/api/v1/channels?limit=1&offset=0", headers=tenant_a_headers)
    assert channels.status_code == 200
    assert set(["items", "total", "limit", "offset", "next"]).issubset(channels.json())

    bad_channel = await client.post(
        "/api/v1/channels/email/test",
        headers=tenant_a_headers,
        json={"config": {}, "title": "test", "content": "test"},
    )
    assert bad_channel.status_code == 400
    assert bad_channel.json()["error"]["code"] == "CHANNEL_NOT_SUPPORTED"

    tools = await client.get("/api/v1/tools/?limit=2&offset=0", headers=tenant_a_headers)
    assert tools.status_code == 200
    assert set(["items", "total", "limit", "offset", "next"]).issubset(tools.json())

    missing_tool = await client.delete("/api/v1/tools/not-registered", headers=tenant_a_headers)
    assert missing_tool.status_code == 404
    assert missing_tool.json()["error"]["code"] == "TOOL_NOT_FOUND"


async def test_tools_admin_can_register_test_and_delete_mcp_server(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory
    from app.core.tools.mcp.manager import mcp_manager
    from app.models.user import User
    from app.services.auth_service import decode_token

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()

    server_name = f"echo-{uuid.uuid4().hex}"
    try:
        registered = await client.post(
            "/api/v1/tools/",
            headers=tenant_a_headers,
            json={
                "name": server_name,
                "tool_type": "mcp",
                "config": {
                    "command": "python",
                    "args": ["scripts/mcp_echo_server.py"],
                    "env": {},
                },
            },
        )
        assert registered.status_code == 201, registered.text
        assert registered.json()["name"] == server_name
        assert registered.json()["tool_type"] == "mcp"
        assert registered.json()["tools_count"] == 1

        tool_name = f"mcp__{server_name}__echo"
        assert registered.json()["tools"][0]["function"]["name"] == tool_name

        listed = await client.get("/api/v1/tools/?limit=200&offset=0", headers=tenant_a_headers)
        assert listed.status_code == 200
        assert any(item["function"]["name"] == tool_name for item in listed.json()["items"])

        tested = await client.post(
            f"/api/v1/tools/{server_name}/test",
            headers=tenant_a_headers,
            json={"tool_name": "echo", "args": {"text": "admin-mcp-ok"}},
        )
        assert tested.status_code == 200, tested.text
        assert tested.json() == {"tool_name": tool_name, "result": '["admin-mcp-ok"]'}

        deleted = await client.delete(f"/api/v1/tools/{server_name}", headers=tenant_a_headers)
        assert deleted.status_code == 204

        deleted_again = await client.delete(
            f"/api/v1/tools/{server_name}",
            headers=tenant_a_headers,
        )
        assert deleted_again.status_code == 404
        assert deleted_again.json()["error"]["code"] == "TOOL_NOT_FOUND"
    finally:
        await mcp_manager.unregister(server_name)


async def test_tools_mcp_failures_do_not_leak_exception_details(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.deps import _async_session_factory
    from app.core.tools.mcp.manager import mcp_manager
    from app.models.user import User
    from app.services.auth_service import decode_token

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()

    secret = f"sk-secret-{uuid.uuid4().hex}"
    secret_command = f"secret-command-{uuid.uuid4().hex}"

    async def fail_register(name, config):
        raise RuntimeError(f"raw register failure {secret} {config['command']} {config['env']}")

    monkeypatch.setattr(mcp_manager, "register", fail_register)
    register_failure = await client.post(
        "/api/v1/tools/",
        headers=tenant_a_headers,
        json={
            "name": "unsafe-mcp",
            "tool_type": "mcp",
            "config": {
                "command": secret_command,
                "args": [],
                "env": {"TOKEN": secret},
            },
        },
    )

    assert register_failure.status_code == 502
    assert register_failure.json()["error"] == {
        "code": "MCP_CONNECTION_FAILED",
        "message": "Failed to connect to MCP server",
        "detail": None,
    }
    assert secret not in register_failure.text
    assert secret_command not in register_failure.text

    async def fail_execute(tool_name, args):
        raise RuntimeError(f"raw tool failure {secret} {args}")

    monkeypatch.setattr(mcp_manager, "get_client_for_tool", lambda tool_name: object())
    monkeypatch.setattr(mcp_manager, "execute", fail_execute)
    test_failure = await client.post(
        "/api/v1/tools/unsafe-mcp/test",
        headers=tenant_a_headers,
        json={"tool_name": "echo", "args": {"text": secret}},
    )

    assert test_failure.status_code == 502
    assert test_failure.json()["error"] == {
        "code": "MCP_CONNECTION_FAILED",
        "message": "Tool call failed",
        "detail": None,
    }
    assert secret not in test_failure.text


async def test_eval_admin_api_uses_pagination_validation_and_safe_run_contract(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory
    from app.models.user import User
    from app.services.auth_service import decode_token

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()

    suites = await client.get("/api/v1/eval/suites?limit=1&offset=0", headers=tenant_a_headers)
    statuses = await client.get("/api/v1/eval/status?limit=1&offset=0", headers=tenant_a_headers)
    dry_run = await client.post(
        "/api/v1/eval/run",
        headers=tenant_a_headers,
        json={"suite": "basic", "dry_run": True},
    )
    missing = await client.post(
        "/api/v1/eval/run",
        headers=tenant_a_headers,
        json={"suite": "missing-suite", "dry_run": True},
    )
    traversal = await client.get(
        "/api/v1/eval/suites/../secret/status",
        headers=tenant_a_headers,
    )

    assert suites.status_code == 200
    assert set(suites.json()) == {"items", "total", "limit", "offset", "next"}
    assert suites.json()["items"]
    assert "name" in suites.json()["items"][0]
    assert statuses.status_code == 200
    assert set(statuses.json()) == {"items", "total", "limit", "offset", "next"}
    assert dry_run.status_code == 202
    assert dry_run.json()["status"] == "validated"
    assert dry_run.json()["executed"] is False
    assert "stdout" not in dry_run.text.lower()
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "EVAL_SUITE_NOT_FOUND"
    assert traversal.status_code in (404, 422)


async def test_system_and_openapi_route_truth(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import app_state
    from app.core.ops.health import write_worker_heartbeat
    import redis.asyncio as aioredis
    from app.config import settings

    class DummySandboxManager:
        pool_size = 0

        async def get_proxy_health(self) -> dict:
            return {"pool_size": 0, "total_containers": 0}

    monkeypatch.setattr(app_state, "sandbox_manager", DummySandboxManager())
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    await write_worker_heartbeat(redis_client)
    await redis_client.aclose()

    public_health = await client.get("/api/v1/health")
    detailed_health_without_auth = await client.get("/api/v1/system/health")
    metrics_without_auth = await client.get("/api/v1/system/metrics")

    await _promote_to_admin(tenant_a_headers)
    detailed_health = await client.get(
        "/api/v1/system/health", headers=tenant_a_headers
    )
    metrics = await client.get("/api/v1/system/metrics", headers=tenant_a_headers)

    assert public_health.status_code == 200
    assert public_health.json() == {"status": "ok"}
    assert detailed_health_without_auth.status_code == 401
    assert metrics_without_auth.status_code == 401
    assert detailed_health.status_code == 200
    assert detailed_health.json()["status"] == "ok"
    assert metrics.status_code == 200
    assert "chainless_db_up" in metrics.text

    openapi = await client.get("/openapi.json")
    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    assert "/api/v1/auth/refresh" in paths
    assert "/api/v1/conversations/{conv_id}/confirm" in paths
    assert "/api/v1/tools/" in paths
    assert "/api/v1/skills/" in paths
    assert "/api/v1/skills/match" in paths
    assert "/api/v1/eval/suites" in paths
    assert "/api/v1/system/health" in paths
    assert "/api/v1/system/metrics" in paths


async def test_chat_route_uses_active_agent_provider_and_system_prompt(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = await _promote_to_admin(tenant_a_headers)
    tenant_id = payload["tenant_id"]

    primary = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "primary-provider",
            "api_base": "https://provider.example/v1",
            "api_key": "primary-key",
            "model": "primary-model",
            "is_default": True,
        },
    )
    assert primary.status_code == 201, primary.text

    switched = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "selected-provider",
            "api_base": "https://provider.example/v2",
            "api_key": "selected-key",
            "model": "selected-model",
        },
    )
    assert switched.status_code == 201, switched.text
    switch_default = await client.post(
        "/api/v1/llm-providers/selected-provider/default",
        headers=tenant_a_headers,
    )
    assert switch_default.status_code == 200, switch_default.text

    old_agent = await client.post(
        "/api/v1/agents/",
        headers=tenant_a_headers,
        json={
            "name": "old-agent",
            "system_prompt": "Old system instructions.",
            "llm_provider": "primary-provider",
            "is_active": True,
        },
    )
    assert old_agent.status_code == 200, old_agent.text
    active_agent = await client.post(
        "/api/v1/agents/",
        headers=tenant_a_headers,
        json={
            "name": "active-agent",
            "system_prompt": "Active system instructions.",
            "llm_provider": "selected-provider",
            "is_active": True,
        },
    )
    assert active_agent.status_code == 200, active_agent.text

    agents = await client.get("/api/v1/agents/?limit=20&offset=0", headers=tenant_a_headers)
    assert agents.status_code == 200, agents.text
    active_agents = [item for item in agents.json()["items"] if item["is_active"]]
    assert len(active_agents) == 1
    assert active_agents[0]["name"] == "active-agent"
    assert active_agents[0]["llm_provider"] == "selected-provider"
    assert active_agents[0]["id"] == active_agent.json()["id"]

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "agent-runtime"},
    )
    assert created.status_code == 200, created.text
    conv_id = created.json()["id"]

    captured: dict = {}

    class CaptureGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            captured["provider"] = provider
            captured["tenant_id"] = tenant_id
            captured["messages"] = messages
            yield {"type": "text", "content": "ok"}

    class DummySandbox:
        pass

    monkeypatch.setattr(app_state, "llm_gateway", CaptureGateway())
    monkeypatch.setattr(app_state, "sandbox_manager", DummySandbox())

    chatted = await client.post(
        f"/api/v1/conversations/{conv_id}/chat",
        headers=tenant_a_headers,
        json={"content": "runtime-provider"},
    )
    assert chatted.status_code == 200, chatted.text

    assert captured["tenant_id"] == tenant_id
    assert captured["provider"] == "selected-provider"
    system_message = next(
        (message for message in captured["messages"] if message["role"] == "system"),
        None,
    )
    assert system_message is not None
    assert "Active agent instructions:" in system_message["content"]
    assert "Active system instructions." in system_message["content"]

    refreshed = await client.get(f"/api/v1/conversations/{conv_id}", headers=tenant_a_headers)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["agent_id"] == active_agent.json()["id"]


async def test_chat_route_uses_default_provider_when_no_active_agent(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _promote_to_admin(tenant_a_headers)
    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    tenant_id = payload["tenant_id"]

    initial_default = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "v1-initial-provider",
            "api_base": "https://provider.example/default-a",
            "api_key": "default-key",
            "model": "default-model",
            "is_default": True,
        },
    )
    assert initial_default.status_code == 201, initial_default.text

    replacement = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "v1-replacement-provider",
            "api_base": "https://provider.example/default-b",
            "api_key": "replacement-key",
            "model": "replacement-model",
        },
    )
    assert replacement.status_code == 201, replacement.text
    switched = await client.post(
        "/api/v1/llm-providers/v1-replacement-provider/default",
        headers=tenant_a_headers,
    )
    assert switched.status_code == 200, switched.text

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "default-provider-runtime"},
    )
    assert created.status_code == 200, created.text
    conv_id = created.json()["id"]

    captured: dict = {}

    class CaptureGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            captured["provider"] = provider
            captured["tenant_id"] = tenant_id
            yield {"type": "text", "content": "ok"}

    class DummySandbox:
        pass

    monkeypatch.setattr(app_state, "llm_gateway", CaptureGateway())
    monkeypatch.setattr(app_state, "sandbox_manager", DummySandbox())

    chatted = await client.post(
        f"/api/v1/conversations/{conv_id}/chat",
        headers=tenant_a_headers,
        json={"content": "runtime-provider-default"},
    )
    assert chatted.status_code == 200, chatted.text

    assert captured["tenant_id"] == tenant_id
    assert captured["provider"] == "v1-replacement-provider"


async def test_single_active_agent_is_used_for_conversations(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _promote_to_admin(tenant_a_headers)

    provider = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "active-agent-provider",
            "api_base": "https://provider.example/v1",
            "api_key": "agent-key",
            "model": "agent-model",
            "is_default": True,
        },
    )
    assert provider.status_code == 201, provider.text

    first = await client.post(
        "/api/v1/agents/",
        headers=tenant_a_headers,
        json={"name": "first-agent", "system_prompt": "First agent", "is_active": True},
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        "/api/v1/agents/",
        headers=tenant_a_headers,
        json={
            "name": "second-agent",
            "system_prompt": "Second agent",
            "llm_provider": "active-agent-provider",
            "is_active": True,
        },
    )
    assert second.status_code == 200, second.text

    agents = await client.get("/api/v1/agents/?limit=10&offset=0", headers=tenant_a_headers)
    assert agents.status_code == 200, agents.text
    active = [item for item in agents.json()["items"] if item["is_active"]]
    assert len(active) == 1
    assert active[0]["id"] == second.json()["id"]

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "single-active-runtime"},
    )
    assert created.status_code == 200, created.text
    conv_id = created.json()["id"]

    captured: dict = {}

    class CaptureGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            captured["provider"] = provider
            captured["messages"] = messages
            yield {"type": "text", "content": "ok"}

    class DummySandbox:
        pass

    monkeypatch.setattr(app_state, "llm_gateway", CaptureGateway())
    monkeypatch.setattr(app_state, "sandbox_manager", DummySandbox())

    chatted = await client.post(
        f"/api/v1/conversations/{conv_id}/chat",
        headers=tenant_a_headers,
        json={"content": "active runtime"},
    )
    assert chatted.status_code == 200, chatted.text

    system_message = next(
        (message for message in captured["messages"] if message["role"] == "system"),
        None,
    )
    assert system_message is not None
    assert captured["provider"] == "active-agent-provider"
    assert "Second agent" in system_message["content"]

    refreshed = await client.get(f"/api/v1/conversations/{conv_id}", headers=tenant_a_headers)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["agent_id"] == second.json()["id"]


async def test_confirmation_reuses_active_agent_prompt_and_provider(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _promote_to_admin(tenant_a_headers)

    await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "confirm-provider",
            "api_base": "https://provider.example/v1",
            "api_key": "confirm-key",
            "model": "confirm-model",
            "is_default": True,
        },
    )

    agent = await client.post(
        "/api/v1/agents/",
        headers=tenant_a_headers,
        json={
            "name": "confirm-agent",
            "system_prompt": "Confirm system instructions.",
            "llm_provider": "confirm-provider",
            "is_active": True,
        },
    )
    assert agent.status_code == 200, agent.text

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "confirm-runtime"},
    )
    assert created.status_code == 200, created.text
    conv_id = created.json()["id"]

    async with _async_session_factory() as db:
        from app.services.conversation_stream_service import persist_confirmation_required

        await persist_confirmation_required(
            db,
            conv_id,
            tool_call_id="runtime-resume",
            tool_name="shell_exec",
            args={"script": "echo ok"},
            risk="destructive",
            timeout_s=30,
        )

    captured: dict = {}

    import app.services.conversation_stream_service as stream_service

    async def fake_run_agent(
        gateway,
        sandbox,
        provider,
        messages,
        tools,
        tenant_id=None,
        **kwargs,
    ):
        captured["provider"] = provider
        captured["tenant_id"] = tenant_id
        captured["context_kwargs"] = kwargs
        captured["system_message"] = next(
            (message for message in messages if message["role"] == "system"),
            {},
        )
        yield {"type": "text", "content": "resume-ok"}
        yield {"type": "done", "tokens_used": 1}

    async def fake_execute_confirmed_tool(*args, **kwargs):
        return "ok"

    class DummySandbox:
        pass

    monkeypatch.setattr(app_state, "sandbox_manager", DummySandbox())
    monkeypatch.setattr(stream_service, "run_agent", fake_run_agent)
    monkeypatch.setattr(stream_service, "execute_confirmed_tool", fake_execute_confirmed_tool)

    approved = await client.post(
        f"/api/v1/conversations/{conv_id}/confirm",
        headers=tenant_a_headers,
        json={"tool_call_id": "runtime-resume", "decision": "approve"},
    )
    assert approved.status_code == 200, approved.text
    assert captured["provider"] == "confirm-provider"
    assert captured["context_kwargs"]["conversation_id"] == conv_id
    assert captured["system_message"]["content"].find("Confirm system instructions.") != -1


async def test_tool_configuration_updates_persist_and_runtime_enforces_enabled_and_risk_override(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    payload = await _promote_to_admin(tenant_a_headers)

    original = await client.get("/api/v1/tools/?limit=200&offset=0", headers=tenant_a_headers)
    assert original.status_code == 200, original.text
    shell_before = next(
        item
        for item in original.json()["items"]
        if item["function"]["name"] == "shell_exec"
    )
    assert shell_before["enabled"] is True

    disabled = await client.patch(
        "/api/v1/tools/shell_exec/configuration",
        headers=tenant_a_headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False
    assert disabled.json()["risk_override"] is None

    preserved = await client.patch(
        "/api/v1/tools/shell_exec/configuration",
        headers=tenant_a_headers,
        json={},
    )
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["enabled"] is False
    assert preserved.json()["risk_override"] is None

    listed = await client.get("/api/v1/tools/?limit=200&offset=0", headers=tenant_a_headers)
    listed_shell = next(
        item for item in listed.json()["items"] if item["function"]["name"] == "shell_exec"
    )
    assert listed_shell["enabled"] is False

    restored = await client.patch(
        "/api/v1/tools/shell_exec/configuration",
        headers=tenant_a_headers,
        json={"enabled": True, "risk_override": "safe"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["enabled"] is True
    assert restored.json()["risk_override"] == "safe"

    listed = await client.get("/api/v1/tools/?limit=200&offset=0", headers=tenant_a_headers)
    listed_shell = next(
        item for item in listed.json()["items"] if item["function"]["name"] == "shell_exec"
    )
    assert listed_shell["enabled"] is True
    assert listed_shell["risk"] == "safe"
    assert listed_shell["risk_override"] == "safe"

    clear_override = await client.patch(
        "/api/v1/tools/shell_exec/configuration",
        headers=tenant_a_headers,
        json={"risk_override": None},
    )
    assert clear_override.status_code == 200, clear_override.text
    assert clear_override.json()["enabled"] is True
    assert clear_override.json()["risk_override"] is None

    disabled_runtime = await client.patch(
        "/api/v1/tools/shell_exec/configuration",
        headers=tenant_a_headers,
        json={"enabled": False},
    )
    assert disabled_runtime.status_code == 200, disabled_runtime.text
    assert disabled_runtime.json()["enabled"] is False

    bad_enabled = await client.patch(
        "/api/v1/tools/shell_exec/configuration",
        headers=tenant_a_headers,
        json={"enabled": None},
    )
    assert bad_enabled.status_code == 400, bad_enabled.text
    assert bad_enabled.json()["error"]["code"] == "VALIDATION_ERROR"

    from app.services.conversation_stream_service import get_agent_tools

    tools_disabled = await get_agent_tools(payload["tenant_id"])
    assert not any(
        item["function"]["name"] == "shell_exec" for item in tools_disabled
    )

    await client.patch(
        "/api/v1/tools/shell_exec/configuration",
        headers=tenant_a_headers,
        json={"enabled": True, "risk_override": "risky"},
    )
    tools_enabled = await get_agent_tools(payload["tenant_id"])
    shell_tool = next(
        item for item in tools_enabled if item["function"]["name"] == "shell_exec"
    )
    assert shell_tool["risk"] == "risky"
