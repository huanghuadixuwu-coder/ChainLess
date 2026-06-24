"""RuntimePlanningIssue owner coverage for W7."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.acquisition.journal import render_acquisition_journal
from app.core.planning_issues.service import (
    classify_runtime_issue,
    create_runtime_planning_issue,
    dismiss_runtime_planning_issue,
)
from app.models.acquisition import CapabilityGap, RuntimePlanningIssue
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


async def test_planner_miss_creates_runtime_planning_issue_not_gap(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)

    async with _async_session_factory() as db:
        classification = classify_runtime_issue(
            failure_reason="planner missed existing tool",
            available_capability_ref={"tool_name": "weather_get"},
        )
        assert classification.should_create_gap is False
        issue = await create_runtime_planning_issue(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id="w7-planner-miss",
            issue_type=classification.issue_type or "planner_missed_existing_tool",
            available_capability_ref={"tool_name": "weather_get"},
            missed_signal="Existing weather tool was available.",
            planner_decision_summary="Agent tried generic web search.",
            expected_decision_summary="Agent should call weather_get first.",
            severity=classification.severity,
            evidence={"tool_name": "weather_get"},
        )
        await db.commit()

        gaps = list(
            (
                await db.execute(
                    select(CapabilityGap).where(
                        CapabilityGap.tenant_id == tenant_id,
                        CapabilityGap.user_id == user_id,
                    )
                )
            ).scalars()
        )

    assert issue.id
    assert gaps == []


async def test_missing_credential_creates_gap_classification() -> None:
    classification = classify_runtime_issue(missing_credential=True)
    assert classification.should_create_gap is True
    assert classification.gap_type == "missing_credential"
    assert classification.issue_type is None


async def test_missing_prompt_context_creates_runtime_planning_issue(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)

    async with _async_session_factory() as db:
        classification = classify_runtime_issue(missing_prompt_context=True)
        issue = await create_runtime_planning_issue(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id="w7-context-miss",
            issue_type=classification.issue_type or "wrong_fallback_choice",
            available_capability_ref={"context": "project memory"},
            missed_signal="Task context was present in memory but not used.",
            planner_decision_summary="Agent guessed from stale context.",
            expected_decision_summary="Agent should retrieve memory context.",
            severity=classification.severity,
            evidence={"memory_ref": "memory:test"},
        )
        await db.commit()

    assert issue.issue_type == "wrong_fallback_choice"
    assert issue.status == "open"


async def test_runtime_planning_issue_appears_in_journal(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)

    async with _async_session_factory() as db:
        issue = await create_runtime_planning_issue(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id="w7-journal",
            issue_type="planner_missed_existing_tool",
            available_capability_ref={"tool_name": "file_read"},
            missed_signal="file_read was available.",
            planner_decision_summary="Agent listed stale workspace files.",
            expected_decision_summary="Agent should read the selected attachment.",
            severity="high",
            evidence={"source": "test"},
        )
        view = await render_acquisition_journal(db, tenant_id=tenant_id, user_id=user_id)
        dismissed = await dismiss_runtime_planning_issue(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            issue_id=issue.id,
        )
        await db.commit()

    markdown = view.rendered_markdown
    assert f"runtime_planning_issue:{issue.id}" in markdown
    assert "Agent should read the selected attachment." in markdown
    assert dismissed.status == "dismissed"


async def test_runtime_planning_issue_is_user_isolated(
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    tenant_a, user_a = _identity(tenant_a_headers)
    tenant_b, user_b = _identity(tenant_b_headers)

    async with _async_session_factory() as db:
        await create_runtime_planning_issue(
            db,
            tenant_id=tenant_a,
            user_id=user_a,
            source_run_id="w7-isolation",
            issue_type="planner_missed_existing_tool",
            available_capability_ref={"tool_name": "private_tool"},
            missed_signal="private tool skipped",
            planner_decision_summary="missed",
            expected_decision_summary="use private tool",
            severity="medium",
            evidence={},
        )
        await db.commit()

        leaked = list(
            (
                await db.execute(
                    select(RuntimePlanningIssue).where(
                        RuntimePlanningIssue.tenant_id == tenant_b,
                        RuntimePlanningIssue.user_id == user_b,
                    )
                )
            ).scalars()
        )

    assert leaked == []
