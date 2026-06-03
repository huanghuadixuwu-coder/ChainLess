"""Proactive task CRUD API — create, list, and delete scheduled tasks.

Endpoints:
    POST   /proactive-tasks     — create a new scheduled task
    GET    /proactive-tasks     — list all scheduled tasks
    DELETE /proactive-tasks/{id} — delete a scheduled task
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.proactive import schedule_task, cancel_task, list_tasks, get_task

router = APIRouter(prefix="/proactive-tasks", tags=["proactive"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateTaskRequest(BaseModel):
    type: str = "cron"
    cron_expr: str = "0 9 * * *"
    agent_id: str = "default"
    prompt: str = ""
    channel_type: str = "feishu"
    channel_config: dict = {}


class TaskResponse(BaseModel):
    task_id: str
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
    _: dict = Depends(get_current_user),
):
    """Create a new scheduled proactive task."""
    task = await schedule_task(
        cron_expr=body.cron_expr,
        agent_id=body.agent_id,
        prompt=body.prompt,
        channel_type=body.channel_type,
        channel_config=body.channel_config,
    )
    return TaskResponse(
        task_id=task.task_id,
        cron_expr=task.cron_expr,
        agent_id=task.agent_id,
        prompt=task.prompt,
        channel_type=task.channel_type,
        enabled=task.enabled,
        created_at=task.created_at,
    )


@router.get("")
async def list_proactive_tasks(
    _: dict = Depends(get_current_user),
):
    """List all scheduled proactive tasks."""
    tasks = await list_tasks()
    items = [
        TaskResponse(
            task_id=t.task_id,
            cron_expr=t.cron_expr,
            agent_id=t.agent_id,
            prompt=t.prompt,
            channel_type=t.channel_type,
            enabled=t.enabled,
            created_at=t.created_at,
        )
        for t in tasks
    ]
    return {
        "items": items,
        "total": len(items),
    }


@router.delete("/{task_id}")
async def delete_proactive_task(
    task_id: str,
    _: dict = Depends(get_current_user),
):
    """Delete a scheduled proactive task."""
    removed = await cancel_task(task_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )
    return {"status": "ok", "task_id": task_id}
