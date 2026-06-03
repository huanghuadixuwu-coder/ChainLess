"""Proactive task scheduler using ARQ and Redis.

This module provides:

- An in-memory / Redis-backed registry for proactive (cron) tasks.
- An ARQ-compatible job function ``execute_proactive_task`` that runs the agent
  and delivers results via the configured channel.
- ``schedule_task`` / ``cancel_task`` / ``list_tasks`` helpers.

Storage
-------
Task definitions are kept in an in-memory dict for now (backed by Redis in
production).  The ARQ worker enqueues job execution at the times determined
by each task's cron expression.

ARQ Worker Integration
----------------------
To run the worker, add an ``arq-worker`` service to docker-compose:

    arq-worker:
        build:
            context: ./backend
            dockerfile: Dockerfile
        command: [
            "arq", "app.core.proactive.scheduler.WorkerSettings"
        ]
        environment: ...
        depends_on: [redis]
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import redis.asyncio as aioredis

from arq.connections import RedisSettings

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory task registry (Redis-backed in production)
# ---------------------------------------------------------------------------

_tasks: dict[str, dict] = {}

ARQ_REDIS_KEY = "chainless:proactive:tasks"


class ProactiveTask:
    """Value object describing a scheduled proactive task."""

    def __init__(
        self,
        task_id: str,
        cron_expr: str,
        agent_id: str,
        prompt: str,
        channel_type: str,
        channel_config: Optional[dict] = None,
        enabled: bool = True,
        created_at: Optional[str] = None,
    ):
        self.task_id = task_id
        self.cron_expr = cron_expr
        self.agent_id = agent_id
        self.prompt = prompt
        self.channel_type = channel_type
        self.channel_config = channel_config or {}
        self.enabled = enabled
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "cron_expr": self.cron_expr,
            "agent_id": self.agent_id,
            "prompt": self.prompt,
            "channel_type": self.channel_type,
            "channel_config": self.channel_config,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProactiveTask":
        return cls(
            task_id=d["task_id"],
            cron_expr=d.get("cron_expr", ""),
            agent_id=d.get("agent_id", "default"),
            prompt=d.get("prompt", ""),
            channel_type=d.get("channel_type", "feishu"),
            channel_config=d.get("channel_config", {}),
            enabled=d.get("enabled", True),
            created_at=d.get("created_at"),
        )


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

async def _get_redis() -> aioredis.Redis:
    """Return a Redis client connected to the configured Redis URL."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _save_tasks_to_redis(tasks: dict[str, dict]) -> None:
    """Persist the tasks dict to Redis as a JSON blob."""
    try:
        r = await _get_redis()
        await r.set(ARQ_REDIS_KEY, json.dumps(tasks))
        await r.close()
    except Exception as exc:
        logger.warning("Could not persist tasks to Redis: %s", exc)


async def _load_tasks_from_redis() -> dict[str, dict]:
    """Load tasks from Redis, falling back to in-memory dict."""
    try:
        r = await _get_redis()
        raw = await r.get(ARQ_REDIS_KEY)
        await r.close()
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("Could not load tasks from Redis: %s", exc)
    return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def schedule_task(
    task_id: Optional[str] = None,
    cron_expr: str = "0 9 * * *",
    agent_id: str = "default",
    prompt: str = "",
    channel_type: str = "feishu",
    channel_config: Optional[dict] = None,
) -> ProactiveTask:
    """Register a new proactive task.

    The task will be picked up by the ARQ worker's ``check_scheduled_tasks``
    cron job and executed at the times indicated by ``cron_expr``.
    """
    tid = task_id or str(uuid4())
    task = ProactiveTask(
        task_id=tid,
        cron_expr=cron_expr,
        agent_id=agent_id,
        prompt=prompt,
        channel_type=channel_type,
        channel_config=channel_config or {},
    )
    _tasks[tid] = task.to_dict()
    await _save_tasks_to_redis(_tasks)
    logger.info("Scheduled proactive task '%s' with cron '%s'", tid, cron_expr)
    return task


async def cancel_task(task_id: str) -> bool:
    """Remove a scheduled task. Returns False if not found."""
    if task_id not in _tasks:
        # Try loading from Redis
        _tasks.update(await _load_tasks_from_redis())
    if task_id in _tasks:
        del _tasks[task_id]
        await _save_tasks_to_redis(_tasks)
        logger.info("Cancelled proactive task '%s'", task_id)
        return True
    return False


async def get_task(task_id: str) -> Optional[ProactiveTask]:
    """Retrieve a single task by ID."""
    if task_id not in _tasks:
        _tasks.update(await _load_tasks_from_redis())
    raw = _tasks.get(task_id)
    if raw is None:
        return None
    return ProactiveTask.from_dict(raw)


async def list_tasks() -> list[ProactiveTask]:
    """Return all registered proactive tasks."""
    _tasks.update(await _load_tasks_from_redis())
    return [ProactiveTask.from_dict(v) for v in _tasks.values()]


# ---------------------------------------------------------------------------
# ARQ job function — execute one proactive task
# ---------------------------------------------------------------------------

async def execute_proactive_task(ctx: dict, task_id: str) -> dict:
    """ARQ job function: run the agent for a scheduled task and deliver results.

    This function is called by the ARQ worker when a proactive task is due.
    It:
      1. Looks up the task config.
      2. Runs the agent with the configured prompt.
      3. Sends the result through the configured channel.

    Args:
        ctx: ARQ job context (contains ``redis`` connection pool).
        task_id: ID of the proactive task to execute.

    Returns:
        Dict with execution result summary.
    """
    logger.info("Executing proactive task '%s'", task_id)

    task = await get_task(task_id)
    if task is None:
        logger.warning("Proactive task '%s' not found", task_id)
        return {"status": "error", "message": f"Task '{task_id}' not found"}

    # Import agent engine lazily to avoid circular imports at module level
    from app.core.agent.engine import run_agent
    from app.core.llm.gateway import LLMGateway
    from app.core.sandbox.manager import SandboxManager
    from app.core.tools.builtin import ALL_TOOLS
    from app.core.channel.feishu import FeishuChannel
    from app.core.channel.base import ChannelMessage

    # Initialize gateway and sandbox
    llm_gateway = LLMGateway()
    llm_gateway.register(
        "default",
        settings.default_llm_api_base,
        settings.glm_api_key,
        settings.default_llm_model,
        settings.embedding_model,
    )
    sandbox_manager = SandboxManager(settings)
    try:
        await sandbox_manager.warm_pool()
    except Exception as exc:
        logger.warning("Could not warm sandbox pool: %s", exc)

    # Run agent
    messages = [{"role": "user", "content": task.prompt}]
    response_text = ""
    tool_calls_made: list[str] = []
    error = None

    try:
        async for event in run_agent(
            gateway=llm_gateway,
            sandbox_manager=sandbox_manager,
            provider="default",
            messages=messages,
            tools=ALL_TOOLS,
        ):
            if event["type"] == "text":
                response_text += event["content"]
            elif event["type"] == "tool_call_start":
                tool_calls_made.append(event["name"])
    except Exception as exc:
        error = str(exc)
        logger.error("Agent execution failed for task '%s': %s", task_id, exc)

    if sandbox_manager is not None:
        await sandbox_manager.close()

    # Build result message
    content_parts = [
        f"**Task**: {task.prompt}",
        f"**Response**:\n{response_text[:1000]}",
    ]
    if tool_calls_made:
        content_parts.append(f"**Tools used**: {', '.join(tool_calls_made)}")
    if error:
        content_parts.append(f"**Error**: {error}")

    content = "\n\n".join(content_parts)

    # Deliver via channel
    channel = FeishuChannel(
        task.channel_config.get("webhook_url", "")
    )
    msg = ChannelMessage(
        title=f"Proactive Task: {task_id[:8]}",
        content=content,
    )
    delivered = await channel.send(msg)
    logger.info(
        "Proactive task '%s' completed, delivered=%s, tools=%s",
        task_id,
        delivered,
        tool_calls_made,
    )

    return {
        "status": "completed" if not error else "error",
        "task_id": task_id,
        "response_length": len(response_text),
        "tool_calls": tool_calls_made,
        "delivered": delivered,
        "error": error,
    }


# ---------------------------------------------------------------------------
# ARQ WorkerSettings — periodic check for due tasks
# ---------------------------------------------------------------------------

async def check_scheduled_tasks(ctx: dict) -> None:
    """ARQ cron job: check all registered tasks and enqueue those due to run.

    Runs every minute. For each enabled task, evaluates its cron expression
    and only enqueues if the current minute matches.
    """
    from datetime import datetime, timezone
    from arq.jobs import Job
    from croniter import croniter

    now = datetime.now(timezone.utc)
    min_window = now.replace(second=0, microsecond=0)

    tasks = await list_tasks()
    enqueued = 0
    for task in tasks:
        if not task.enabled:
            continue
        # Evaluate cron expression — only enqueue if this minute is a match
        if not croniter.match(task.cron_expr, min_window):
            continue
        await Job.create(
            ctx["redis"],
            execute_proactive_task,
            _job_id=f"proactive:{task.task_id}",
            _queue_name="arq:proactive",
            task_id=task.task_id,
        )
        enqueued += 1
        logger.info("Enqueued proactive task '%s' (cron: %s)", task.task_id, task.cron_expr)
    logger.debug("Checked %d tasks, enqueued %d", len(tasks), enqueued)


class WorkerSettings:
    """ARQ worker settings for the proactive scheduler.

    Use this class to launch an ARQ worker that processes proactive tasks:

        arq app.core.proactive.scheduler.WorkerSettings

    Or add it to docker-compose as a separate service.
    """

    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [execute_proactive_task]
    cron_jobs = [
        # Check for due tasks every 5 minutes
        (check_scheduled_tasks, {"cron": "*/5 * * * *"}),
    ]
    queue_name = "arq:proactive"
