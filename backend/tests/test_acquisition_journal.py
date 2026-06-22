"""Acquisition journal read-model and rendering tests."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, null, select

from app.api.deps import _async_session_factory
from app.core.acquisition.journal import (
    DEFAULT_SECTION_LIMIT,
    render_acquisition_journal,
    write_acquisition_journal_snapshot,
)
from app.models.acquisition import (
    AcquisitionJournalEntry,
    AcquisitionProposal,
    ActivationTarget,
    CapabilityGap,
    CapabilityRecommendation,
    DevelopmentPatchProposal,
    RuntimePlanningIssue,
)
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


def _permission_bundle() -> dict:
    return {
        "target_type": "api_tool",
        "permission_scope": {"hosts": ["api.weather.example"]},
        "risk_level": "safe",
        "confirmation_policy": "never_for_safe",
        "credential_scope": "none",
        "credential_connection_refs": [],
        "data_scope": "none",
        "network_scope": "public_web",
        "egress_policy": {"allow_hosts": ["api.weather.example"]},
        "write_scope": "none",
        "execution_scope": "api_tool",
        "duration": "one_run",
        "revocation_plan": {"disable": True},
        "audit_events": [],
    }


async def _gap(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    title: str,
    status: str = "detected",
    dedupe_key: str | None = None,
    source_run_id: str | None = None,
    evidence: dict | None = None,
) -> CapabilityGap:
    async with _async_session_factory() as db:
        gap = CapabilityGap(
            tenant_id=tenant_id,
            user_id=user_id,
            source_kind="agent_runtime",
            source_run_id=source_run_id or f"journal-{uuid.uuid4().hex}",
            dedupe_key=dedupe_key or f"journal-{uuid.uuid4().hex}",
            title=title,
            description=f"{title} description",
            gap_type="missing_api",
            severity="medium",
            status=status,
            source_evidence=[{"kind": "tool_error", "message": "TOOL_NOT_FOUND"}],
            evidence=evidence or {"summary": title},
        )
        db.add(gap)
        await db.commit()
        return gap


async def _recommendation(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    *,
    title: str,
) -> CapabilityRecommendation:
    async with _async_session_factory() as db:
        recommendation = CapabilityRecommendation(
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap_id,
            recommendation_type="api_recommendation",
            title=title,
            summary=f"{title} summary",
            reason=f"{title} reason",
            evidence={"source": "journal-test"},
            risk_level="safe",
            expected_value={"reusable": True},
            required_permissions={"network": "public_web"},
            candidate_targets=[{"target_type": "api_tool", "name": title}],
        )
        db.add(recommendation)
        await db.commit()
        return recommendation


async def _proposal(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    *,
    title: str,
    status: str,
    proposal_kind: str = "runtime_activation",
    evidence: dict | None = None,
) -> AcquisitionProposal:
    async with _async_session_factory() as db:
        proposal = AcquisitionProposal(
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_kind=proposal_kind,
            gap_id=gap_id,
            recommendation_id=recommendation_id,
            title=title,
            reason=f"{title} reason",
            evidence=evidence or {"source": "journal-test"},
            status=status,
            risk_level="safe",
            permission_bundle=_permission_bundle(),
            primary_target=(
                {
                    "target_type": "api_tool",
                    "target_name": title,
                    "target_owner": "core.api_tools",
                    "target_payload": {"base_url": "https://api.weather.example"},
                    "permission_bundle": _permission_bundle(),
                    "verification_plan": {"kind": "contract"},
                    "rollback_plan": {"disable": True},
                    "activation_status": "draft",
                    "activation_result": {},
                }
                if proposal_kind == "runtime_activation"
                else null()
            ),
            secondary_targets=[],
            development_handoff={"patch_artifact_ref": "artifact://patch"} if proposal_kind == "development_patch_proposal" else None,
            verification_plan={"kind": "contract"},
            rollback_plan={"disable": True},
            user_visible_effect=f"{title} user effect",
            approval_history=[],
        )
        db.add(proposal)
        await db.commit()
        return proposal


async def _activation_target(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    *,
    name: str,
    status: str = "active",
) -> ActivationTarget:
    async with _async_session_factory() as db:
        target = ActivationTarget(
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            target_type="api_tool",
            target_name=name,
            target_owner="core.api_tools",
            target_payload={"base_url": "https://api.weather.example"},
            permission_bundle=_permission_bundle(),
            verification_plan={"kind": "contract"},
            rollback_plan={"disable": True},
            activation_status=status,
            activation_result={"manifest_ref": f"api_tool:{name}"},
            activated_resource_ref={"kind": "api_tool", "name": name},
        )
        db.add(target)
        await db.commit()
        return target


async def _planning_issue(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    missed_signal: str,
    status: str = "open",
    evidence: dict | None = None,
) -> RuntimePlanningIssue:
    async with _async_session_factory() as db:
        issue = RuntimePlanningIssue(
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=f"planning-{uuid.uuid4().hex}",
            issue_type="planner_missed_existing_tool",
            available_capability_ref={"type": "tool", "name": "weather"},
            missed_signal=missed_signal,
            planner_decision_summary="Planner tried acquisition.",
            expected_decision_summary="Planner should reuse existing weather tool.",
            severity="medium",
            status=status,
            evidence=evidence or {"source": "journal-test"},
        )
        db.add(issue)
        await db.commit()
        return issue


async def test_journal_groups_open_gaps_proposals_activated_rejected_runtime_issues_and_patch_proposals(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id, title="Open weather gap")
    recommendation = await _recommendation(tenant_id, user_id, gap.id, title="Weather recommendation")
    approval = await _proposal(tenant_id, user_id, gap.id, recommendation.id, title="Needs approval", status="verified")
    rejected = await _proposal(tenant_id, user_id, gap.id, recommendation.id, title="Rejected proposal", status="activation_rejected")
    activated = await _proposal(tenant_id, user_id, gap.id, recommendation.id, title="Activated proposal", status="activated")
    patch = await _proposal(
        tenant_id,
        user_id,
        gap.id,
        recommendation.id,
        title="Patch proposal",
        status="handoff_ready",
        proposal_kind="development_patch_proposal",
    )
    await _activation_target(tenant_id, user_id, activated.id, name="Activated weather")
    await _planning_issue(tenant_id, user_id, missed_signal="Existing weather tool was skipped")
    async with _async_session_factory() as db:
        db.add(
            DevelopmentPatchProposal(
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=patch.id,
                status="handoff_ready",
                base_git_commit="abc123",
                patch_artifact_ref="artifact://patch",
                patch_digest="sha256:patch",
                test_plan_ref="artifact://test-plan",
                rollback_plan_ref="artifact://rollback",
                review_checklist_ref="artifact://review",
                apply_check_status="not_started",
                working_tree_mutation_allowed=False,
            )
        )
        await db.commit()

    async with _async_session_factory() as db:
        view = await render_acquisition_journal(db, tenant_id=tenant_id, user_id=user_id)

    markdown = view.rendered_markdown
    for section in (
        "## Open Gaps",
        "## Proposals Needing Approval",
        "## Activated Capabilities",
        "## Rejected or Dismissed",
        "## Runtime Planning Issues",
        "## Development Patch Proposals",
    ):
        assert section in markdown
    assert "Open weather gap" in markdown
    assert "Needs approval" in markdown
    assert "Activated weather" in markdown
    assert "Rejected proposal" in markdown
    assert "Existing weather tool was skipped" in markdown
    assert "Patch proposal" in markdown
    assert "Generated evidence, not authority" in markdown
    assert "cannot treat this journal as approval or activation" in markdown


async def test_journal_is_user_private(tenant_a_headers: dict[str, str], client) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    private_gap = await _gap(tenant_id, user_id, title="Private owner gap")
    await _recommendation(tenant_id, user_id, private_gap.id, title="Private recommendation")

    other_headers = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": f"tenant-{uuid.uuid4().hex}",
            "username": f"user-{uuid.uuid4().hex}",
            "password": "secret123",
        },
    )
    assert other_headers.status_code == 200, other_headers.text
    other_tenant_id, other_user_id = _identity({"Authorization": f"Bearer {other_headers.json()['access_token']}"})
    other_gap = await _gap(other_tenant_id, other_user_id, title="Other user gap")
    await _recommendation(other_tenant_id, other_user_id, other_gap.id, title="Other recommendation")

    async with _async_session_factory() as db:
        owner_view = await render_acquisition_journal(db, tenant_id=tenant_id, user_id=user_id)
        other_view = await render_acquisition_journal(db, tenant_id=other_tenant_id, user_id=other_user_id)

    assert "Private owner gap" in owner_view.rendered_markdown
    assert "Other user gap" not in owner_view.rendered_markdown
    assert "Other user gap" in other_view.rendered_markdown
    assert "Private owner gap" not in other_view.rendered_markdown


async def test_journal_write_is_idempotent(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id, title="Idempotent gap")
    await _recommendation(tenant_id, user_id, gap.id, title="Idempotent recommendation")

    async with _async_session_factory() as db:
        first = await write_acquisition_journal_snapshot(db, tenant_id=tenant_id, user_id=user_id)
        await db.commit()
    async with _async_session_factory() as db:
        second = await write_acquisition_journal_snapshot(db, tenant_id=tenant_id, user_id=user_id)
        await db.commit()
    async with _async_session_factory() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(AcquisitionJournalEntry)
                .where(
                    AcquisitionJournalEntry.tenant_id == tenant_id,
                    AcquisitionJournalEntry.user_id == user_id,
                    AcquisitionJournalEntry.entry_kind == "acquisition_journal_snapshot",
                )
            )
        ).scalar_one()

    assert first.entries[0].id == second.entries[0].id
    assert first.rendered_markdown == second.rendered_markdown
    assert count == 1


async def test_journal_snapshot_write_is_concurrent_idempotent(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id, title="Concurrent snapshot gap")
    await _recommendation(tenant_id, user_id, gap.id, title="Concurrent snapshot recommendation")

    async def write_once() -> uuid.UUID:
        async with _async_session_factory() as db:
            view = await write_acquisition_journal_snapshot(db, tenant_id=tenant_id, user_id=user_id)
            await db.commit()
            return view.entries[0].id

    first_id, second_id = await asyncio.gather(write_once(), write_once())

    async with _async_session_factory() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(AcquisitionJournalEntry)
                .where(
                    AcquisitionJournalEntry.tenant_id == tenant_id,
                    AcquisitionJournalEntry.user_id == user_id,
                    AcquisitionJournalEntry.entry_kind == "acquisition_journal_snapshot",
                )
            )
        ).scalar_one()

    assert first_id == second_id
    assert count == 1


async def test_journal_snapshot_write_bounds_large_evidence(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    huge_value = "x" * 7000
    for index in range(25):
        gap = await _gap(
            tenant_id,
            user_id,
            title=f"Large evidence gap {index}",
            evidence={"huge": huge_value, "nested": {"also_huge": huge_value}},
        )
        recommendation = await _recommendation(tenant_id, user_id, gap.id, title=f"Large evidence recommendation {index}")
        await _proposal(
            tenant_id,
            user_id,
            gap.id,
            recommendation.id,
            title=f"Large evidence proposal {index}",
            status="verified",
            evidence={"huge": huge_value},
        )

    async with _async_session_factory() as db:
        view = await write_acquisition_journal_snapshot(db, tenant_id=tenant_id, user_id=user_id, section_limit=25)
        await db.commit()

    assert len(view.rendered_markdown.encode("utf-8")) <= 32768
    assert huge_value not in view.rendered_markdown
    assert '"truncated":true' in view.rendered_markdown
    assert '"sha256":' in view.rendered_markdown
    assert "## Snapshot Truncated" in view.rendered_markdown


async def test_journal_redacts_credentials_paths_and_trace_sensitive_values(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    raw_secret = "sk-live-secret-token"
    raw_windows_path = r"E:\Users\alice\secrets\tool.env"
    raw_posix_path = "/home/alice/.config/tool/token.json"
    trace_id = "trace-secret-123"
    gap = await _gap(
        tenant_id,
        user_id,
        title="Sensitive gap",
        dedupe_key=f"{raw_secret}-{raw_windows_path}",
        source_run_id=f"run-{raw_secret}-{raw_posix_path}",
        evidence={
            "api_key": raw_secret,
            "config_path": raw_windows_path,
            "trace_payload": {"trace_id": trace_id, "stdout": raw_posix_path},
        },
    )
    recommendation = await _recommendation(tenant_id, user_id, gap.id, title="Sensitive recommendation")
    await _proposal(
        tenant_id,
        user_id,
        gap.id,
        recommendation.id,
        title=f"Sensitive proposal {raw_secret}",
        status="verified",
        evidence={
            "authorization": f"Bearer {raw_secret}",
            "artifact": raw_windows_path,
            "trace": {"value": trace_id},
        },
    )
    activated = await _proposal(
        tenant_id,
        user_id,
        gap.id,
        recommendation.id,
        title="Sensitive activated proposal",
        status="activated",
    )
    await _activation_target(
        tenant_id,
        user_id,
        activated.id,
        name=f"Sensitive target {raw_secret}",
    )
    await _planning_issue(
        tenant_id,
        user_id,
        missed_signal=f"Trace value {trace_id} in {raw_posix_path}",
        evidence={"cookie": "sessionid=secret", "host_path": raw_windows_path},
    )

    async with _async_session_factory() as db:
        view = await render_acquisition_journal(db, tenant_id=tenant_id, user_id=user_id)

    markdown = view.rendered_markdown
    assert raw_secret not in markdown
    assert raw_windows_path not in markdown
    assert raw_posix_path not in markdown
    assert trace_id not in markdown
    assert "[REDACTED_CREDENTIAL]" in markdown
    assert "[REDACTED_PATH]" in markdown
    assert "[REDACTED_TRACE]" in markdown


async def test_journal_uses_section_limits_totals_and_paginated_links_for_large_record_sets(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    for index in range(DEFAULT_SECTION_LIMIT + 2):
        await _gap(tenant_id, user_id, title=f"Bulk gap {index}")

    async with _async_session_factory() as db:
        view = await render_acquisition_journal(db, tenant_id=tenant_id, user_id=user_id)

    markdown = view.rendered_markdown
    assert "Total: 7" in markdown
    assert f"Showing: {DEFAULT_SECTION_LIMIT}" in markdown
    assert "More: 2" in markdown
    assert f"/api/v1/acquisition/gaps?limit={DEFAULT_SECTION_LIMIT}&offset=0" in markdown
    assert f"/api/v1/acquisition/gaps?limit={DEFAULT_SECTION_LIMIT}&offset={DEFAULT_SECTION_LIMIT}" in markdown
    assert f"/api/v1/acquisition/runtime-planning-issues?limit={DEFAULT_SECTION_LIMIT}&offset=0" in markdown
    assert "Bulk gap 0" in markdown
    assert "Bulk gap 4" in markdown
    assert "Bulk gap 5" not in markdown
