"""Redis-backed proactive task scheduler with ARQ worker execution."""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.core.acquisition.tasks import process_acquisition_analysis
from app.core.channel.configuration import resolve_channel_configuration
from app.core.capabilities.tasks import process_capability_analysis
from app.core.tools.classifier import is_pre_authorized
from app.core.secrets import is_sensitive_key, safe_error_message
from app.core.ops.health import write_worker_heartbeat

logger = logging.getLogger(__name__)

_tasks: dict[str, dict] = {}
_redis_client: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None

ARQ_REDIS_KEY = "chainless:proactive:tasks"
ARQ_RUN_LOG_KEY = "chainless:proactive:run-log"
ARQ_RUN_LOG_LIMIT = 100
ARQ_QUEUE_NAME = "arq:proactive"


class LegacyProactiveSecretStateError(RuntimeError):
    """Raised when Redis contains retired secret-bearing proactive state."""


class ProactiveTask:
    """Value object describing a scheduled proactive task."""

    def __init__(
        self,
        task_id: str,
        cron_expr: str,
        agent_id: str,
        prompt: str,
        channel_type: str,
        tenant_id: Optional[str] = None,
        enabled: bool = True,
        created_at: Optional[str] = None,
        authorized_tools: Optional[list[str]] = None,
        trigger_type: str = "cron",
        event_type: Optional[str] = None,
        execute_at: Optional[str] = None,
    ):
        self.task_id = task_id
        self.cron_expr = cron_expr
        self.agent_id = agent_id
        self.prompt = prompt
        self.channel_type = channel_type
        self.tenant_id = tenant_id
        self.enabled = enabled
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.authorized_tools = authorized_tools or []
        self.trigger_type = trigger_type
        self.event_type = event_type
        self.execute_at = execute_at

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "cron_expr": self.cron_expr,
            "agent_id": self.agent_id,
            "prompt": self.prompt,
            "channel_type": self.channel_type,
            "tenant_id": self.tenant_id,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "authorized_tools": self.authorized_tools,
            "trigger_type": self.trigger_type,
            "event_type": self.event_type,
            "execute_at": self.execute_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProactiveTask":
        return cls(
            task_id=d["task_id"],
            cron_expr=d.get("cron_expr", ""),
            agent_id=d.get("agent_id", "default"),
            prompt=d.get("prompt", ""),
            channel_type=d.get("channel_type", "feishu"),
            tenant_id=d.get("tenant_id"),
            enabled=d.get("enabled", True),
            created_at=d.get("created_at"),
            authorized_tools=list(d.get("authorized_tools") or []),
            trigger_type=d.get("trigger_type") or d.get("type") or "cron",
            event_type=d.get("event_type"),
            execute_at=d.get("execute_at"),
        )


async def _get_redis_client() -> aioredis.Redis:
    """Return a shared Redis client singleton."""
    global _redis_client, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        _redis_loop = loop
    return _redis_client


async def _save_tasks_to_redis(tasks: dict[str, dict]) -> None:
    if inspect_legacy_proactive_state(tasks)["unsafe_task_count"]:
        logger.error("Refusing retired secret-bearing proactive task write")
        raise LegacyProactiveSecretStateError(
            "Retired secret-bearing proactive task write was rejected"
        )
    try:
        r = await _get_redis_client()
        await r.set(ARQ_REDIS_KEY, json.dumps(tasks, ensure_ascii=False))
    except Exception as exc:
        logger.warning("%s", safe_error_message(exc, "Could not persist tasks to Redis"))


async def _load_tasks_from_redis() -> dict[str, dict]:
    try:
        r = await _get_redis_client()
        raw = await r.get(ARQ_REDIS_KEY)
        if raw:
            try:
                tasks = json.loads(raw)
            except (TypeError, ValueError) as exc:
                logger.error("Refusing malformed proactive task state")
                raise LegacyProactiveSecretStateError(
                    "Malformed proactive task state requires controlled migration"
                ) from exc
            report = inspect_legacy_proactive_state(tasks)
            if report["unsafe_task_count"]:
                logger.error(
                    "Refusing retired secret-bearing proactive state: unsafe_task_count=%d",
                    report["unsafe_task_count"],
                )
                raise LegacyProactiveSecretStateError(
                    "Retired secret-bearing proactive state requires controlled migration"
                )
            return tasks
    except LegacyProactiveSecretStateError:
        raise
    except Exception as exc:
        logger.warning("%s", safe_error_message(exc, "Could not load tasks from Redis"))
    return {}


def inspect_legacy_proactive_state(tasks: object) -> dict[str, Any]:
    """Return a secret-free, read-only report for historical Redis task state."""
    if not isinstance(tasks, dict):
        return {"task_count": 0, "unsafe_task_count": 1, "unsafe_task_ids": []}
    unsafe_ids = [
        _unsafe_state_fingerprint(task_id)
        for task_id, value in tasks.items()
        if _contains_retired_secret_field(value)
    ]
    return {
        "task_count": len(tasks),
        "unsafe_task_count": len(unsafe_ids),
        "unsafe_task_ids": unsafe_ids,
    }


def inspect_legacy_run_history_state(rows: object) -> dict[str, Any]:
    """Return a secret-free, read-only report for historical Redis run records."""
    if not isinstance(rows, (list, tuple)):
        return {"run_count": 0, "unsafe_run_count": 1, "unsafe_run_ids": []}

    unsafe_ids: list[str] = []
    for row in rows:
        try:
            record = json.loads(row) if isinstance(row, str) else row
        except (TypeError, ValueError):
            record = None
        if not isinstance(record, dict) or _contains_retired_secret_field(record):
            unsafe_ids.append(_unsafe_state_fingerprint(row))
    return {
        "run_count": len(rows),
        "unsafe_run_count": len(unsafe_ids),
        "unsafe_run_ids": unsafe_ids,
    }


def _unsafe_state_fingerprint(value: object) -> str:
    fingerprint = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"sha256:{fingerprint}"


def _contains_retired_secret_field(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            is_sensitive_key(key)
            or _contains_retired_secret_field(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_retired_secret_field(item) for item in value)
    return False


def _parse_utc_datetime(value: str) -> datetime:
    """Parse ISO datetimes, accepting the common UTC ``Z`` suffix."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def inspect_redis_proactive_state() -> dict[str, Any]:
    """Inspect Redis without changing task state or returning secret values."""
    r = await _get_redis_client()
    raw_tasks = await r.get(ARQ_REDIS_KEY)
    raw_runs = await r.lrange(ARQ_RUN_LOG_KEY, 0, -1)
    if raw_tasks:
        try:
            task_report = inspect_legacy_proactive_state(json.loads(raw_tasks))
        except (TypeError, ValueError):
            task_report = {"task_count": 0, "unsafe_task_count": 1, "unsafe_task_ids": []}
    else:
        task_report = {"task_count": 0, "unsafe_task_count": 0, "unsafe_task_ids": []}
    return {**task_report, **inspect_legacy_run_history_state(raw_runs)}


async def _refresh_tasks_from_redis() -> dict[str, dict]:
    """Replace the in-process cache with Redis as the source of truth."""
    _tasks.clear()
    _tasks.update(await _load_tasks_from_redis())
    return _tasks


async def _record_task_run(record: dict[str, Any]) -> None:
    """Append a bounded execution record for scheduler observability."""
    if _contains_retired_secret_field(record):
        logger.error("Refusing retired secret-bearing proactive run record")
        raise LegacyProactiveSecretStateError(
            "Retired secret-bearing proactive run record was rejected"
        )
    payload = json.dumps(record, ensure_ascii=False)
    try:
        r = await _get_redis_client()
        await r.lpush(ARQ_RUN_LOG_KEY, payload)
        await r.ltrim(ARQ_RUN_LOG_KEY, 0, ARQ_RUN_LOG_LIMIT - 1)
    except Exception as exc:
        logger.warning("%s", safe_error_message(exc, "Could not record proactive run"))


async def list_run_records(limit: int = 20, tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Return recent proactive execution records, newest first."""
    try:
        r = await _get_redis_client()
        rows = await r.lrange(ARQ_RUN_LOG_KEY, 0, -1)
        report = inspect_legacy_run_history_state(rows)
        if report["unsafe_run_count"]:
            logger.error(
                "Refusing retired secret-bearing proactive run history: unsafe_run_count=%d",
                report["unsafe_run_count"],
            )
            raise LegacyProactiveSecretStateError(
                "Retired secret-bearing proactive run history requires controlled migration"
            )
        records = [json.loads(row) for row in rows]
        if tenant_id is not None:
            records = [record for record in records if record.get("tenant_id") == tenant_id]
        return records[:limit]
    except LegacyProactiveSecretStateError:
        raise
    except Exception as exc:
        logger.warning("%s", safe_error_message(exc, "Could not load proactive run records"))
        return []


async def count_run_records(tenant_id: str | None = None) -> int:
    """Return the number of retained proactive execution records."""
    try:
        r = await _get_redis_client()
        if tenant_id is None:
            return int(await r.llen(ARQ_RUN_LOG_KEY))
        return len(await list_run_records(ARQ_RUN_LOG_LIMIT, tenant_id))
    except Exception as exc:
        logger.warning("%s", safe_error_message(exc, "Could not count proactive run records"))
        return 0


async def summarize_run_records(tenant_id: str | None = None) -> dict[str, int]:
    """Return secret-free proactive run counters for metrics."""
    records = await list_run_records(ARQ_RUN_LOG_LIMIT, tenant_id)
    summary = {
        "total": len(records),
        "blocked": 0,
        "delivery_failed": 0,
        "error": 0,
        "completed": 0,
    }
    for record in records:
        status = str(record.get("status") or "")
        if status in summary:
            summary[status] += 1
        if record.get("blocked_tools"):
            summary["blocked"] += 1
        if record.get("delivery", {}).get("ok") is False:
            summary["delivery_failed"] += 1
    return summary


async def schedule_task(
    task_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    cron_expr: str = "0 9 * * *",
    agent_id: str = "default",
    prompt: str = "",
    channel_type: str = "feishu",
    authorized_tools: Optional[list[str]] = None,
    trigger_type: str = "cron",
    event_type: Optional[str] = None,
    execute_at: Optional[str] = None,
    enabled: bool = True,
) -> ProactiveTask:
    """Register a proactive task for the ARQ worker to execute."""
    await _refresh_tasks_from_redis()
    tid = task_id or str(uuid4())
    if execute_at and trigger_type == "cron":
        trigger_type = "delayed"
    if event_type and trigger_type == "cron":
        trigger_type = "event"
    task = ProactiveTask(
        task_id=tid,
        cron_expr=cron_expr,
        agent_id=agent_id,
        prompt=prompt,
        channel_type=channel_type,
        tenant_id=tenant_id,
        authorized_tools=authorized_tools,
        trigger_type=trigger_type,
        event_type=event_type,
        execute_at=execute_at,
        enabled=enabled,
    )
    _tasks[tid] = task.to_dict()
    await _save_tasks_to_redis(_tasks)
    logger.info("Scheduled proactive task '%s' with cron '%s'", tid, cron_expr)
    return task


async def cancel_task(task_id: str, tenant_id: Optional[str] = None) -> bool:
    """Remove a scheduled task. Returns False if not found."""
    await _refresh_tasks_from_redis()
    raw = _tasks.get(task_id)
    if raw is not None and (tenant_id is None or raw.get("tenant_id") == tenant_id):
        del _tasks[task_id]
        await _save_tasks_to_redis(_tasks)
        logger.info("Cancelled proactive task '%s'", task_id)
        return True
    return False


async def get_task(task_id: str, tenant_id: Optional[str] = None) -> Optional[ProactiveTask]:
    """Retrieve a single task by ID."""
    await _refresh_tasks_from_redis()
    raw = _tasks.get(task_id)
    if raw is None:
        return None
    if tenant_id is not None and raw.get("tenant_id") != tenant_id:
        return None
    return ProactiveTask.from_dict(raw)


async def list_tasks(tenant_id: Optional[str] = None) -> list[ProactiveTask]:
    """Return all registered proactive tasks."""
    await _refresh_tasks_from_redis()
    return [
        ProactiveTask.from_dict(v)
        for v in _tasks.values()
        if tenant_id is None or v.get("tenant_id") == tenant_id
    ]


async def execute_proactive_task(ctx: dict, task_id: str) -> dict:
    """Run the agent for a scheduled task and deliver the result."""
    logger.info("Executing proactive task '%s'", task_id)

    task = await get_task(task_id)
    if task is None:
        result = {
            "status": "error",
            "task_id": task_id,
            "delivered": False,
            "error": f"Task '{task_id}' not found",
        }
        await _record_task_run({**result, "created_at": datetime.now(timezone.utc).isoformat()})
        return result
    if not task.enabled:
        result = {
            "status": "skipped",
            "task_id": task_id,
            "tenant_id": task.tenant_id,
            "delivered": False,
            "error": "Task is disabled",
        }
        await _record_task_run({**result, "created_at": datetime.now(timezone.utc).isoformat()})
        await _audit_proactive_result(task, result)
        return result

    from app.core.agent.code_executor import CODE_AS_ACTION_TOOL
    from app.core.agent.engine import run_agent
    from app.core.channel.base import ChannelMessage
    from app.core.tools.builtin import ALL_TOOLS

    llm_gateway = ctx.get("llm_gateway")
    sandbox_manager = ctx.get("sandbox_manager")
    if llm_gateway is None or sandbox_manager is None:
        from app.main import app_state

        llm_gateway = llm_gateway or app_state.llm_gateway
        sandbox_manager = sandbox_manager or app_state.sandbox_manager

    if llm_gateway is None or sandbox_manager is None:
        error_message = "Worker runtime dependencies are not initialized"
        result = {
            "status": "error",
            "task_id": task_id,
            "delivered": False,
            "error": error_message,
        }
        await _record_task_run({**result, "created_at": datetime.now(timezone.utc).isoformat()})
        await _audit_proactive_result(task, result)
        return result

    try:
        channel = await _resolve_delivery_channel(task)
    except Exception as exc:
        result = {
            "status": "error",
            "task_id": task_id,
            "tenant_id": task.tenant_id,
            "delivered": False,
            "error": safe_error_message(exc, "Channel configuration"),
        }
        await _record_task_run({**result, "created_at": datetime.now(timezone.utc).isoformat()})
        await _audit_proactive_result(task, result)
        return result

    response_text = ""
    tool_calls_made: list[str] = []
    blocked_tools: list[dict[str, Any]] = []
    blocked_tool_names: set[str] = set()
    blocked_tool_attempts = 0
    error = None
    all_tools = ALL_TOOLS + [CODE_AS_ACTION_TOOL]
    authorized_tool_names = {
        tool.get("function", {}).get("name")
        for tool in all_tools
        if tool.get("function", {}).get("name")
        and is_pre_authorized(tool.get("function", {}).get("name", ""), task.authorized_tools)
    }

    try:
        async for event in run_agent(
            gateway=llm_gateway,
            sandbox_manager=sandbox_manager,
            provider="default",
            messages=[{"role": "user", "content": task.prompt}],
            tools=all_tools,
            authorized_tool_names=authorized_tool_names,
            tenant_id=task.tenant_id,
        ):
            if event["type"] == "text":
                response_text += event["content"]
            elif event["type"] == "tool_call_start":
                tool_calls_made.append(event["name"])
            elif event["type"] == "tool_error" and event.get("blocked"):
                blocked_tool_attempts += 1
                name = str(event.get("name") or "")
                if name not in blocked_tool_names:
                    blocked_tool_names.add(name)
                    blocked_tools.append(
                        {
                            "name": name,
                            "reason": event.get("rejection_reason") or event.get("error"),
                        }
                    )
            elif event["type"] == "error":
                error = event.get("message", "Unknown error")
    except Exception as exc:
        error = safe_error_message(exc, "Agent execution")
        logger.error("Agent execution failed for task '%s'", task_id)

    content_parts = [
        f"**Task**: {task.prompt}",
        f"**Response**:\n{response_text[:1000]}",
    ]
    if tool_calls_made:
        content_parts.append(f"**Tools used**: {', '.join(tool_calls_made)}")
    if blocked_tools:
        content_parts.append(
            "**Blocked tools**: "
            + ", ".join(str(item.get("name")) for item in blocked_tools)
        )
    if error:
        content_parts.append(f"**Error**: {error}")

    if blocked_tools:
        delivery = {
            "ok": False,
            "attempts": 0,
            "status_code": None,
            "error": "Blocked unauthorized proactive tool call",
            "skipped": True,
        }
    else:
        delivery = await channel.send_with_result(
            ChannelMessage(
                title=f"Proactive Task: {task_id[:8]}",
                content="\n\n".join(content_parts),
            )
        )

    delivered = delivery["ok"]
    status = "blocked" if blocked_tools else ("completed" if not error else "error")
    if not delivered and status == "completed":
        status = "delivery_failed"

    result = {
        "status": status,
        "task_id": task_id,
        "tenant_id": task.tenant_id,
        "response_length": len(response_text),
        "tool_calls": tool_calls_made,
        "authorized_tools": task.authorized_tools,
        "blocked_tools": blocked_tools,
        "blocked_tool_attempts": blocked_tool_attempts,
        "attempt": 1,
        "delivered": delivered,
        "delivery": delivery,
        "error": error,
    }
    await _record_task_run(
        {
            **result,
            "prompt_sha256": hashlib.sha256(task.prompt.encode("utf-8")).hexdigest(),
            "tenant_id": task.tenant_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    await _audit_proactive_result(task, result)
    logger.info(
        "Proactive task '%s' completed, delivered=%s, tools=%s",
        task_id,
        delivered,
        tool_calls_made,
    )
    return result


async def _resolve_delivery_channel(task: ProactiveTask):
    """Build a delivery channel only from the tenant-scoped database owner."""
    from app.core.channel.feishu import FeishuChannel

    if not task.tenant_id:
        raise ValueError("Tenant scope is required for proactive channel resolution")
    resolved_channel = await resolve_channel_configuration(task.tenant_id, task.channel_type)
    if task.channel_type != "feishu":
        raise ValueError("Unsupported proactive channel type")
    webhook_url = resolved_channel["secrets"].get("webhook_url")
    if not webhook_url:
        raise ValueError("Configured channel webhook is missing")
    return FeishuChannel(webhook_url, signing_secret=resolved_channel["secrets"].get("secret"))


async def _audit_proactive_result(task: ProactiveTask, result: dict[str, Any]) -> None:
    """Persist a bounded, secret-free audit record for a proactive action."""
    if not task.tenant_id:
        return
    try:
        from app.api.deps import _async_session_factory
        from app.core.audit.service import AuditRecord, write_audit_log

        async with _async_session_factory() as db:
            await write_audit_log(
                db,
                AuditRecord(
                    tenant_id=UUID(task.tenant_id),
                    action="EXECUTE proactive-task",
                    resource_type="proactive-tasks",
                    resource_id=task.task_id,
                    method="WORKER",
                    path=f"/internal/proactive-tasks/{task.task_id}/execute",
                    status_code=200 if result.get("status") == "completed" else 500,
                    details={
                        "status": result.get("status"),
                        "delivered": bool(result.get("delivered")),
                        "tool_calls": list(result.get("tool_calls") or []),
                        "blocked_tools": list(result.get("blocked_tools") or []),
                    },
                ),
            )
    except Exception:
        logger.warning("Could not audit proactive task '%s'", task.task_id)


async def check_scheduled_tasks(ctx: dict) -> None:
    """Enqueue enabled cron and due delayed tasks."""
    from croniter import croniter

    await write_worker_heartbeat(ctx["redis"])

    now = datetime.now(timezone.utc)
    min_window = now.replace(second=0, microsecond=0)
    run_key = min_window.strftime("%Y%m%d%H%M")

    tasks = await list_tasks()
    enqueued = 0
    for task in tasks:
        if not task.enabled:
            continue
        if task.trigger_type == "delayed":
            if not task.execute_at or _parse_utc_datetime(task.execute_at) > now:
                continue
            job = await _enqueue_proactive_job(
                ctx,
                task,
                job_key=f"delayed:{task.task_id}",
            )
            await cancel_task(task.task_id, task.tenant_id)
        elif task.trigger_type != "cron" or not croniter.match(task.cron_expr, min_window):
            continue
        else:
            job = await _enqueue_proactive_job(
                ctx,
                task,
                job_key=f"proactive:{task.task_id}:{run_key}",
            )
        if job is not None:
            enqueued += 1
            logger.info("Enqueued proactive task '%s' (cron: %s)", task.task_id, task.cron_expr)
    logger.debug("Checked %d tasks, enqueued %d", len(tasks), enqueued)


async def trigger_event_tasks(
    ctx: dict,
    *,
    tenant_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Enqueue enabled event-triggered tasks for one tenant/event boundary."""
    await write_worker_heartbeat(ctx["redis"])
    enqueued = 0
    for task in await list_tasks(tenant_id):
        if (
            not task.enabled
            or task.trigger_type != "event"
            or task.event_type != event_type
        ):
            continue
        job = await _enqueue_proactive_job(
            ctx,
            task,
            job_key=f"event:{task.task_id}:{uuid4().hex}",
            payload=payload,
        )
        if job is not None:
            enqueued += 1
    return enqueued


async def _enqueue_proactive_job(
    ctx: dict,
    task: ProactiveTask,
    *,
    job_key: str,
    payload: dict[str, Any] | None = None,
):
    _ = payload
    return await ctx["redis"].enqueue_job(
        "execute_proactive_task",
        task.task_id,
        _job_id=job_key,
        _queue_name=ARQ_QUEUE_NAME,
    )


async def startup(ctx: dict) -> None:
    """Initialize runtime dependencies for the standalone ARQ worker."""
    from app.config import validate_production_settings
    from app.core.llm.gateway import LLMGateway
    from app.core.sandbox.manager import SandboxManager

    validate_production_settings(settings)
    llm_gateway = LLMGateway()
    sandbox_manager = SandboxManager(settings)
    try:
        await sandbox_manager.warm_pool()
    except Exception as exc:
        logger.warning("Worker could not warm sandbox pool: %s", exc)

    ctx["llm_gateway"] = llm_gateway
    ctx["sandbox_manager"] = sandbox_manager
    await write_worker_heartbeat(ctx["redis"])


async def shutdown(ctx: dict) -> None:
    """Close worker-owned runtime resources."""
    sandbox_manager = ctx.get("sandbox_manager")
    if sandbox_manager is not None:
        await sandbox_manager.close()


class WorkerSettings:
    """ARQ worker settings for proactive scheduling."""

    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [execute_proactive_task, process_acquisition_analysis, process_capability_analysis]
    cron_jobs = [
        cron(check_scheduled_tasks, minute=None),
        cron(process_acquisition_analysis, minute=None),
        cron(process_capability_analysis, minute=None),
    ]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = ARQ_QUEUE_NAME
