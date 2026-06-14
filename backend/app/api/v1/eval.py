"""Admin-only eval suite administration API."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import not_found, validation_error
from app.api.deps import get_db, require_role
from app.api.pagination import paginated_response
from app.core.audit.service import AuditRecord, write_audit_log

router = APIRouter(prefix="/eval", tags=["eval"])
Admin = Depends(require_role("admin"))

BACKEND_DIR = Path(__file__).resolve().parents[3]
TASKS_DIR = BACKEND_DIR / "tests" / "eval" / "tasks"
RESULTS_DIR = BACKEND_DIR / "tests" / "eval" / "results"
RUN_EVAL_SCRIPT = BACKEND_DIR / "scripts" / "run-eval.py"
SUITE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class EvalRunRequest(BaseModel):
    suite: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=80)
    dry_run: bool = True
    timeout_s: int = Field(default=5, ge=1, le=60)
    min_pass_rate: float = Field(default=0.70, ge=0.0, le=1.0)


def _tenant_id(user: dict) -> uuid.UUID:
    return uuid.UUID(user["tenant_id"])


def _suite_path(suite: str) -> Path:
    if not SUITE_NAME_RE.fullmatch(suite):
        raise validation_error("Eval suite name is invalid")
    path = TASKS_DIR / f"{suite}.json"
    if not path.exists() or not path.is_file():
        raise not_found("EVAL_SUITE_NOT_FOUND", "Eval suite not found")
    return path


def _result_path(suite: str) -> Path:
    return RESULTS_DIR / f"{suite}_results.json"


def _suite_names() -> list[str]:
    if not TASKS_DIR.exists():
        return []
    return sorted(path.stem for path in TASKS_DIR.glob("*.json") if path.is_file())


def _read_suite_summary(suite: str) -> dict[str, Any]:
    path = _suite_path(suite)
    try:
        tasks = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise validation_error("Eval suite JSON is invalid", {"suite": suite}) from exc
    if not isinstance(tasks, list):
        raise validation_error("Eval suite must contain a list of tasks", {"suite": suite})
    return {
        "name": suite,
        "task_count": len(tasks),
        "tasks": [
            {
                "id": str(task.get("id", "")),
                "criteria": task.get("pass_criteria"),
                "judge": task.get("judge"),
            }
            for task in tasks
            if isinstance(task, dict)
        ],
    }


def _safe_status(suite: str) -> dict[str, Any]:
    result_path = _result_path(suite)
    if not result_path.exists():
        return {
            "suite": suite,
            "status": "not_run",
            "summary": None,
            "updated_at": None,
        }
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        summary = payload.get("summary") if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        summary = None
    return {
        "suite": suite,
        "status": "completed" if summary else "result_unreadable",
        "summary": summary if isinstance(summary, dict) else None,
        "updated_at": datetime.fromtimestamp(
            result_path.stat().st_mtime,
            timezone.utc,
        ).isoformat(),
    }


async def _audit_eval_action(
    db: AsyncSession,
    user: dict,
    *,
    action: str,
    path: str,
    method: str,
    status_code: int,
    details: dict[str, Any],
) -> None:
    await write_audit_log(
        db,
        AuditRecord(
            tenant_id=_tenant_id(user),
            user_id=uuid.UUID(user["user_id"]),
            action=action,
            resource_type="eval",
            method=method,
            path=path,
            status_code=status_code,
            details=details,
        ),
    )


@router.get("/suites")
async def list_eval_suites(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    names = _suite_names()
    page_names = names[offset : offset + limit]
    items = [_read_suite_summary(name) for name in page_names]
    await _audit_eval_action(
        db,
        user,
        action="LIST eval-suites",
        path="/api/v1/eval/suites",
        method="GET",
        status_code=200,
        details={"suite_count": len(names), "audited_without_body": True},
    )
    return paginated_response(items, len(names), limit, offset, request)


@router.get("/status")
async def list_eval_status(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    names = _suite_names()
    page_names = names[offset : offset + limit]
    await _audit_eval_action(
        db,
        user,
        action="LIST eval-status",
        path="/api/v1/eval/status",
        method="GET",
        status_code=200,
        details={"suite_count": len(names), "audited_without_body": True},
    )
    return paginated_response(
        [_safe_status(name) for name in page_names],
        len(names),
        limit,
        offset,
        request,
    )


@router.get("/suites/{suite}/status")
async def get_eval_suite_status(
    suite: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    _suite_path(suite)
    status_body = _safe_status(suite)
    await _audit_eval_action(
        db,
        user,
        action="GET eval-status",
        path="/api/v1/eval/suites/{suite}/status",
        method="GET",
        status_code=200,
        details={"suite": suite, "audited_without_body": True},
    )
    return status_body


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_eval_suite(
    body: EvalRunRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    _suite_path(body.suite)
    result: dict[str, Any] = {
        "suite": body.suite,
        "dry_run": body.dry_run,
        "executed": False,
        "status": "validated",
        "message": "Eval suite exists; dry_run=true so no eval process was started.",
    }
    status_code = status.HTTP_202_ACCEPTED
    if not body.dry_run:
        result = await _run_eval_subprocess(body, tenant_id=str(_tenant_id(user)))
        status_code = 200 if result["status"] == "completed" else status.HTTP_202_ACCEPTED
    response.status_code = status_code

    await _audit_eval_action(
        db,
        user,
        action="RUN eval-suite",
        path="/api/v1/eval/run",
        method="POST",
        status_code=status_code,
        details={
            "suite": body.suite,
            "dry_run": body.dry_run,
            "executed": result["executed"],
            "status": result["status"],
            "audited_without_body": True,
        },
    )
    return result


async def _run_eval_subprocess(body: EvalRunRequest, *, tenant_id: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(RUN_EVAL_SCRIPT),
        "--suite",
        body.suite,
        "--json",
        "--tenant-id",
        tenant_id,
        "--min-pass-rate",
        str(body.min_pass_rate),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(BACKEND_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=body.timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {
                "suite": body.suite,
                "dry_run": False,
                "executed": True,
                "status": "timeout",
                "exit_code": None,
                "message": "Eval process timed out before completion.",
            }
    except OSError:
        return {
            "suite": body.suite,
            "dry_run": False,
            "executed": False,
            "status": "start_failed",
            "exit_code": None,
            "message": "Eval process could not be started.",
        }

    summary = _safe_status(body.suite).get("summary")
    return {
        "suite": body.suite,
        "dry_run": False,
        "executed": True,
        "status": "completed" if proc.returncode == 0 else "failed",
        "exit_code": proc.returncode,
        "summary": summary,
        "stdout_bytes": len(stdout or b""),
        "stderr_bytes": len(stderr or b""),
        "message": "Eval process finished; raw output is intentionally not returned.",
    }
