"""W8 delayed proactive task one-shot scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.proactive import scheduler

pytestmark = pytest.mark.asyncio


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.heartbeats: list[tuple] = []

    async def set(self, *args, **kwargs):
        self.heartbeats.append((args, kwargs))

    async def enqueue_job(self, name, task_id, **kwargs):
        self.jobs.append({"name": name, "task_id": task_id, **kwargs})
        return {"job_id": kwargs.get("_job_id")}


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


async def test_due_delayed_task_enqueues_once_then_cleans_itself_up() -> None:
    now = datetime.now(timezone.utc)
    due = await scheduler.schedule_task(
        tenant_id="tenant-a",
        prompt="delayed",
        trigger_type="delayed",
        execute_at=(now - timedelta(seconds=5)).isoformat(),
    )
    await scheduler.schedule_task(
        tenant_id="tenant-a",
        prompt="future",
        trigger_type="delayed",
        execute_at=(now + timedelta(hours=1)).isoformat(),
    )
    await scheduler.schedule_task(
        tenant_id="tenant-a",
        prompt="disabled",
        trigger_type="delayed",
        execute_at=(now - timedelta(seconds=5)).isoformat(),
        enabled=False,
    )
    queue = FakeQueue()

    await scheduler.check_scheduled_tasks({"redis": queue})
    await scheduler.check_scheduled_tasks({"redis": queue})

    assert [job["task_id"] for job in queue.jobs] == [due.task_id]
    assert await scheduler.get_task(due.task_id, "tenant-a") is None
    remaining = await scheduler.list_tasks("tenant-a")
    assert sorted(task.prompt for task in remaining) == ["disabled", "future"]
