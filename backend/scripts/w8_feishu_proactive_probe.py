"""W8 live Feishu-compatible proactive delivery probe.

Runs entirely inside the backend container. It starts a local HTTP receiver,
sends one Feishu-compatible test message, executes one proactive task through
the scheduler delivery path, then removes exact-prefix QA state.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select

from app.api.deps import _async_session_factory
from app.core.channel.base import ChannelMessage
from app.core.channel.feishu import FeishuChannel
from app.core.proactive import scheduler
from app.core.secrets import encrypt_secret
from app.models.channel_configuration import ChannelConfiguration
from app.models.tenant import Tenant


class _Receiver:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> str:
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8"))
                except Exception:
                    body = {"_raw": raw.decode("utf-8", errors="replace")}
                with receiver._lock:
                    receiver.payloads.append({"path": self.path, "body": body})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, *_args) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        host, port = self._server.server_address
        return f"http://{host}:{port}/hook"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()


class _Gateway:
    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        yield {"type": "text", "content": "w8 proactive delivery ok"}


class _Queue:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def set(self, *args, **kwargs):
        return None

    async def enqueue_job(self, name, task_id, **kwargs):
        self.jobs.append({"name": name, "task_id": task_id, **kwargs})
        return {"job_id": kwargs.get("_job_id")}


async def _create_tenant_with_channel(tenant_name: str, webhook_url: str) -> str:
    async with _async_session_factory() as db:
        tenant = Tenant(name=tenant_name, settings={})
        db.add(tenant)
        await db.flush()
        db.add(
            ChannelConfiguration(
                tenant_id=tenant.id,
                channel_type="feishu",
                public_config={"label": "w8-probe"},
                encrypted_secrets=encrypt_secret(
                    json.dumps({"webhook_url": webhook_url}, separators=(",", ":"))
                ),
                enabled=True,
            )
        )
        await db.commit()
        return str(tenant.id)


async def _delete_tenant_by_name(tenant_name: str) -> None:
    async with _async_session_factory() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.name == tenant_name))
        ).scalar_one_or_none()
        if tenant is not None:
            await db.execute(
                delete(ChannelConfiguration).where(
                    ChannelConfiguration.tenant_id == tenant.id
                )
            )
            await db.delete(tenant)
            await db.commit()


async def _tenant_exists(tenant_name: str) -> bool:
    async with _async_session_factory() as db:
        return (
            await db.execute(select(Tenant.id).where(Tenant.name == tenant_name))
        ).scalar_one_or_none() is not None


async def _remove_probe_run_records(task_ids: set[str]) -> int:
    redis = await scheduler._get_redis_client()
    rows = await redis.lrange(scheduler.ARQ_RUN_LOG_KEY, 0, -1)
    retained: list[str] = []
    removed = 0
    for row in rows:
        try:
            record = json.loads(row)
        except Exception:
            retained.append(row)
            continue
        if record.get("task_id") in task_ids:
            removed += 1
        else:
            retained.append(row)
    await redis.delete(scheduler.ARQ_RUN_LOG_KEY)
    if retained:
        await redis.rpush(scheduler.ARQ_RUN_LOG_KEY, *retained)
    return removed


async def main() -> dict[str, Any]:
    suffix = f"{int(time.time())}-{uuid4().hex[:8]}"
    tenant_name = f"w8-feishu-probe-{suffix}"
    receiver = _Receiver()
    webhook_url = receiver.start()
    task_ids: set[str] = set()

    try:
        tenant_id = await _create_tenant_with_channel(tenant_name, webhook_url)

        test_delivery = await FeishuChannel(webhook_url).send_with_result(
            ChannelMessage(
                title="W8 Feishu Test",
                content="w8 feishu-compatible test payload",
            )
        )

        delivery_task = await scheduler.schedule_task(
            tenant_id=tenant_id,
            task_id=f"w8-delivery-{uuid4().hex}",
            prompt="send w8 proactive delivery proof",
            channel_type="feishu",
            authorized_tools=[],
        )
        task_ids.add(delivery_task.task_id)
        proactive_delivery = await scheduler.execute_proactive_task(
            {"llm_gateway": _Gateway(), "sandbox_manager": object()},
            delivery_task.task_id,
        )
        await scheduler.cancel_task(delivery_task.task_id, tenant_id)

        delayed_task = await scheduler.schedule_task(
            tenant_id=tenant_id,
            task_id=f"w8-delayed-{uuid4().hex}",
            prompt="w8 delayed cleanup proof",
            channel_type="feishu",
            trigger_type="delayed",
            execute_at=datetime.now(timezone.utc).isoformat(),
        )
        task_ids.add(delayed_task.task_id)
        queue = _Queue()
        await scheduler.check_scheduled_tasks({"redis": queue})
        await scheduler.check_scheduled_tasks({"redis": queue})

        tasks_after_delete = [
            task.task_id
            for task in await scheduler.list_tasks(tenant_id)
            if task.task_id in task_ids
        ]
        run_records_before_cleanup = [
            record
            for record in await scheduler.list_run_records(20, tenant_id)
            if record.get("task_id") in task_ids
        ]
        removed_run_records = await _remove_probe_run_records(task_ids)
        await _delete_tenant_by_name(tenant_name)
        redis_report = await scheduler.inspect_redis_proactive_state()

        return {
            "ok": (
                test_delivery["ok"] is True
                and proactive_delivery["status"] == "completed"
                and proactive_delivery["delivered"] is True
                and len(receiver.payloads) == 2
                and len(queue.jobs) == 1
                and queue.jobs[0]["task_id"] == delayed_task.task_id
                and tasks_after_delete == []
                and await _tenant_exists(tenant_name) is False
            ),
            "tenant": tenant_name,
            "test_delivery": test_delivery,
            "proactive_delivery": {
                "status": proactive_delivery["status"],
                "delivered": proactive_delivery["delivered"],
                "delivery": proactive_delivery["delivery"],
                "blocked_tools": proactive_delivery["blocked_tools"],
            },
            "receiver_payload_count": len(receiver.payloads),
            "receiver_payload_shapes": [
                {
                    "path": item["path"],
                    "msg_type": item["body"].get("msg_type"),
                    "title": item["body"]
                    .get("card", {})
                    .get("header", {})
                    .get("title", {})
                    .get("content"),
                    "element_tags": [
                        element.get("tag")
                        for element in item["body"].get("card", {}).get("elements", [])
                    ],
                }
                for item in receiver.payloads
            ],
            "delayed_enqueue_jobs": queue.jobs,
            "tasks_after_delete": tasks_after_delete,
            "run_records_before_cleanup": len(run_records_before_cleanup),
            "removed_run_records": removed_run_records,
            "redis_report_after_cleanup": redis_report,
            "tenant_exists_after_cleanup": await _tenant_exists(tenant_name),
        }
    finally:
        for task_id in task_ids:
            await scheduler.cancel_task(task_id)
        await _remove_probe_run_records(task_ids)
        await _delete_tenant_by_name(tenant_name)
        receiver.stop()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))
