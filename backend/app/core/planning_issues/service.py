"""Runtime planning issue classification and lifecycle."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.acquisition import RuntimePlanningIssue

from . import repository


@dataclass(frozen=True)
class PlanningIssueClassification:
    should_create_gap: bool
    issue_type: str | None
    gap_type: str | None
    severity: str
    reason: str


def classify_runtime_issue(
    *,
    failure_reason: str | None = None,
    available_capability_ref: dict[str, Any] | None = None,
    missing_credential: bool = False,
    missing_prompt_context: bool = False,
) -> PlanningIssueClassification:
    """Separate planner misses from true capability gaps."""

    if missing_credential:
        return PlanningIssueClassification(
            should_create_gap=True,
            issue_type=None,
            gap_type="missing_credential",
            severity="medium",
            reason="Missing credential requires acquisition rather than planner repair.",
        )
    if available_capability_ref:
        return PlanningIssueClassification(
            should_create_gap=False,
            issue_type="planner_missed_existing_tool",
            gap_type=None,
            severity="medium",
            reason="An available capability existed but the planner skipped it.",
        )
    if missing_prompt_context:
        return PlanningIssueClassification(
            should_create_gap=False,
            issue_type="wrong_fallback_choice",
            gap_type=None,
            severity="low",
            reason="The agent lacked or ignored prompt context rather than missing a new capability.",
        )
    reason_text = str(failure_reason or "").casefold()
    if "existing tool" in reason_text or "planner miss" in reason_text:
        return PlanningIssueClassification(
            should_create_gap=False,
            issue_type="planner_missed_existing_tool",
            gap_type=None,
            severity="medium",
            reason="Failure evidence indicates a planner miss.",
        )
    return PlanningIssueClassification(
        should_create_gap=True,
        issue_type=None,
        gap_type="requires_code_patch",
        severity="medium",
        reason="Failure likely needs a new or improved capability.",
    )


async def create_runtime_planning_issue(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_run_id: str,
    conversation_id: uuid.UUID | None = None,
    issue_type: str,
    available_capability_ref: dict[str, Any],
    missed_signal: str,
    planner_decision_summary: str,
    expected_decision_summary: str,
    severity: str = "medium",
    evidence: dict[str, Any] | None = None,
) -> RuntimePlanningIssue:
    issue = await repository.create_issue(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        source_run_id=source_run_id,
        conversation_id=conversation_id,
        issue_type=issue_type,
        available_capability_ref=available_capability_ref,
        missed_signal=missed_signal,
        planner_decision_summary=planner_decision_summary,
        expected_decision_summary=expected_decision_summary,
        severity=severity,
        evidence=evidence or {},
    )
    return issue


async def dismiss_runtime_planning_issue(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    issue_id: uuid.UUID,
) -> RuntimePlanningIssue:
    issue = await repository.get_issue(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        issue_id=issue_id,
    )
    if issue is None:
        raise ValueError("runtime planning issue not found")
    issue.status = "dismissed"
    await db.flush()
    return issue
