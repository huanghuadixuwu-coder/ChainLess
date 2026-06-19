"""Natural-language Worker control intents and confirmed control actions."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import not_found, validation_error
from app.core.workers.service import soft_delete_worker
from app.models.worker import Worker

WORKER_DELETE_TOOL_NAME = "worker_delete"

_WORKER_DELETE_RE = re.compile(
    "\\b(delete|remove|archive|soft[-\\s]?delete)\\b"
    "|\\u5220\\u9664|\\u79fb\\u9664|\\u5f52\\u6863",
    re.IGNORECASE,
)
_WORKER_NOUN_RE = re.compile("\\bworker\\b|\\u667a\\u80fd\\u4f53|\\u5de5\\u4f5c", re.IGNORECASE)
_WORKER_REFERENCE_EDIT_RE = re.compile(
    "\\b(references?|mentions?|links?|docs?|documentation|code|source|readme|text|file|files)\\b",
    re.IGNORECASE,
)


async def queue_worker_delete_confirmation(
    db: AsyncSession,
    *,
    queue: asyncio.Queue,
    tenant_id: str,
    user_id: str,
    request: str,
    timeout_s: int,
) -> Literal["none", "bypass_worker", "queued"]:
    if not _is_worker_delete_control_request(request):
        return "none"
    if _is_worker_reference_edit_request(request):
        return "bypass_worker"

    tenant_uuid = uuid.UUID(str(tenant_id))
    user_uuid = uuid.UUID(str(user_id))
    workers = list(
        (
            await db.execute(
                select(Worker).where(
                    Worker.tenant_id == tenant_uuid,
                    Worker.user_id == user_uuid,
                    Worker.soft_deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    request_key = request.casefold()
    matches = [worker for worker in workers if worker.name.casefold() in request_key]
    if len(matches) != 1:
        return "bypass_worker"

    worker = matches[0]
    await queue.put(
        (
            "confirmation_required",
            {
                "tool_call_id": f"worker-delete-{uuid.uuid4()}",
                "tool_name": WORKER_DELETE_TOOL_NAME,
                "args": {
                    "worker_id": str(worker.id),
                    "worker_name": worker.name,
                },
                "risk": "destructive",
                "timeout_s": timeout_s,
            },
        )
    )
    await queue.put(("done", {"tokens_used": 0}))
    return "queued"


async def execute_confirmed_worker_delete(
    args: dict,
    *,
    tenant_id: str,
    user_id: str | None,
) -> str:
    if not user_id:
        raise validation_error("Worker delete confirmation requires a user")
    worker_id = args.get("worker_id")
    if not worker_id:
        raise validation_error("worker_id is required")
    tenant_uuid = uuid.UUID(str(tenant_id))
    user_uuid = uuid.UUID(str(user_id))
    worker_uuid = uuid.UUID(str(worker_id))

    from app.api.deps import _async_session_factory

    async with _async_session_factory() as db:
        worker = (
            await db.execute(
                select(Worker).where(
                    Worker.id == worker_uuid,
                    Worker.tenant_id == tenant_uuid,
                    Worker.user_id == user_uuid,
                    Worker.soft_deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if worker is None:
            raise not_found("WORKER_NOT_FOUND", "Worker not found")
        worker_name = worker.name
        await soft_delete_worker(db, worker)
    return f"Worker '{worker_name}' was soft deleted after confirmation."


def _is_worker_delete_control_request(request: str) -> bool:
    if not request.strip():
        return False
    return bool(_WORKER_DELETE_RE.search(request) and _WORKER_NOUN_RE.search(request))


def _is_worker_reference_edit_request(request: str) -> bool:
    return bool(_WORKER_REFERENCE_EDIT_RE.search(request))
