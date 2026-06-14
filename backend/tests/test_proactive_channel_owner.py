"""Proactive delivery must resolve secrets only from the tenant DB owner."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from app.api.deps import _async_session_factory
from app.core.proactive import scheduler
from app.core.secrets import encrypt_secret
from app.models.channel_configuration import ChannelConfiguration
from app.models.user import User
from app.services.auth_service import decode_token

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


async def _identity(headers: dict[str, str]) -> dict:
    return decode_token(headers["Authorization"].split(" ", 1)[1])


async def _promote_to_admin(headers: dict[str, str]) -> None:
    identity = await _identity(headers)
    async with _async_session_factory() as db:
        user = await db.get(User, uuid.UUID(identity["user_id"]))
        user.role = "admin"
        await db.commit()


async def _configure(tenant_id: str, webhook: str, signing_secret: str | None = None) -> None:
    secrets = {"webhook_url": webhook}
    if signing_secret is not None:
        secrets["secret"] = signing_secret
    async with _async_session_factory() as db:
        db.add(
            ChannelConfiguration(
                tenant_id=uuid.UUID(tenant_id),
                channel_type="feishu",
                public_config={"label": "proactive"},
                encrypted_secrets=encrypt_secret(json.dumps(secrets)),
                enabled=True,
            )
        )
        await db.commit()


async def test_proactive_contract_and_redis_never_accept_channel_secrets(
    client,
    tenant_a_headers,
) -> None:
    await _promote_to_admin(tenant_a_headers)

    secret = f"https://open.feishu.cn/{uuid.uuid4().hex}"
    for forbidden in (
        {"channel_config": {"webhook_url": secret}},
        {"webhook_url": secret},
        {"secret": secret},
    ):
        rejected = await client.post(
            "/api/v1/proactive-tasks",
            headers=tenant_a_headers,
            json={
                "cron_expr": "0 9 * * *",
                "prompt": "safe prompt",
                "channel_type": "feishu",
                **forbidden,
            },
        )
        assert rejected.status_code == 422
        assert secret not in rejected.text

    created = await client.post(
        "/api/v1/proactive-tasks",
        headers=tenant_a_headers,
        json={"cron_expr": "0 9 * * *", "prompt": "safe prompt", "channel_type": "feishu"},
    )
    listed = await client.get("/api/v1/proactive-tasks", headers=tenant_a_headers)
    runs = await client.get("/api/v1/proactive-tasks/runs", headers=tenant_a_headers)
    raw = await (await scheduler._get_redis_client()).get(scheduler.ARQ_REDIS_KEY)

    assert created.status_code == 201
    combined = created.text + listed.text + runs.text + (raw or "")
    assert secret not in combined
    assert "channel_config" not in combined
    assert "webhook_url" not in combined


async def test_worker_resolves_channel_from_tenant_db_owner_only(
    tenant_a_headers,
    tenant_b_headers,
    monkeypatch,
) -> None:
    tenant_a = await _identity(tenant_a_headers)
    tenant_b = await _identity(tenant_b_headers)
    webhook_a = f"https://open.feishu.cn/a-{uuid.uuid4().hex}"
    webhook_b = f"https://open.feishu.cn/b-{uuid.uuid4().hex}"
    signing_secret_a = f"sign-a-{uuid.uuid4().hex}"
    signing_secret_b = f"sign-b-{uuid.uuid4().hex}"
    await _configure(tenant_a["tenant_id"], webhook_a, signing_secret_a)
    await _configure(tenant_b["tenant_id"], webhook_b, signing_secret_b)
    task = await scheduler.schedule_task(
        tenant_id=tenant_a["tenant_id"],
        prompt="use tenant owner",
        channel_type="feishu",
    )
    captured: dict[str, str] = {}

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            captured["provider_tenant"] = tenant_id
            yield {"type": "text", "content": "ok"}

    class Channel:
        def __init__(self, webhook_url, signing_secret=None):
            captured["webhook"] = webhook_url
            captured["signing_secret"] = signing_secret

        async def send_with_result(self, message):
            return {"ok": True, "attempts": 1, "status_code": 200, "error": None}

    monkeypatch.setattr("app.core.channel.feishu.FeishuChannel", Channel)
    result = await scheduler.execute_proactive_task(
        {"llm_gateway": Gateway(), "sandbox_manager": SimpleNamespace()},
        task.task_id,
    )
    run_text = json.dumps(await scheduler.list_run_records(100, tenant_a["tenant_id"]))
    redis_text = await (await scheduler._get_redis_client()).get(scheduler.ARQ_REDIS_KEY)

    assert result["delivered"] is True
    assert captured == {
        "provider_tenant": tenant_a["tenant_id"],
        "webhook": webhook_a,
        "signing_secret": signing_secret_a,
    }
    assert webhook_a not in run_text + redis_text
    assert webhook_b not in run_text + redis_text
    assert signing_secret_a not in run_text + redis_text
    assert signing_secret_b not in run_text + redis_text


async def test_historical_redis_secret_state_is_reported_and_rejected_without_mutation() -> None:
    redis = await scheduler._get_redis_client()
    secret = f"https://open.feishu.cn/legacy-{uuid.uuid4().hex}"
    raw = json.dumps(
        {
            "legacy-task": {
                "task_id": "legacy-task",
                "tenant_id": str(uuid.uuid4()),
                "channel_type": "feishu",
                "channel_config": {"webhook_url": secret},
            }
        }
    )
    previous = await redis.get(scheduler.ARQ_REDIS_KEY)
    try:
        await redis.set(scheduler.ARQ_REDIS_KEY, raw)

        report = await scheduler.inspect_redis_proactive_state()
        with pytest.raises(scheduler.LegacyProactiveSecretStateError):
            await scheduler.list_tasks()

        assert report == {
            "task_count": 1,
            "unsafe_task_count": 1,
            "unsafe_task_ids": [scheduler._unsafe_state_fingerprint("legacy-task")],
            "run_count": 0,
            "unsafe_run_count": 0,
            "unsafe_run_ids": [],
        }
        assert await redis.get(scheduler.ARQ_REDIS_KEY) == raw
    finally:
        if previous is None:
            await redis.delete(scheduler.ARQ_REDIS_KEY)
        else:
            await redis.set(scheduler.ARQ_REDIS_KEY, previous)


async def test_malformed_historical_redis_state_is_rejected_without_mutation() -> None:
    redis = await scheduler._get_redis_client()
    raw = '{"legacy": {"channel_config":'
    await redis.set(scheduler.ARQ_REDIS_KEY, raw)

    report = await scheduler.inspect_redis_proactive_state()
    with pytest.raises(scheduler.LegacyProactiveSecretStateError):
        await scheduler.schedule_task(prompt="must not overwrite")

    assert report == {
        "task_count": 0,
        "unsafe_task_count": 1,
        "unsafe_task_ids": [],
        "run_count": 0,
        "unsafe_run_count": 0,
        "unsafe_run_ids": [],
    }
    assert await redis.get(scheduler.ARQ_REDIS_KEY) == raw


@pytest.mark.parametrize(
    "secret_field",
    [
        "channel_config",
        "webhook_url",
        "secret",
        "token",
        "api_key",
        "password",
        "client_secret",
        "signing_secret",
        "access_token",
        "authorization",
        "cookie",
        "secret_key",
    ],
)
async def test_run_history_rejects_recursive_secret_fields_before_redis_write(
    secret_field: str,
) -> None:
    redis = await scheduler._get_redis_client()
    secret = f"run-secret-{uuid.uuid4().hex}"

    with pytest.raises(scheduler.LegacyProactiveSecretStateError):
        await scheduler._record_task_run(
            {"task_id": "unsafe-write", "nested": [{secret_field: secret}]}
        )

    assert await redis.lrange(scheduler.ARQ_RUN_LOG_KEY, 0, -1) == []


@pytest.mark.parametrize(
    "secret_field",
    [
        "client_secret",
        "signing_secret",
        "access_token",
        "authorization",
        "cookie",
        "secret_key",
    ],
)
async def test_historical_task_and_run_state_reuse_global_sensitive_key_rules(
    secret_field: str,
) -> None:
    redis = await scheduler._get_redis_client()
    secret = f"global-rule-secret-{uuid.uuid4().hex}"
    tasks = {
        "unsafe-task": {
            "task_id": "unsafe-task",
            "nested": [{secret_field: secret}],
        }
    }
    run = json.dumps({"task_id": "unsafe-run", "nested": [{secret_field: secret}]})
    await redis.set(scheduler.ARQ_REDIS_KEY, json.dumps(tasks))
    await redis.rpush(scheduler.ARQ_RUN_LOG_KEY, run)

    report = await scheduler.inspect_redis_proactive_state()
    with pytest.raises(scheduler.LegacyProactiveSecretStateError):
        await scheduler.list_tasks()
    with pytest.raises(scheduler.LegacyProactiveSecretStateError):
        await scheduler.list_run_records()

    assert report["unsafe_task_count"] == 1
    assert report["unsafe_run_count"] == 1
    assert secret not in json.dumps(report)
    assert secret not in str(report["unsafe_task_ids"] + report["unsafe_run_ids"])
    assert await redis.get(scheduler.ARQ_REDIS_KEY) == json.dumps(tasks)
    assert await redis.lrange(scheduler.ARQ_RUN_LOG_KEY, 0, -1) == [run]


async def test_task_redis_write_rejects_global_sensitive_fields() -> None:
    redis = await scheduler._get_redis_client()
    secret = f"task-write-secret-{uuid.uuid4().hex}"

    with pytest.raises(scheduler.LegacyProactiveSecretStateError):
        await scheduler._save_tasks_to_redis(
            {"unsafe-task": {"nested": {"client_secret": secret}}}
        )

    assert await redis.get(scheduler.ARQ_REDIS_KEY) is None


async def test_historical_run_secret_state_is_reported_and_rejected_without_mutation(
    client,
    tenant_a_headers,
) -> None:
    await _promote_to_admin(tenant_a_headers)

    redis = await scheduler._get_redis_client()
    secret = f"historical-run-secret-{uuid.uuid4().hex}"
    unsafe = json.dumps(
        {"task_id": "unsafe-run", "nested": {"channel_config": {"token": secret}}}
    )
    safe = json.dumps({"task_id": "safe-run", "status": "completed"})
    await redis.rpush(scheduler.ARQ_RUN_LOG_KEY, unsafe, safe)

    report = await scheduler.inspect_redis_proactive_state()
    with pytest.raises(scheduler.LegacyProactiveSecretStateError):
        await scheduler.list_run_records()
    response = await client.get("/api/v1/proactive-tasks/runs", headers=tenant_a_headers)

    assert report["run_count"] == 2
    assert report["unsafe_run_count"] == 1
    assert len(report["unsafe_run_ids"]) == 1
    assert secret not in json.dumps(report)
    assert response.status_code == 500
    assert secret not in response.text
    assert await redis.lrange(scheduler.ARQ_RUN_LOG_KEY, 0, -1) == [unsafe, safe]
