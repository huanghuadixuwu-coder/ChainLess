"""W8 proactive event-trigger scheduling."""

from __future__ import annotations

import pytest

from app.core.proactive import scheduler

pytestmark = pytest.mark.asyncio


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    async def set(self, *args, **kwargs):
        return None

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


async def test_event_trigger_enqueues_only_matching_enabled_tenant_tasks() -> None:
    matching = await scheduler.schedule_task(
        tenant_id="tenant-a",
        prompt="match",
        trigger_type="event",
        event_type="ticket.created",
    )
    await scheduler.schedule_task(
        tenant_id="tenant-a",
        prompt="wrong event",
        trigger_type="event",
        event_type="ticket.closed",
    )
    await scheduler.schedule_task(
        tenant_id="tenant-b",
        prompt="wrong tenant",
        trigger_type="event",
        event_type="ticket.created",
    )
    await scheduler.schedule_task(
        tenant_id="tenant-a",
        prompt="disabled",
        trigger_type="event",
        event_type="ticket.created",
        enabled=False,
    )

    queue = FakeQueue()
    count = await scheduler.trigger_event_tasks(
        {"redis": queue},
        tenant_id="tenant-a",
        event_type="ticket.created",
        payload={"ticket_id": "T-1"},
    )

    assert count == 1
    assert [job["task_id"] for job in queue.jobs] == [matching.task_id]
    assert await scheduler.get_task(matching.task_id, "tenant-a") is not None
