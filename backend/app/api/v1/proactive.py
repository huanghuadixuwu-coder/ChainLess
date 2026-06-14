"""Proactive task CRUD API — create, list, and delete scheduled tasks.

Endpoints:
    POST   /proactive-tasks     — create a new scheduled task
    GET    /proactive-tasks     — list all scheduled tasks
    DELETE /proactive-tasks/{id} — delete a scheduled task
"""

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict

from app.api.contracts import not_found
from app.api.deps import require_role
from app.api.pagination import paginated_response
from app.core.proactive import (
    cancel_task,
    count_run_records,
    list_run_records,
    list_tasks,
    schedule_task,
)

router = APIRouter(prefix="/proactive-tasks", tags=["proactive"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "cron"
    cron_expr: str = "0 9 * * *"
    agent_id: str = "default"
    prompt: str = ""
    channel_type: str = "feishu"


class TaskResponse(BaseModel):
    task_id: str
    tenant_id: str | None = None
    cron_expr: str
    agent_id: str
    prompt: str
    channel_type: str
    enabled: bool
    created_at: str


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_proactive_task(
    body: CreateTaskRequest,
    current_user: dict = Depends(require_role("admin")),
):
    """Create a new scheduled proactive task."""
    task = await schedule_task(
        tenant_id=current_user["tenant_id"],
        cron_expr=body.cron_expr,
        agent_id=body.agent_id,
        prompt=body.prompt,
        channel_type=body.channel_type,
    )
    return TaskResponse(
        task_id=task.task_id,
        tenant_id=task.tenant_id,
        cron_expr=task.cron_expr,
        agent_id=task.agent_id,
        prompt=task.prompt,
        channel_type=task.channel_type,
        enabled=task.enabled,
        created_at=task.created_at,
    )


@router.get("")
async def list_proactive_tasks(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    current_user: dict = Depends(require_role("admin")),
):
    """List all scheduled proactive tasks."""
    tasks = await list_tasks(current_user["tenant_id"])
    items = [
        TaskResponse(
            task_id=t.task_id,
            tenant_id=t.tenant_id,
            cron_expr=t.cron_expr,
            agent_id=t.agent_id,
            prompt=t.prompt,
            channel_type=t.channel_type,
            enabled=t.enabled,
            created_at=t.created_at,
        )
        for t in tasks
    ]
    total = len(items)
    return paginated_response(items[offset:offset + limit], total, limit, offset, request)


@router.get("/runs")
async def list_proactive_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    current_user: dict = Depends(require_role("admin")),
):
    """List recent proactive task executions for runtime verification."""
    tenant_id = current_user["tenant_id"]
    records = await list_run_records(limit + offset, tenant_id)
    total = await count_run_records(tenant_id)
    return paginated_response(records[offset:offset + limit], total, limit, offset, request)


@router.delete("/{task_id}")
async def delete_proactive_task(
    task_id: str,
    current_user: dict = Depends(require_role("admin")),
):
    """Delete a scheduled proactive task."""
    removed = await cancel_task(task_id, current_user["tenant_id"])
    if not removed:
        raise not_found("TASK_NOT_FOUND", f"Task '{task_id}' not found")
    return {"status": "ok", "task_id": task_id}
