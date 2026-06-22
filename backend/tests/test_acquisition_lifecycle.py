"""Acquisition lifecycle owner tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select

from app.api.deps import _async_session_factory
from app.core.acquisition import lifecycle, repository
from app.core.acquisition.activation import (
    TargetActivationResult,
    _ensure_activation_targets,
    approve_activation,
    run_activation_saga,
)
from app.core.acquisition.rollback import RollbackHookResult, rollback_activation
from app.core.acquisition.verification import verify_proposal
from app.models.acquisition import (
    APIToolConfiguration,
    AcquisitionIdempotencyRecord,
    AcquisitionJournalEntry,
    AcquisitionProposal,
    ActivationTarget,
    CapabilityGap,
    CapabilityRecommendation,
    ExplorationRun,
    StandingPermission,
)
from app.models.audit_log import AuditLog
from app.models.conversation import Conversation
from app.models.tenant import Tenant
from app.models.tool_confirmation import ToolConfirmation
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


async def _gap(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    dedupe_key: str = "Tool: Weather API",
    source_kind: str = "agent_runtime",
    source_run_id: str | None = None,
    idempotency_key: str | None = None,
    evidence: dict | None = None,
    source_evidence: list[dict] | None = None,
) -> CapabilityGap:
    async with _async_session_factory() as db:
        gap = await lifecycle.record_gap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_kind=source_kind,
            source_run_id=source_run_id or f"run-{uuid.uuid4().hex}",
            dedupe_key=dedupe_key,
            title="Missing weather API",
            description="The task needs a reusable weather API capability.",
            gap_type="missing_api",
            severity="medium",
            evidence=evidence or {"target": "weather"},
            source_evidence=source_evidence or [{"kind": "tool_error", "message": "TOOL_NOT_FOUND"}],
            idempotency_key=idempotency_key or f"gap-{uuid.uuid4().hex}",
        )
        await db.commit()
        return gap


async def _recommendation(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
    evidence: dict | None = None,
) -> CapabilityRecommendation:
    async with _async_session_factory() as db:
        recommendation = await lifecycle.create_recommendation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap_id,
            recommendation_type="api_recommendation",
            title="Configure weather API",
            summary="Use a bounded weather API tool.",
            reason="The gap needs stable public weather data.",
            evidence=evidence or {"source": "test"},
            risk_level="safe",
            expected_value={"reusable": True},
            required_permissions={"network": "public_web"},
            candidate_targets=[{"target_type": "api_tool", "name": "weather"}],
            idempotency_key=idempotency_key,
        )
        await db.commit()
        return recommendation


def _permission_bundle(*, duration: str = "one_run") -> dict:
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
        "duration": duration,
        "revocation_plan": {"disable": True},
        "audit_events": [],
    }


def _primary_target(*, name: str = "weather", permission_bundle: dict | None = None) -> dict:
    return {
        "target_type": "api_tool",
        "target_name": name,
        "target_owner": "core.api_tools",
        "target_payload": {"base_url": "https://api.weather.example"},
        "permission_bundle": permission_bundle or _permission_bundle(),
        "verification_plan": {"kind": "contract"},
        "rollback_plan": {"disable": True},
        "activation_status": "draft",
        "activation_result": {},
    }


async def _proposal(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
    evidence: dict | None = None,
    proposal_kind: str = "runtime_activation",
    primary_target: dict | None = None,
    secondary_targets: list[dict] | None = None,
    permission_bundle: dict | None = None,
) -> AcquisitionProposal:
    async with _async_session_factory() as db:
        proposal = await lifecycle.create_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_kind=proposal_kind,
            gap_id=gap_id,
            recommendation_id=recommendation_id,
            title="Activate weather API",
            reason="Stable weather lookup should be reusable.",
            evidence=evidence or {"source": "test"},
            risk_level="safe",
            permission_bundle=permission_bundle or _permission_bundle(),
            primary_target=(primary_target or _primary_target()) if proposal_kind == "runtime_activation" else None,
            secondary_targets=secondary_targets,
            development_handoff={"handoff": "development"} if proposal_kind == "development_patch_proposal" else None,
            verification_plan={"kind": "contract"},
            rollback_plan={"disable": True},
            user_visible_effect="Weather lookups can use a configured API tool.",
            idempotency_key=idempotency_key,
        )
        await db.commit()
        return proposal


async def _same_tenant_user_headers(client: AsyncClient, tenant_id: uuid.UUID) -> dict[str, str]:
    async with _async_session_factory() as db:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    suffix = uuid.uuid4().hex
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": tenant.name,
            "username": f"user-{suffix}",
            "password": "secret123",
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _confirmation(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    status: str = "approved",
) -> ToolConfirmation:
    async with _async_session_factory() as db:
        conversation = Conversation(tenant_id=tenant_id, user_id=user_id, title="approval owner")
        db.add(conversation)
        await db.flush()
        confirmation = ToolConfirmation(
            conversation_id=conversation.id,
            tool_call_id=f"approval-{uuid.uuid4().hex}",
            tool_name="acquisition.explore",
            args={"purpose": "acquisition_exploration"},
            status=status,
        )
        db.add(confirmation)
        await db.commit()
        return confirmation


async def _approved_runtime_proposal(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    primary_target: dict | None = None,
    secondary_targets: list[dict] | None = None,
    permission_bundle: dict | None = None,
    dedupe_key: str | None = None,
) -> tuple[uuid.UUID, str]:
    gap = await _gap(tenant_id, user_id, dedupe_key=dedupe_key or f"approved-{uuid.uuid4().hex}")
    recommendation = await _recommendation(tenant_id, user_id, gap.id)
    proposal = await _proposal(
        tenant_id,
        user_id,
        gap.id,
        recommendation.id,
        primary_target=primary_target,
        secondary_targets=secondary_targets,
        permission_bundle=permission_bundle,
    )
    async with _async_session_factory() as db:
        verification = await verify_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            verification_kind="contract",
            input_fixture={"city": "London"},
            expected_result={"ok": True},
            actual_result={"ok": True},
            artifact_refs=[{"artifact_id": f"verify-{proposal.id}", "digest": "sha256:evidence"}],
            idempotency_key=f"verify-{proposal.id}",
        )
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            idempotency_key=f"approve-{proposal.id}",
        )
        await db.commit()
        return proposal.id, verification.verified_snapshot_hash


class FakeActivationHooks:
    def __init__(self, *, fail_roles: set[str] | None = None) -> None:
        self.fail_roles = fail_roles or set()
        self.calls: list[str] = []

    async def activate_target(
        self,
        db,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        approved_hash: str,
        idempotency_key: str | None,
    ) -> TargetActivationResult:
        role = str((target.activation_result or {}).get("role"))
        self.calls.append(f"{role}:{target.target_name}")
        if role in self.fail_roles:
            return TargetActivationResult(
                success=False,
                error_code=f"{role.upper()}_FAILED",
                error_message=f"{role} activation failed",
                evidence={"fake": True, "role": role},
            )
        return TargetActivationResult(
            success=True,
            activated_resource_ref={
                "kind": target.target_type,
                "name": target.target_name,
                "manifest_ref": f"{target.target_type}:{target.target_name}",
            },
            runtime_session_ref={"session_id": f"session-{target.target_name}"},
            evidence={"fake": True, "role": role, "runtime_side_effects": False},
        )


class FakeRollbackHooks:
    def __init__(self, *, fail_compensation: bool = False) -> None:
        self.fail_compensation = fail_compensation
        self.terminated: list[str] = []
        self.compensated: list[str] = []

    async def terminate_session(
        self,
        db,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        resource_ref: dict,
        idempotency_key: str | None,
    ) -> RollbackHookResult:
        self.terminated.append(target.target_name)
        return RollbackHookResult(success=True, evidence={"terminated_session": resource_ref.get("runtime_session_ref")})

    async def compensate_target(
        self,
        db,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        resource_ref: dict,
        idempotency_key: str | None,
    ) -> RollbackHookResult:
        self.compensated.append(target.target_name)
        if self.fail_compensation:
            return RollbackHookResult(
                success=False,
                evidence={"compensated": False},
                error_code="COMPENSATION_FAILED",
                error_message="manual cleanup required",
            )
        return RollbackHookResult(success=True, evidence={"compensated": True})


async def test_gap_lifecycle_is_idempotent(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)

    first = await _gap(
        tenant_id,
        user_id,
        dedupe_key=" HTTPS://WWW.Example.com/weather/ ",
        idempotency_key="gap-idempotent",
    )
    second = await _gap(
        tenant_id,
        user_id,
        dedupe_key="https://example.com/weather",
        idempotency_key="gap-idempotent",
    )

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(
                select(CapabilityGap).where(CapabilityGap.id == first.id)
            )
        ).scalar_one()
        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id == user_id,
                    AuditLog.action == "acquisition.gap.created",
                    AuditLog.resource_id == str(first.id),
                )
            )
        ).scalar_one()

    assert first.id == second.id
    assert persisted.dedupe_key == "example.com/weather"
    assert persisted.occurrence_count == 1
    assert audit_count == 1


async def test_gap_dedupe_ignores_runtime_source_kind_by_default(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)

    first = await _gap(
        tenant_id,
        user_id,
        dedupe_key="Weather API",
        source_kind="agent_runtime",
        idempotency_key="gap-source-owner-1",
    )
    second = await _gap(
        tenant_id,
        user_id,
        dedupe_key="weather api",
        source_kind="ui_runtime",
        idempotency_key="gap-source-owner-2",
    )

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(CapabilityGap).where(CapabilityGap.id == first.id))
        ).scalar_one()

    assert first.id == second.id
    assert persisted.dedupe_key == "weather-api"
    assert persisted.source_kind == "ui_runtime"
    assert persisted.occurrence_count == 2


async def test_gap_evidence_lifecycle_idempotency_keys_survive_caller_lifecycle_merge(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)

    first = await _gap(
        tenant_id,
        user_id,
        dedupe_key="lifecycle weather api",
        idempotency_key="gap-lifecycle-1",
        evidence={"lifecycle": {"caller": "first"}, "target": "weather"},
    )
    await _gap(
        tenant_id,
        user_id,
        dedupe_key="lifecycle weather api",
        idempotency_key="gap-lifecycle-2",
        evidence={"lifecycle": {"caller": "second"}, "target": "weather-v2"},
    )

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(CapabilityGap).where(CapabilityGap.id == first.id))
        ).scalar_one()

    assert persisted.evidence["lifecycle"]["caller"] == "second"
    assert persisted.evidence["lifecycle"]["idempotency_keys"] == [
        "gap-lifecycle-1",
        "gap-lifecycle-2",
    ]


async def test_gap_idempotency_record_survives_bounded_json_history_rolloff(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    first = await _gap(
        tenant_id,
        user_id,
        dedupe_key="old idempotency durable authority",
        idempotency_key="old-gap-key",
    )

    for index in range(25):
        await _gap(
            tenant_id,
            user_id,
            dedupe_key="old idempotency durable authority",
            idempotency_key=f"new-gap-key-{index}",
        )

    replay = await _gap(
        tenant_id,
        user_id,
        dedupe_key="old idempotency durable authority",
        idempotency_key="old-gap-key",
        evidence={"source": "must-not-increment"},
    )

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(CapabilityGap).where(CapabilityGap.id == first.id))
        ).scalar_one()
        idempotency_count = (
            await db.execute(
                select(func.count())
                .select_from(AcquisitionIdempotencyRecord)
                .where(
                    AcquisitionIdempotencyRecord.tenant_id == tenant_id,
                    AcquisitionIdempotencyRecord.user_id == user_id,
                    AcquisitionIdempotencyRecord.scope == "gap:create",
                    AcquisitionIdempotencyRecord.idempotency_key == "old-gap-key",
                    AcquisitionIdempotencyRecord.resource_id == first.id,
                )
            )
        ).scalar_one()

    assert replay.id == first.id
    assert persisted.occurrence_count == 26
    assert "old-gap-key" not in persisted.evidence["lifecycle"]["idempotency_keys"]
    assert idempotency_count == 1


async def test_duplicate_gap_occurrence_retains_prior_and_new_source_evidence(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    first = await _gap(
        tenant_id,
        user_id,
        dedupe_key="source evidence retention",
        idempotency_key="source-evidence-1",
        source_evidence=[{"kind": "first", "message": "original evidence"}],
    )
    await _gap(
        tenant_id,
        user_id,
        dedupe_key="source evidence retention",
        idempotency_key="source-evidence-2",
        source_evidence=[{"kind": "second", "message": "new evidence"}],
    )

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(CapabilityGap).where(CapabilityGap.id == first.id))
        ).scalar_one()

    assert {"kind": "first", "message": "original evidence"} in persisted.source_evidence
    assert {"kind": "second", "message": "new evidence"} in persisted.source_evidence


async def test_lifecycle_audit_does_not_commit_caller_transaction(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)

    async with _async_session_factory() as db:
        gap = await lifecycle.record_gap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_kind="agent_runtime",
            source_run_id="rollback-run",
            dedupe_key="rollback gap",
            title="Rollback gap",
            description="This gap should roll back with its audit row.",
            gap_type="missing_api",
            severity="medium",
            evidence={"target": "rollback"},
            source_evidence=[{"kind": "rollback"}],
            idempotency_key="rollback-gap-key",
        )
        gap_id = gap.id
        await db.rollback()

    async with _async_session_factory() as db:
        gap_count = (
            await db.execute(
                select(func.count()).select_from(CapabilityGap).where(CapabilityGap.id == gap_id)
            )
        ).scalar_one()
        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_id == str(gap_id))
            )
        ).scalar_one()
        idempotency_count = (
            await db.execute(
                select(func.count())
                .select_from(AcquisitionIdempotencyRecord)
                .where(AcquisitionIdempotencyRecord.resource_id == gap_id)
            )
        ).scalar_one()

    assert gap_count == 0
    assert audit_count == 0
    assert idempotency_count == 0


async def test_gap_dedupe_concurrent_failures_create_one_gap_and_increment_occurrence_count(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)

    async def record_once(idempotency_key: str) -> uuid.UUID:
        gap = await _gap(
            tenant_id,
            user_id,
            dedupe_key="weather api",
            idempotency_key=idempotency_key,
        )
        return gap.id

    first_id, second_id = await asyncio.gather(
        record_once("gap-concurrent-1"),
        record_once("gap-concurrent-2"),
    )

    async with _async_session_factory() as db:
        rows = list(
            (
                await db.execute(
                    select(CapabilityGap).where(
                        CapabilityGap.tenant_id == tenant_id,
                        CapabilityGap.user_id == user_id,
                        CapabilityGap.gap_type == "missing_api",
                    )
                )
            ).scalars()
        )

    assert first_id == second_id
    assert len(rows) == 1
    assert rows[0].occurrence_count == 2


async def test_missing_user_input_greeting_transient_retryable_failure_and_planner_missed_existing_tool_do_not_create_gap(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)

    for failure_class in [
        "missing_user_input",
        "greeting",
        "transient_retryable_failure",
        "planner_missed_existing_tool",
    ]:
        async with _async_session_factory() as db:
            gap = await lifecycle.record_failure(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                failure_class=failure_class,
                source_kind="agent_runtime",
                source_run_id=f"run-{failure_class}",
                dedupe_key=failure_class,
                title=failure_class,
                description="Negative classification should not create a gap.",
                has_existing_tool=failure_class == "planner_missed_existing_tool",
                idempotency_key=f"negative-{failure_class}",
            )
            assert gap is None

    async with _async_session_factory() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(CapabilityGap)
                .where(CapabilityGap.tenant_id == tenant_id, CapabilityGap.user_id == user_id)
            )
        ).scalar_one()

    assert count == 0


async def test_safe_exploration_auto_runs_only_inside_public_read_only_run_workspace_bounds(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id)
    bounds = {
        "data_scope": "public_web",
        "network_scope": "public_web",
        "write_scope": "run_workspace",
        "read_only": True,
        "cleanup_supported": True,
    }

    async with _async_session_factory() as db:
        exploration = await lifecycle.start_exploration(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap.id,
            source_run_id=f"explore-{uuid.uuid4().hex}",
            strategy="code_as_action",
            risk_level="safe",
            bounds=bounds,
            idempotency_key="safe-exploration",
        )
        await db.commit()

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(
                select(ExplorationRun).where(ExplorationRun.id == exploration.id)
            )
        ).scalar_one()
        persisted_gap = (
            await db.execute(select(CapabilityGap).where(CapabilityGap.id == gap.id))
        ).scalar_one()

    assert persisted.status == "running"
    assert persisted.started_at is not None
    assert persisted_gap.status == "exploring"
    assert lifecycle.evaluate_exploration_bounds(bounds).can_auto_run is True


async def test_start_exploration_idempotency_key_ignores_changed_source_run_id(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id, dedupe_key="exploration retry source run")
    bounds = {
        "data_scope": "public_web",
        "network_scope": "public_web",
        "write_scope": "run_workspace",
        "read_only": True,
        "cleanup_supported": True,
    }

    async with _async_session_factory() as db:
        first = await lifecycle.start_exploration(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap.id,
            source_run_id="exploration-retry-run-1",
            strategy="code_as_action",
            risk_level="safe",
            bounds=bounds,
            idempotency_key="exploration-retry-idempotent",
        )
        await db.commit()

    async with _async_session_factory() as db:
        second = await lifecycle.start_exploration(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap.id,
            source_run_id="exploration-retry-run-2",
            strategy="code_as_action",
            risk_level="safe",
            bounds=bounds,
            idempotency_key="exploration-retry-idempotent",
        )
        await db.commit()

    async with _async_session_factory() as db:
        exploration_count = (
            await db.execute(
                select(func.count())
                .select_from(ExplorationRun)
                .where(
                    ExplorationRun.tenant_id == tenant_id,
                    ExplorationRun.user_id == user_id,
                    ExplorationRun.gap_id == gap.id,
                )
            )
        ).scalar_one()
        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id == user_id,
                    AuditLog.action == "acquisition.exploration.started",
                    AuditLog.resource_id == str(first.id),
                )
            )
        ).scalar_one()

    assert first.id == second.id
    assert second.source_run_id == "exploration-retry-run-1"
    assert exploration_count == 1
    assert audit_count == 1


async def test_start_exploration_same_key_concurrent_creates_one_run(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id, dedupe_key="concurrent exploration create")
    bounds = {
        "data_scope": "public_web",
        "network_scope": "public_web",
        "write_scope": "run_workspace",
        "read_only": True,
        "cleanup_supported": True,
    }

    async def create_once(source_run_id: str) -> uuid.UUID:
        async with _async_session_factory() as db:
            exploration = await lifecycle.start_exploration(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                gap_id=gap.id,
                source_run_id=source_run_id,
                strategy="code_as_action",
                risk_level="safe",
                bounds=bounds,
                idempotency_key="exploration-concurrent-idempotent",
            )
            await db.commit()
            return exploration.id

    first_id, second_id = await asyncio.gather(
        create_once("exploration-concurrent-run-1"),
        create_once("exploration-concurrent-run-2"),
    )

    async with _async_session_factory() as db:
        exploration_count = (
            await db.execute(
                select(func.count())
                .select_from(ExplorationRun)
                .where(
                    ExplorationRun.tenant_id == tenant_id,
                    ExplorationRun.user_id == user_id,
                    ExplorationRun.gap_id == gap.id,
                )
            )
        ).scalar_one()
        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id == user_id,
                    AuditLog.action == "acquisition.exploration.started",
                    AuditLog.resource_id == str(first_id),
                )
            )
        ).scalar_one()

    assert first_id == second_id
    assert exploration_count == 1
    assert audit_count == 1


async def test_invalid_status_transitions_raise_api_errors(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    detected_gap = await _gap(
        tenant_id,
        user_id,
        dedupe_key="invalid transition detected gap",
        idempotency_key="invalid-gap-detected",
    )
    gap = await _gap(tenant_id, user_id)
    recommendation = await _recommendation(tenant_id, user_id, gap.id)
    proposal = await _proposal(tenant_id, user_id, gap.id, recommendation.id)
    queued_gap = await _gap(
        tenant_id,
        user_id,
        dedupe_key="queued exploration gap",
        idempotency_key="queued-gap",
    )

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as gap_exc:
            await repository.transition_gap(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                gap_id=detected_gap.id,
                status="proposal_drafted",
            )
        assert gap_exc.value.status_code == 409

    async with _async_session_factory() as db:
        exploration, _ = await repository.create_exploration(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=queued_gap.id,
            source_run_id="queued-invalid-transition",
            risk_level="safe",
            strategy="code_as_action",
            idempotency_key="queued-invalid-transition",
        )
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exploration_exc:
            await repository.transition_exploration(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                exploration_id=exploration.id,
                status="succeeded",
            )
        assert exploration_exc.value.status_code == 409

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as proposal_exc:
            await repository.transition_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                status="activated",
                actor_user_id=user_id,
            )
        assert proposal_exc.value.status_code == 409


async def test_proposal_drafted_cannot_skip_verification_request_or_verifying(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id, dedupe_key="proposal mandatory verification")
    recommendation = await _recommendation(tenant_id, user_id, gap.id)
    proposal = await _proposal(tenant_id, user_id, gap.id, recommendation.id)

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as verifying_exc:
            await repository.transition_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                status="verifying",
                actor_user_id=user_id,
            )
        assert verifying_exc.value.status_code == 409

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as verified_exc:
            await repository.transition_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                status="verified",
                actor_user_id=user_id,
            )
        assert verified_exc.value.status_code == 409


async def test_development_patch_proposal_rejects_runtime_only_states_with_lifecycle_error(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id, dedupe_key="patch proposal lifecycle")
    recommendation = await _recommendation(tenant_id, user_id, gap.id)
    proposal = await _proposal(
        tenant_id,
        user_id,
        gap.id,
        recommendation.id,
        proposal_kind="development_patch_proposal",
    )

    for runtime_only_status in [
        "verification_requested",
        "activation_requested",
        "activation_approved",
        "activating",
        "activated",
        "rolled_back",
    ]:
        async with _async_session_factory() as db:
            with pytest.raises(HTTPException) as exc:
                await repository.transition_proposal(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    proposal_id=proposal.id,
                    status=runtime_only_status,
                    actor_user_id=user_id,
                    idempotency_key=f"patch-runtime-only-{runtime_only_status}",
                )
            assert exc.value.status_code == 409
            assert exc.value.detail["error"]["code"] == "INVALID_PROPOSAL_STATUS_TRANSITION"

    async with _async_session_factory() as db:
        patch, changed = await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            status="verifying",
            actor_user_id=user_id,
            idempotency_key="patch-valid-verifying",
        )
        await db.commit()

    assert changed is True
    assert patch.status == "verifying"


async def test_complete_exploration_is_idempotent(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id)
    bounds = {
        "data_scope": "public_web",
        "network_scope": "public_web",
        "write_scope": "run_workspace",
        "read_only": True,
        "cleanup_supported": True,
    }

    async with _async_session_factory() as db:
        exploration = await lifecycle.start_exploration(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap.id,
            source_run_id="complete-idempotent-run",
            strategy="code_as_action",
            risk_level="safe",
            bounds=bounds,
            idempotency_key="complete-idempotent-start",
        )
        await db.commit()

    async with _async_session_factory() as db:
        first = await lifecycle.complete_exploration(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            exploration_id=exploration.id,
            status="succeeded",
            result_summary="first completion wins",
            idempotency_key="complete-idempotent",
        )
        await db.commit()

    async with _async_session_factory() as db:
        second = await lifecycle.complete_exploration(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            exploration_id=exploration.id,
            status="succeeded",
            result_summary="first completion wins",
            idempotency_key="complete-idempotent",
        )
        await db.commit()

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(ExplorationRun).where(ExplorationRun.id == exploration.id))
        ).scalar_one()
        persisted_gap = (
            await db.execute(select(CapabilityGap).where(CapabilityGap.id == gap.id))
        ).scalar_one()
        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id == user_id,
                    AuditLog.action == "acquisition.exploration.succeeded",
                    AuditLog.resource_id == str(exploration.id),
                )
            )
        ).scalar_one()

    assert first.id == second.id
    assert persisted.status == "succeeded"
    assert persisted.result_summary == "first completion wins"
    assert persisted_gap.status == "explored_success"
    assert audit_count == 1


async def test_recommendation_and_proposal_creation_are_idempotent(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id)

    first_recommendation = await _recommendation(
        tenant_id,
        user_id,
        gap.id,
        idempotency_key="recommendation-idempotent",
    )
    second_recommendation = await _recommendation(
        tenant_id,
        user_id,
        gap.id,
        idempotency_key="recommendation-idempotent",
    )
    first_proposal = await _proposal(
        tenant_id,
        user_id,
        gap.id,
        first_recommendation.id,
        idempotency_key="proposal-idempotent",
    )
    second_proposal = await _proposal(
        tenant_id,
        user_id,
        gap.id,
        first_recommendation.id,
        idempotency_key="proposal-idempotent",
    )

    async with _async_session_factory() as db:
        recommendation_count = (
            await db.execute(
                select(func.count())
                .select_from(CapabilityRecommendation)
                .where(
                    CapabilityRecommendation.tenant_id == tenant_id,
                    CapabilityRecommendation.user_id == user_id,
                    CapabilityRecommendation.gap_id == gap.id,
                )
            )
        ).scalar_one()
        proposal_count = (
            await db.execute(
                select(func.count())
                .select_from(AcquisitionProposal)
                .where(
                    AcquisitionProposal.tenant_id == tenant_id,
                    AcquisitionProposal.user_id == user_id,
                    AcquisitionProposal.gap_id == gap.id,
                )
            )
        ).scalar_one()
        recommendation_audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id == user_id,
                    AuditLog.action == "acquisition.recommendation.created",
                    AuditLog.resource_id == str(first_recommendation.id),
                )
            )
        ).scalar_one()
        proposal_audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id == user_id,
                    AuditLog.action == "acquisition.proposal.created",
                    AuditLog.resource_id == str(first_proposal.id),
                )
            )
        ).scalar_one()

    assert first_recommendation.id == second_recommendation.id
    assert first_proposal.id == second_proposal.id
    assert recommendation_count == 1
    assert proposal_count == 1
    assert recommendation_audit_count == 1
    assert proposal_audit_count == 1


async def test_recommendation_same_key_concurrent_creates_one_row(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id, dedupe_key="concurrent recommendation create")

    async def create_once() -> uuid.UUID:
        async with _async_session_factory() as db:
            recommendation = await lifecycle.create_recommendation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                gap_id=gap.id,
                recommendation_type="api_recommendation",
                title="Configure weather API",
                summary="Use a bounded weather API tool.",
                reason="The gap needs stable public weather data.",
                evidence={"source": "concurrent"},
                risk_level="safe",
                expected_value={"reusable": True},
                required_permissions={"network": "public_web"},
                candidate_targets=[{"target_type": "api_tool", "name": "weather"}],
                idempotency_key="recommendation-concurrent-idempotent",
            )
            await db.commit()
            return recommendation.id

    first_id, second_id = await asyncio.gather(create_once(), create_once())

    async with _async_session_factory() as db:
        recommendation_count = (
            await db.execute(
                select(func.count())
                .select_from(CapabilityRecommendation)
                .where(
                    CapabilityRecommendation.tenant_id == tenant_id,
                    CapabilityRecommendation.user_id == user_id,
                    CapabilityRecommendation.gap_id == gap.id,
                )
            )
        ).scalar_one()
        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id == user_id,
                    AuditLog.action == "acquisition.recommendation.created",
                    AuditLog.resource_id == str(first_id),
                )
            )
        ).scalar_one()

    assert first_id == second_id
    assert recommendation_count == 1
    assert audit_count == 1


async def test_proposal_same_key_concurrent_creates_one_row(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id, dedupe_key="concurrent proposal create")
    recommendation = await _recommendation(tenant_id, user_id, gap.id)

    async def create_once() -> uuid.UUID:
        async with _async_session_factory() as db:
            proposal = await lifecycle.create_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_kind="runtime_activation",
                gap_id=gap.id,
                recommendation_id=recommendation.id,
                title="Activate weather API",
                reason="Stable weather lookup should be reusable.",
                evidence={"source": "concurrent"},
                risk_level="safe",
                permission_bundle=_permission_bundle(),
                primary_target=_primary_target(),
                verification_plan={"kind": "contract"},
                rollback_plan={"disable": True},
                user_visible_effect="Weather lookups can use a configured API tool.",
                idempotency_key="proposal-concurrent-idempotent",
            )
            await db.commit()
            return proposal.id

    first_id, second_id = await asyncio.gather(create_once(), create_once())

    async with _async_session_factory() as db:
        proposal_count = (
            await db.execute(
                select(func.count())
                .select_from(AcquisitionProposal)
                .where(
                    AcquisitionProposal.tenant_id == tenant_id,
                    AcquisitionProposal.user_id == user_id,
                    AcquisitionProposal.gap_id == gap.id,
                )
            )
        ).scalar_one()
        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id == user_id,
                    AuditLog.action == "acquisition.proposal.created",
                    AuditLog.resource_id == str(first_id),
                )
            )
        ).scalar_one()

    assert first_id == second_id
    assert proposal_count == 1
    assert audit_count == 1


async def test_same_idempotency_key_with_different_payload_returns_conflict(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id, dedupe_key="recommendation payload conflict")
    await _recommendation(
        tenant_id,
        user_id,
        gap.id,
        idempotency_key="recommendation-payload-conflict",
        evidence={"source": "first"},
    )

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await lifecycle.create_recommendation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                gap_id=gap.id,
                recommendation_type="api_recommendation",
                title="Configure weather API differently",
                summary="Use a bounded weather API tool.",
                reason="The gap needs stable public weather data.",
                evidence={"source": "second"},
                risk_level="safe",
                expected_value={"reusable": True},
                required_permissions={"network": "public_web"},
                candidate_targets=[{"target_type": "api_tool", "name": "weather"}],
                idempotency_key="recommendation-payload-conflict",
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"


async def test_recommendation_rejects_wrong_gap_and_cross_scope_exploration_parent_refs(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    same_tenant_other_headers = await _same_tenant_user_headers(client, tenant_id)
    same_tenant_other_id, same_tenant_other_user_id = _identity(same_tenant_other_headers)
    tenant_b_id, tenant_b_user_id = _identity(tenant_b_headers)
    bounds = {
        "data_scope": "public_web",
        "network_scope": "public_web",
        "write_scope": "run_workspace",
        "read_only": True,
        "cleanup_supported": True,
    }
    target_gap = await _gap(tenant_id, user_id, dedupe_key="target recommendation parent")
    wrong_gap = await _gap(tenant_id, user_id, dedupe_key="wrong recommendation parent")
    same_tenant_other_gap = await _gap(
        same_tenant_other_id,
        same_tenant_other_user_id,
        dedupe_key="same tenant other user exploration parent",
    )
    tenant_b_gap = await _gap(tenant_b_id, tenant_b_user_id, dedupe_key="tenant b exploration parent")

    async with _async_session_factory() as db:
        wrong_gap_exploration = await lifecycle.start_exploration(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=wrong_gap.id,
            source_run_id="wrong-gap-exploration-parent",
            strategy="code_as_action",
            risk_level="safe",
            bounds=bounds,
            idempotency_key="wrong-gap-exploration-parent",
        )
        await db.commit()
    async with _async_session_factory() as db:
        same_tenant_other_exploration = await lifecycle.start_exploration(
            db,
            tenant_id=same_tenant_other_id,
            user_id=same_tenant_other_user_id,
            gap_id=same_tenant_other_gap.id,
            source_run_id="cross-user-exploration-parent",
            strategy="code_as_action",
            risk_level="safe",
            bounds=bounds,
            idempotency_key="cross-user-exploration-parent",
        )
        await db.commit()
    async with _async_session_factory() as db:
        tenant_b_exploration = await lifecycle.start_exploration(
            db,
            tenant_id=tenant_b_id,
            user_id=tenant_b_user_id,
            gap_id=tenant_b_gap.id,
            source_run_id="cross-tenant-exploration-parent",
            strategy="code_as_action",
            risk_level="safe",
            bounds=bounds,
            idempotency_key="cross-tenant-exploration-parent",
        )
        await db.commit()

    for exploration_id in [
        wrong_gap_exploration.id,
        same_tenant_other_exploration.id,
        tenant_b_exploration.id,
    ]:
        async with _async_session_factory() as db:
            with pytest.raises(HTTPException) as exc:
                await lifecycle.create_recommendation(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    gap_id=target_gap.id,
                    exploration_run_id=exploration_id,
                    recommendation_type="api_recommendation",
                    title="Invalid parent",
                    summary="Invalid parent must be rejected.",
                    reason="Scope mismatch.",
                    evidence={"source": "test"},
                    risk_level="safe",
                    idempotency_key=f"invalid-recommendation-parent-{exploration_id}",
                )
            assert exc.value.status_code == 409
            assert exc.value.detail["error"]["code"] == "EXPLORATION_PARENT_SCOPE_MISMATCH"


async def test_proposal_rejects_wrong_gap_and_cross_scope_recommendation_parent_refs(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    same_tenant_other_headers = await _same_tenant_user_headers(client, tenant_id)
    same_tenant_other_id, same_tenant_other_user_id = _identity(same_tenant_other_headers)
    tenant_b_id, tenant_b_user_id = _identity(tenant_b_headers)
    target_gap = await _gap(tenant_id, user_id, dedupe_key="target proposal parent")
    target_recommendation = await _recommendation(tenant_id, user_id, target_gap.id)
    wrong_gap = await _gap(tenant_id, user_id, dedupe_key="wrong proposal parent")
    wrong_gap_recommendation = await _recommendation(tenant_id, user_id, wrong_gap.id)
    same_tenant_other_gap = await _gap(
        same_tenant_other_id,
        same_tenant_other_user_id,
        dedupe_key="same tenant other user recommendation parent",
    )
    same_tenant_other_recommendation = await _recommendation(
        same_tenant_other_id,
        same_tenant_other_user_id,
        same_tenant_other_gap.id,
    )
    tenant_b_gap = await _gap(tenant_b_id, tenant_b_user_id, dedupe_key="tenant b recommendation parent")
    tenant_b_recommendation = await _recommendation(tenant_b_id, tenant_b_user_id, tenant_b_gap.id)

    for recommendation_id in [
        wrong_gap_recommendation.id,
        same_tenant_other_recommendation.id,
        tenant_b_recommendation.id,
    ]:
        async with _async_session_factory() as db:
            with pytest.raises(HTTPException) as exc:
                await lifecycle.create_proposal(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    proposal_kind="runtime_activation",
                    gap_id=target_gap.id,
                    recommendation_id=recommendation_id,
                    title="Invalid recommendation parent",
                    reason="Scope mismatch.",
                    evidence={"source": "test"},
                    risk_level="safe",
                    permission_bundle=_permission_bundle(),
                    primary_target=_primary_target(),
                    verification_plan={"kind": "contract"},
                    rollback_plan={"disable": True},
                    user_visible_effect="Invalid proposal should not persist.",
                    idempotency_key=f"invalid-proposal-parent-{recommendation_id}",
                )
            assert exc.value.status_code == 409
            assert exc.value.detail["error"]["code"] == "RECOMMENDATION_PARENT_SCOPE_MISMATCH"

    persisted = await _proposal(tenant_id, user_id, target_gap.id, target_recommendation.id)
    assert persisted.recommendation_id == target_recommendation.id


async def test_login_payment_private_network_external_write_dependency_install_credentials_and_non_idempotent_side_effects_require_exploration_approval(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id)
    unsafe_cases = [
        {"requires_login": True},
        {"uses_payment": True},
        {"private_network": True},
        {"external_write": True},
        {"dependency_install": True},
        {"uses_credentials": True},
        {"non_idempotent_side_effect": True},
    ]

    for unsafe in unsafe_cases:
        bounds = {
            "data_scope": "public_web",
            "network_scope": "public_web",
            "write_scope": "run_workspace",
            "read_only": True,
            "cleanup_supported": True,
            **unsafe,
        }
        decision = lifecycle.evaluate_exploration_bounds(bounds)
        assert decision.can_auto_run is False
        assert decision.requires_approval is True

        async with _async_session_factory() as db:
            with pytest.raises(HTTPException) as exc:
                await lifecycle.start_exploration(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    gap_id=gap.id,
                    source_run_id=f"unsafe-{uuid.uuid4().hex}",
                    strategy="code_as_action",
                    risk_level="risky",
                    bounds=bounds,
                    idempotency_key=f"unsafe-{uuid.uuid4().hex}",
                )
            assert exc.value.status_code == 409


async def test_unsafe_exploration_requires_owned_approved_confirmation(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    same_tenant_other_headers = await _same_tenant_user_headers(client, tenant_id)
    same_tenant_other_id, same_tenant_other_user_id = _identity(same_tenant_other_headers)
    tenant_b_id, tenant_b_user_id = _identity(tenant_b_headers)
    gap = await _gap(tenant_id, user_id, dedupe_key="unsafe approval owner")
    pending = await _confirmation(tenant_id, user_id, status="pending")
    cross_user = await _confirmation(same_tenant_other_id, same_tenant_other_user_id, status="approved")
    cross_tenant = await _confirmation(tenant_b_id, tenant_b_user_id, status="approved")
    approved = await _confirmation(tenant_id, user_id, status="approved")
    bounds = {
        "data_scope": "public_web",
        "network_scope": "public_web",
        "write_scope": "run_workspace",
        "read_only": True,
        "cleanup_supported": True,
        "external_write": True,
    }

    for approval_id in [uuid.uuid4(), pending.id, cross_user.id, cross_tenant.id]:
        async with _async_session_factory() as db:
            with pytest.raises(HTTPException) as exc:
                await lifecycle.start_exploration(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    gap_id=gap.id,
                    source_run_id=f"invalid-approval-{uuid.uuid4().hex}",
                    strategy="code_as_action",
                    risk_level="risky",
                    bounds=bounds,
                    approval_id=approval_id,
                    idempotency_key=f"invalid-approval-{approval_id}",
                )
            assert exc.value.status_code == 409
            assert exc.value.detail["error"]["code"] == "EXPLORATION_APPROVAL_INVALID"

    async with _async_session_factory() as db:
        exploration = await lifecycle.start_exploration(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap.id,
            source_run_id="valid-unsafe-approval",
            strategy="code_as_action",
            risk_level="risky",
            bounds=bounds,
            approval_id=approved.id,
            idempotency_key="valid-unsafe-approval",
        )
        await db.commit()

    assert exploration.status == "running"
    assert exploration.approval_id == approved.id


async def test_rejected_proposal_cannot_activate(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id)
    recommendation = await _recommendation(tenant_id, user_id, gap.id)
    proposal = await _proposal(tenant_id, user_id, gap.id, recommendation.id)

    async with _async_session_factory() as db:
        rejected = await lifecycle.reject_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            reason="Not useful enough",
            idempotency_key="reject-weather",
        )
        await db.commit()
        assert rejected.status == "activation_rejected"

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await lifecycle.activate_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                idempotency_key="activate-weather",
            )
        assert exc.value.status_code == 409
        assert lifecycle.is_activation_rejection(exc.value) is True

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(
                select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id)
            )
        ).scalar_one()

    assert persisted.status == "activation_rejected"


async def test_primary_activation_failure_blocks_activation(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    secondary = _primary_target(name="weather-worker")
    proposal_id, approved_hash = await _approved_runtime_proposal(
        tenant_id,
        user_id,
        secondary_targets=[secondary],
        dedupe_key="primary activation failure",
    )
    hooks = FakeActivationHooks(fail_roles={"primary"})

    async with _async_session_factory() as db:
        result = await run_activation_saga(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            idempotency_key="primary-failure-saga",
            hooks=hooks,
        )
        await db.commit()

    async with _async_session_factory() as db:
        targets = list(
            (
                await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))
            ).scalars()
        )
        activated_audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "acquisition.target.activated", AuditLog.resource_id == str(proposal_id))
            )
        ).scalar_one()

    assert result.status == "activation_failed"
    assert hooks.calls == ["primary:weather"]
    assert len(targets) == 2
    primary = next(target for target in targets if (target.activation_result or {}).get("role") == "primary")
    pending_secondary = next(target for target in targets if (target.activation_result or {}).get("role") == "secondary")
    assert primary.activation_status == "activation_failed"
    assert primary.activated_resource_ref is None
    assert pending_secondary.activation_status == "activation_pending"
    assert pending_secondary.activated_resource_ref is None
    assert activated_audit_count == 0


async def test_secondary_only_target_ids_require_primary_before_proposal_activated(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    secondary = _primary_target(name="weather-worker")
    proposal_id, approved_hash = await _approved_runtime_proposal(
        tenant_id,
        user_id,
        secondary_targets=[secondary],
        dedupe_key="secondary only target ids require primary",
    )

    async with _async_session_factory() as db:
        proposal = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal_id))
        ).scalar_one()
        targets = await _ensure_activation_targets(
            db,
            proposal=proposal,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        primary = next(target for target in targets if (target.activation_result or {}).get("role") == "primary")
        secondary_target = next(target for target in targets if (target.activation_result or {}).get("role") == "secondary")
        await db.commit()

    hooks = FakeActivationHooks()
    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await run_activation_saga(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal_id,
                approved_hash=approved_hash,
                target_ids=[secondary_target.id],
                idempotency_key="secondary-only-before-primary",
                hooks=hooks,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "PRIMARY_TARGET_REQUIRED_FOR_SECONDARY_ACTIVATION"
    assert hooks.calls == []

    async with _async_session_factory() as db:
        proposal_after_reject = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal_id))
        ).scalar_one()
        targets_after_reject = list(
            (
                await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))
            ).scalars()
        )

    assert proposal_after_reject.status == "activation_approved"
    assert {target.activation_status for target in targets_after_reject} == {"activation_pending"}

    async with _async_session_factory() as db:
        primary_only = await run_activation_saga(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            target_ids=[primary.id],
            idempotency_key="primary-only-stage",
            hooks=hooks,
        )
        await db.commit()

    assert primary_only.status == "activating"
    assert hooks.calls == ["primary:weather"]

    async with _async_session_factory() as db:
        activated = await run_activation_saga(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            target_ids=[secondary_target.id],
            idempotency_key="secondary-after-primary",
            hooks=hooks,
        )
        await db.commit()

    async with _async_session_factory() as db:
        targets = list(
            (
                await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))
            ).scalars()
        )

    assert activated.status == "activated"
    assert hooks.calls == ["primary:weather", "secondary:weather-worker"]
    assert {target.activation_status for target in targets} == {"active"}


async def test_secondary_activation_failure_records_partial_activation_without_auto_rolling_back_primary(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    secondary = _primary_target(name="weather-worker")
    proposal_id, approved_hash = await _approved_runtime_proposal(
        tenant_id,
        user_id,
        secondary_targets=[secondary],
        dedupe_key="secondary activation failure",
    )
    hooks = FakeActivationHooks(fail_roles={"secondary"})

    async with _async_session_factory() as db:
        result = await run_activation_saga(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            idempotency_key="secondary-failure-saga",
            hooks=hooks,
        )
        await db.commit()

    async with _async_session_factory() as db:
        targets = list(
            (
                await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))
            ).scalars()
        )
        primary = next(target for target in targets if (target.activation_result or {}).get("role") == "primary")
        failed_secondary = next(target for target in targets if (target.activation_result or {}).get("role") == "secondary")
        rollback_audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "acquisition.activation.rolled_back", AuditLog.resource_id == str(proposal_id))
            )
        ).scalar_one()

    assert result.status == "partial_activation"
    assert primary.activation_status == "active"
    assert primary.activated_resource_ref.get("hidden") is not True
    assert failed_secondary.activation_status == "activation_failed"
    assert failed_secondary.activated_resource_ref is None
    assert rollback_audit_count == 0


async def test_rollback_is_idempotent(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id, approved_hash = await _approved_runtime_proposal(
        tenant_id,
        user_id,
        dedupe_key="rollback idempotent",
    )
    async with _async_session_factory() as db:
        await run_activation_saga(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            idempotency_key="rollback-idempotent-activate",
            hooks=FakeActivationHooks(),
        )
        await db.commit()

    hooks = FakeRollbackHooks()
    async with _async_session_factory() as db:
        first = await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            idempotency_key="rollback-idempotent",
            hooks=hooks,
        )
        await db.commit()
    async with _async_session_factory() as db:
        second = await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            idempotency_key="rollback-idempotent",
            hooks=hooks,
        )
        await db.commit()

    async with _async_session_factory() as db:
        journal_count = (
            await db.execute(
                select(func.count())
                .select_from(AcquisitionJournalEntry)
                .where(AcquisitionJournalEntry.entry_kind == "activation_rollback", AcquisitionJournalEntry.subject_ref["proposal_id"].astext == str(proposal_id))
            )
        ).scalar_one()
        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "acquisition.activation.rolled_back", AuditLog.resource_id == str(proposal_id))
            )
        ).scalar_one()

    assert first.status == "rolled_back"
    assert first.changed is True
    assert second.changed is False
    assert hooks.terminated == ["weather"]
    assert hooks.compensated == ["weather"]
    assert journal_count == 1
    assert audit_count == 1


async def test_rollback_hides_tool_revokes_permission_terminates_session_updates_journal_and_writes_audit(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    permission = _permission_bundle(duration="until_revoked")
    proposal_id, approved_hash = await _approved_runtime_proposal(
        tenant_id,
        user_id,
        primary_target=_primary_target(permission_bundle=permission),
        permission_bundle=permission,
        dedupe_key="rollback full evidence",
    )
    async with _async_session_factory() as db:
        await run_activation_saga(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            idempotency_key="rollback-full-activate",
            hooks=FakeActivationHooks(),
        )
        target = (
            await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))
        ).scalar_one()
        db.add(
            APIToolConfiguration(
                tenant_id=tenant_id,
                user_id=user_id,
                activation_target_id=target.id,
                name="weather",
                base_url="https://api.weather.example",
                method="GET",
                path_template="/weather",
                headers_schema={},
                auth_scheme="none",
                input_schema={},
                output_schema={},
                allowed_hosts=["api.weather.example"],
                deny_private_networks=True,
                redirect_policy={"follow": False},
                allowed_content_types=["application/json"],
                max_request_bytes=1024,
                max_response_bytes=4096,
                idempotency_policy={"safe": True},
                response_redaction_policy={},
                rate_limit={"rpm": 60},
                timeout_s=5,
                retry_policy={"retries": 0},
                error_contract={},
                enabled=True,
                risk_level="safe",
            )
        )
        await db.commit()

    hooks = FakeRollbackHooks()
    async with _async_session_factory() as db:
        result = await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            reason="User requested rollback",
            idempotency_key="rollback-full",
            hooks=hooks,
        )
        await db.commit()

    async with _async_session_factory() as db:
        proposal = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal_id))
        ).scalar_one()
        target = (
            await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))
        ).scalar_one()
        permission_row = (
            await db.execute(select(StandingPermission).where(StandingPermission.proposal_id == proposal_id))
        ).scalar_one()
        api_tool = (
            await db.execute(select(APIToolConfiguration).where(APIToolConfiguration.activation_target_id == target.id))
        ).scalar_one()
        journal_count = (
            await db.execute(
                select(func.count())
                .select_from(AcquisitionJournalEntry)
                .where(AcquisitionJournalEntry.entry_kind == "activation_rollback", AcquisitionJournalEntry.subject_ref["proposal_id"].astext == str(proposal_id))
            )
        ).scalar_one()
        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "acquisition.activation.rolled_back", AuditLog.resource_id == str(proposal_id))
            )
        ).scalar_one()

    assert result.status == "rolled_back"
    assert proposal.status == "rolled_back"
    assert target.activation_status == "rolled_back"
    assert target.activated_resource_ref["hidden"] is True
    assert target.activation_result["tool_manifest"]["status"] == "hidden"
    assert permission_row.status == "revoked"
    assert permission_row.revoked_at is not None
    assert any(event["event"] == "permission_revoked_for_rollback" for event in permission_row.audit_events)
    assert api_tool.enabled is False
    assert hooks.terminated == ["weather"]
    assert hooks.compensated == ["weather"]
    assert journal_count == 1
    assert audit_count == 1


async def test_rollback_failure_reports_user_visible_recovery_state(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id, approved_hash = await _approved_runtime_proposal(
        tenant_id,
        user_id,
        dedupe_key="rollback failure recovery",
    )
    async with _async_session_factory() as db:
        await run_activation_saga(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            idempotency_key="rollback-failure-activate",
            hooks=FakeActivationHooks(),
        )
        await db.commit()

    async with _async_session_factory() as db:
        result = await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            idempotency_key="rollback-failure",
            hooks=FakeRollbackHooks(fail_compensation=True),
        )
        await db.commit()

    async with _async_session_factory() as db:
        proposal = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal_id))
        ).scalar_one()
        target = (
            await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))
        ).scalar_one()
        failed_audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "acquisition.rollback.failed", AuditLog.resource_id == str(proposal_id))
            )
        ).scalar_one()
        journal_count = (
            await db.execute(
                select(func.count())
                .select_from(AcquisitionJournalEntry)
                .where(AcquisitionJournalEntry.entry_kind == "activation_rollback", AcquisitionJournalEntry.subject_ref["proposal_id"].astext == str(proposal_id))
            )
        ).scalar_one()

    assert result.status == "needs_user_recovery"
    assert "manual recovery" in result.user_visible_recovery_state
    assert proposal.status == "activated"
    assert proposal.evidence["rollback"]["status"] == "needs_user_recovery"
    assert target.activation_result["rollback"]["status"] == "needs_user_recovery"
    assert failed_audit_count == 1
    assert journal_count == 1


async def test_activation_approved_proposal_activates_with_w23_noop_saga(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap = await _gap(tenant_id, user_id)
    recommendation = await _recommendation(tenant_id, user_id, gap.id)
    proposal = await _proposal(tenant_id, user_id, gap.id, recommendation.id)

    async with _async_session_factory() as db:
        verification = await verify_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            verification_kind="contract",
            input_fixture={"city": "London"},
            expected_result={"ok": True},
            actual_result={"ok": True},
            artifact_refs=[{"artifact_id": "verify-weather", "digest": "sha256:evidence"}],
            idempotency_key="verify-before-approval",
        )
        approved = await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            idempotency_key="approve-activation",
        )
        await db.commit()

    assert approved.status == "activation_approved"

    async with _async_session_factory() as db:
        activated = await lifecycle.activate_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            idempotency_key="activate-approved-weather",
        )
        await db.commit()
        assert activated.status == "activated"

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(
                select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id)
            )
        ).scalar_one()
        activation_audit_count = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id == user_id,
                    AuditLog.action == "acquisition.target.activated",
                    AuditLog.resource_id == str(proposal.id),
                )
            )
        ).scalar_one()

        target_count = (
            await db.execute(
                select(func.count())
                .select_from(ActivationTarget)
                .where(ActivationTarget.proposal_id == proposal.id, ActivationTarget.activation_status == "active")
            )
        ).scalar_one()

    assert persisted.status == "activated"
    assert activation_audit_count == 1
    assert target_count == 1


async def test_activation_saga_persists_iso_expires_at_as_datetime(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    permission = _permission_bundle(duration="expires_at")
    permission["expires_at"] = expires_at.isoformat()
    proposal_id, approved_hash = await _approved_runtime_proposal(
        tenant_id,
        user_id,
        primary_target=_primary_target(permission_bundle=permission),
        permission_bundle=permission,
        dedupe_key="expires-at iso standing permission",
    )

    async with _async_session_factory() as db:
        activated = await run_activation_saga(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            idempotency_key="expires-at-iso-saga",
            hooks=FakeActivationHooks(),
        )
        await db.commit()

    async with _async_session_factory() as db:
        permission_row = (
            await db.execute(select(StandingPermission).where(StandingPermission.proposal_id == proposal_id))
        ).scalar_one()

    assert activated.status == "activated"
    assert isinstance(permission_row.expires_at, datetime)
    assert permission_row.expires_at is not None
    assert permission_row.expires_at.isoformat() == expires_at.isoformat()


async def test_activation_target_missing_permission_bundle_does_not_inherit_proposal_bundle(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    primary_target = _primary_target()
    primary_target.pop("permission_bundle")
    proposal_id, approved_hash = await _approved_runtime_proposal(
        tenant_id,
        user_id,
        primary_target=primary_target,
        permission_bundle=_permission_bundle(),
        dedupe_key="missing target permission bundle",
    )

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await run_activation_saga(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal_id,
                approved_hash=approved_hash,
                idempotency_key="missing-target-bundle",
                hooks=FakeActivationHooks(),
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "PERMISSION_BUNDLE_REQUIRED"
