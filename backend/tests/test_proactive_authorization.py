"""W8 proactive pre-authorization and audit/run-history contract."""

from __future__ import annotations

import json

import pytest

from app.core.proactive import scheduler

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _isolated_proactive_redis():
    redis = await scheduler._get_redis_client()
    previous_tasks = await redis.get(scheduler.ARQ_REDIS_KEY)
    previous_runs = await redis.lrange(scheduler.ARQ_RUN_LOG_KEY, 0, -1)
    await redis.delete(scheduler.ARQ_REDIS_KEY, scheduler.ARQ_RUN_LOG_KEY)
    scheduler._tasks.clear()
    try:
        yield
    finally:
        await redis.delete(scheduler.ARQ_REDIS_KEY, scheduler.ARQ_RUN_LOG_KEY)
        if previous_tasks is not None:
            await redis.set(scheduler.ARQ_REDIS_KEY, previous_tasks)
        if previous_runs:
            await redis.rpush(scheduler.ARQ_RUN_LOG_KEY, *previous_runs)
        scheduler._tasks.clear()


async def test_proactive_blocks_tools_outside_pre_authorized_list_and_logs_without_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = "secret prompt that must not be written to run history"
    task = await scheduler.schedule_task(
        tenant_id="11111111-1111-1111-1111-111111111111",
        prompt=prompt,
        authorized_tools=["weather_get"],
    )
    sent: list[str] = []

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {
                "type": "tool_call",
                "index": 0,
                "id": f"call-{len(messages)}",
                "name": "web_fetch",
                "arguments": '{"url":"https://example.com"}',
            }

    class Channel:
        async def send_with_result(self, message):
            sent.append(message.content)
            return {"ok": True, "attempts": 1, "status_code": 200, "error": None}

    async def fake_resolve(task):
        return Channel()

    monkeypatch.setattr(scheduler, "_resolve_delivery_channel", fake_resolve)

    result = await scheduler.execute_proactive_task(
        {"llm_gateway": Gateway(), "sandbox_manager": object()},
        task.task_id,
    )
    records = await scheduler.list_run_records(10, task.tenant_id)
    run_text = json.dumps(records, ensure_ascii=False)

    assert result["status"] == "blocked"
    assert result["delivered"] is False
    assert result["delivery"]["skipped"] is True
    assert [item["name"] for item in result["blocked_tools"]] == ["web_fetch"]
    assert sent == []
    assert records[0]["prompt_sha256"]
    assert prompt not in run_text
    assert "web_fetch" in run_text


async def test_proactive_contract_persists_pre_authorized_tools_and_trigger_fields(
    client,
    tenant_a_headers,
) -> None:
    from app.api.deps import _async_session_factory
    from app.models.user import User
    from app.services.auth_service import decode_token
    import uuid

    identity = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        user = await db.get(User, uuid.UUID(identity["user_id"]))
        user.role = "admin"
        await db.commit()

    created = await client.post(
        "/api/v1/proactive-tasks",
        headers=tenant_a_headers,
        json={
            "type": "event",
            "event_type": "invoice.created",
            "prompt": "summarize event",
            "channel_type": "feishu",
            "authorized_tools": ["weather_get", "web_search"],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["trigger_type"] == "event"
    assert body["event_type"] == "invoice.created"
    assert body["authorized_tools"] == ["weather_get", "web_search"]

    listed = await client.get("/api/v1/proactive-tasks", headers=tenant_a_headers)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["authorized_tools"] == ["weather_get", "web_search"]
