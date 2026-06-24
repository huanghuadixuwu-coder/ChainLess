"""Persistence helpers for RuntimePlanningIssue."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities.bounds import validate_bounded_json
from app.models.acquisition import RuntimePlanningIssue


async def create_issue(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_run_id: str,
    conversation_id: uuid.UUID | None,
    issue_type: str,
    available_capability_ref: dict[str, Any],
    missed_signal: str,
    planner_decision_summary: str,
    expected_decision_summary: str,
    severity: str,
    evidence: dict[str, Any],
) -> RuntimePlanningIssue:
    issue = RuntimePlanningIssue(
        tenant_id=tenant_id,
        user_id=user_id,
        source_run_id=source_run_id,
        conversation_id=conversation_id,
        issue_type=issue_type,
        available_capability_ref=validate_bounded_json(available_capability_ref, field="available_capability_ref"),
        missed_signal=missed_signal,
        planner_decision_summary=planner_decision_summary,
        expected_decision_summary=expected_decision_summary,
        severity=severity,
        status="open",
        evidence=validate_bounded_json(evidence, field="evidence"),
    )
    db.add(issue)
    await db.flush()
    return issue


async def get_issue(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    issue_id: uuid.UUID,
) -> RuntimePlanningIssue | None:
    return (
        await db.execute(
            select(RuntimePlanningIssue).where(
                RuntimePlanningIssue.tenant_id == tenant_id,
                RuntimePlanningIssue.user_id == user_id,
                RuntimePlanningIssue.id == issue_id,
            )
        )
    ).scalar_one_or_none()


async def list_issues(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[RuntimePlanningIssue]:
    filters = [
        RuntimePlanningIssue.tenant_id == tenant_id,
        RuntimePlanningIssue.user_id == user_id,
    ]
    if status:
        filters.append(RuntimePlanningIssue.status == status)
    return list(
        (
            await db.execute(
                select(RuntimePlanningIssue)
                .where(*filters)
                .order_by(RuntimePlanningIssue.created_at.desc(), RuntimePlanningIssue.id.desc())
                .limit(max(1, min(int(limit), 100)))
                .offset(max(0, int(offset)))
            )
        ).scalars()
    )
