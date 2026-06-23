"""V3 acquisition activation targets backed by V2 capability owners."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.acquisition import lifecycle
from app.core.acquisition.activation import approve_activation
from app.core.acquisition.rollback import rollback_activation
from app.core.acquisition.verification import verify_proposal
from app.models.acquisition import AcquisitionProposal, ActivationTarget
from app.models.audit_log import AuditLog
from app.models.capability import CapabilityCandidate
from app.models.memory import Memory
from app.models.skill import Skill
from app.models.worker import Worker, WorkerVersion
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


def _permission_bundle(target_type: str, *, duration: str = "until_revoked") -> dict:
    execution_scope = "worker_run" if target_type == "worker" else "code_as_action_temp"
    return {
        "target_type": target_type,
        "permission_scope": {"capability": target_type},
        "risk_level": "safe",
        "confirmation_policy": "before_activation_only",
        "credential_scope": "none",
        "credential_connection_refs": [],
        "data_scope": "none",
        "network_scope": "none",
        "egress_policy": {},
        "write_scope": "none",
        "execution_scope": execution_scope,
        "duration": duration,
        "revocation_plan": {"disable": True},
        "audit_events": [],
    }


def _target(target_type: str, payload: dict, *, name: str | None = None) -> dict:
    permission = _permission_bundle(target_type)
    return {
        "target_type": target_type,
        "target_name": name or f"{target_type}-{uuid.uuid4().hex}",
        "target_owner": "core.v2_capabilities",
        "target_payload": payload,
        "permission_bundle": permission,
        "verification_plan": {"kind": "v2-owner-contract"},
        "rollback_plan": {"disable": True},
        "activation_status": "draft",
        "activation_result": {},
    }


async def _create_proposal(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    target_type: str,
    payload: dict,
    name: str | None = None,
    secondary_targets: list[dict] | None = None,
) -> uuid.UUID:
    async with _async_session_factory() as db:
        gap = await lifecycle.record_gap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_kind="agent_runtime",
            source_run_id=f"run-{uuid.uuid4().hex}",
            dedupe_key=f"{target_type}:{uuid.uuid4().hex}",
            title=f"Missing {target_type} capability",
            description=f"Need a reusable {target_type} capability.",
            gap_type="missing_tool",
            severity="medium",
            source_evidence=[{"kind": "test", "message": "v2 target test"}],
            evidence={"target_type": target_type},
            idempotency_key=f"gap-{uuid.uuid4().hex}",
        )
        recommendation = await lifecycle.create_recommendation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap.id,
            recommendation_type=f"{target_type}_recommendation",
            title=f"Activate {target_type}",
            summary=f"Activate a V2-owned {target_type}.",
            reason="The acquired capability should become reusable.",
            evidence={"source": "test"},
            risk_level="safe",
            expected_value={"reusable": True},
            required_permissions={"target_type": target_type},
            candidate_targets=[{"target_type": target_type}],
            idempotency_key=f"rec-{uuid.uuid4().hex}",
        )
        primary_target = _target(target_type, payload, name=name)
        proposal = await lifecycle.create_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_kind="runtime_activation",
            gap_id=gap.id,
            recommendation_id=recommendation.id,
            title=f"Activate {target_type}",
            reason="V3 verified this V2 capability target.",
            evidence={"source": "test"},
            risk_level="safe",
            permission_bundle=primary_target["permission_bundle"],
            primary_target=primary_target,
            secondary_targets=secondary_targets,
            verification_plan={"kind": "v2-owner-contract"},
            rollback_plan={"disable": True},
            user_visible_effect=f"{target_type} becomes available to Agent planning.",
            idempotency_key=f"proposal-{uuid.uuid4().hex}",
        )
        await db.commit()
        return proposal.id


async def _verify_only(proposal_id: uuid.UUID, tenant_id: uuid.UUID, user_id: uuid.UUID):
    async with _async_session_factory() as db:
        verification = await verify_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            actual_result={"ok": True},
            idempotency_key=f"verify-{uuid.uuid4().hex}",
        )
        await db.commit()
        return verification


async def _activate_proposal(proposal_id: uuid.UUID, tenant_id: uuid.UUID, user_id: uuid.UUID) -> AcquisitionProposal:
    async with _async_session_factory() as db:
        verification = await verify_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            actual_result={"ok": True},
            idempotency_key=f"verify-{uuid.uuid4().hex}",
        )
        assert verification.status == "passed"
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=verification.verified_snapshot_hash,
            reason="test approval",
            idempotency_key=f"approve-{uuid.uuid4().hex}",
        )
        activated = await lifecycle.activate_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            idempotency_key=f"activate-{uuid.uuid4().hex}",
        )
        await db.commit()
        return activated


def _worker_payload(*, name: str | None = None) -> dict:
    return {
        "name": name or f"Worker {uuid.uuid4().hex}",
        "description": "Handle repeatable release notes work.",
        "trigger": {"type": "semantic", "examples": ["draft release notes"]},
        "policy": {"allowed_tools": ["file_read"], "risk": "low"},
        "definition": {
            "instructions": "Draft release notes from a changelog.",
            "input_schema": {
                "type": "object",
                "required": ["changelog"],
                "properties": {"changelog": {"type": "string"}},
            },
        },
        "verification_plan": {"checks": ["schema", "allowed_tools"]},
    }


async def test_worker_target_requires_verified_worker_version_schema_allowed_tools_and_permission_snapshot(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="worker",
        payload={"name": "Invalid Worker", "definition": {"instructions": "missing schema"}},
    )

    verification = await _verify_only(proposal_id, tenant_id, user_id)

    assert verification.status == "failed"
    assert verification.error_code == "V2_TARGET_VERIFICATION_FAILED"
    codes = {item["code"] for item in verification.actual_result["v2_target_errors"]}
    assert "WORKER_TARGET_INPUT_SCHEMA_REQUIRED" in codes
    assert "WORKER_TARGET_ALLOWED_TOOLS_REQUIRED" in codes


async def test_worker_target_activation_creates_or_updates_worker_version_through_worker_owner(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="worker",
        payload=_worker_payload(),
    )

    activated = await _activate_proposal(proposal_id, tenant_id, user_id)

    async with _async_session_factory() as db:
        target = (await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))).scalar_one()
        worker = await db.get(Worker, uuid.UUID(target.activated_resource_ref["worker_id"]))
        version = await db.get(WorkerVersion, uuid.UUID(target.activated_resource_ref["worker_version_id"]))
        proposal = await db.get(AcquisitionProposal, proposal_id)
        audit = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "acquisition.target.activated",
                    AuditLog.resource_id == str(proposal_id),
                )
            )
        ).scalar_one()

    assert activated.status == "activated"
    assert target.activation_status == "active"
    assert worker is not None and worker.status == "active" and worker.enabled is True
    assert version is not None and version.status == "active"
    assert worker.activation_evidence["proposal_id"] == str(proposal_id)
    assert worker.activation_evidence["approved_snapshot_hash"].startswith("sha256:")
    assert target.activation_result["evidence"]["runtime_side_effects"] is True
    assert target.activation_result["evidence"]["durable_side_effects"] is True
    assert proposal.approval_history[-1]["activation_saga"]["runtime_side_effects"] is True
    assert proposal.approval_history[-1]["activation_saga"]["durable_side_effects"] is True
    assert audit.details["runtime_side_effects"] is True
    assert audit.details["durable_side_effects"] is True


async def test_worker_target_update_rollback_restores_existing_worker_version(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    async with _async_session_factory() as db:
        worker = Worker(
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"Original worker {uuid.uuid4().hex}",
            description="Original description",
            status="active",
            enabled=True,
            trigger={"type": "manual", "examples": ["original"]},
            policy={"allowed_tools": ["file_read"], "risk": "low"},
            activation_confirmed_at=datetime.now(timezone.utc),
            activation_confirmed_by=user_id,
            activation_evidence={"approved_by": "original"},
        )
        db.add(worker)
        await db.flush()
        old_version = WorkerVersion(
            tenant_id=tenant_id,
            user_id=user_id,
            worker_id=worker.id,
            version=1,
            status="active",
            definition={
                "instructions": "Original worker",
                "input_schema": {
                    "type": "object",
                    "required": ["request"],
                    "properties": {"request": {"type": "string"}},
                },
                "allowed_tools": ["file_read"],
            },
            verification_evidence={"source": "original"},
            verified_by=user_id,
            verified_at=datetime.now(timezone.utc),
            activated_at=datetime.now(timezone.utc),
        )
        db.add(old_version)
        await db.flush()
        pending_version = WorkerVersion(
            tenant_id=tenant_id,
            user_id=user_id,
            worker_id=worker.id,
            version=2,
            status="verified",
            definition={
                "instructions": "Pending worker",
                "input_schema": {
                    "type": "object",
                    "required": ["request"],
                    "properties": {"request": {"type": "string"}},
                },
                "allowed_tools": ["file_read"],
            },
            verification_evidence={"source": "pending"},
            verified_by=user_id,
            verified_at=datetime.now(timezone.utc),
        )
        db.add(pending_version)
        await db.flush()
        worker.active_version_id = old_version.id
        worker.activation_token = f"pending-{uuid.uuid4().hex}"
        worker.activation_requested_version_id = pending_version.id
        worker.activation_requested_at = datetime.now(timezone.utc)
        await db.commit()
        worker_id = worker.id
        old_version_id = old_version.id
        pending_version_id = pending_version.id
        pending_token = worker.activation_token
        pending_requested_at = worker.activation_requested_at

    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="worker",
        payload={
            **_worker_payload(name=f"Updated worker {uuid.uuid4().hex}"),
            "worker_id": str(worker_id),
            "description": "Updated description",
        },
    )
    await _activate_proposal(proposal_id, tenant_id, user_id)

    async with _async_session_factory() as db:
        active_target = (
            await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))
        ).scalar_one()
        new_version_id = uuid.UUID(active_target.activated_resource_ref["worker_version_id"])
        updated_worker = await db.get(Worker, worker_id)
        new_version = await db.get(WorkerVersion, new_version_id)
        assert updated_worker is not None and updated_worker.description == "Updated description"
        assert updated_worker.active_version_id == new_version_id
        assert new_version is not None and new_version.status == "active"

        await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            reason="restore existing worker",
            idempotency_key=f"rollback-{uuid.uuid4().hex}",
        )
        await db.commit()

    async with _async_session_factory() as db:
        target = (await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))).scalar_one()
        restored_worker = await db.get(Worker, worker_id)
        old_version = await db.get(WorkerVersion, old_version_id)
        new_version = await db.get(WorkerVersion, new_version_id)

    assert target.activation_status == "rolled_back"
    assert restored_worker is not None
    assert restored_worker.status == "active"
    assert restored_worker.enabled is True
    assert restored_worker.description == "Original description"
    assert restored_worker.active_version_id == old_version_id
    assert restored_worker.activation_token == pending_token
    assert restored_worker.activation_requested_version_id == pending_version_id
    assert restored_worker.activation_requested_at == pending_requested_at
    assert restored_worker.activation_evidence == {"approved_by": "original"}
    assert old_version is not None and old_version.status == "active"
    assert new_version is not None and new_version.status == "archived"


async def test_worker_target_rollback_disables_or_rolls_back_worker_version(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id = await _create_proposal(tenant_id, user_id, target_type="worker", payload=_worker_payload())
    await _activate_proposal(proposal_id, tenant_id, user_id)

    async with _async_session_factory() as db:
        await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            reason="test rollback",
            idempotency_key=f"rollback-{uuid.uuid4().hex}",
        )
        await db.commit()

    async with _async_session_factory() as db:
        target = (await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))).scalar_one()
        worker = await db.get(Worker, uuid.UUID(target.activated_resource_ref["worker_id"]))
        version = await db.get(WorkerVersion, uuid.UUID(target.activated_resource_ref["worker_version_id"]))

    assert target.activation_status == "rolled_back"
    assert worker is not None and worker.status == "disabled" and worker.enabled is False
    assert version is not None and version.status == "archived"


async def test_skill_target_requires_trigger_or_semantic_match_and_no_embedded_runtime_permission(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="skill",
        payload={"name": "Unsafe Skill", "runtime_permission": {"network": "public_web"}},
    )

    verification = await _verify_only(proposal_id, tenant_id, user_id)

    assert verification.status == "failed"
    codes = {item["code"] for item in verification.actual_result["v2_target_errors"]}
    assert "SKILL_TARGET_EMBEDDED_RUNTIME_PERMISSION" in codes
    assert "SKILL_TARGET_TRIGGER_OR_SEMANTIC_MATCH_REQUIRED" in codes


async def test_skill_target_activation_creates_private_skill_through_skill_owner(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="skill",
        payload={
            "name": f"Release notes skill {uuid.uuid4().hex}",
            "description": "Turn changelogs into user-facing release notes.",
            "trigger_terms": ["release notes", "changelog"],
        },
    )

    activated = await _activate_proposal(proposal_id, tenant_id, user_id)

    async with _async_session_factory() as db:
        target = (await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))).scalar_one()
        skill = await db.get(Skill, uuid.UUID(target.activated_resource_ref["skill_id"]))

    assert activated.status == "activated"
    assert skill is not None
    assert skill.user_id == user_id
    assert skill.scope == "private"
    assert skill.enabled is True
    assert "release notes" in skill.trigger_terms


async def test_skill_target_rollback_disables_or_deletes_skill(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="skill",
        payload={"name": f"Rollback skill {uuid.uuid4().hex}", "trigger_terms": ["rollback skill"]},
    )
    await _activate_proposal(proposal_id, tenant_id, user_id)

    async with _async_session_factory() as db:
        await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            reason="test rollback",
            idempotency_key=f"rollback-{uuid.uuid4().hex}",
        )
        await db.commit()

    async with _async_session_factory() as db:
        target = (await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))).scalar_one()
        skill = await db.get(Skill, uuid.UUID(target.activated_resource_ref["skill_id"]))

    assert target.activation_status == "rolled_back"
    assert skill is not None and skill.enabled is False


async def test_memory_target_requires_source_evidence_user_scope_and_secret_redaction(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    payloads = [
        {"name": "Missing evidence", "content": "Remember the release checklist."},
        {
            "name": "Shared memory",
            "content": "Remember the release checklist.",
            "scope": "shared",
            "source_evidence": [{"kind": "message", "message": "user approved"}],
        },
        {
            "name": "Secret memory",
            "content": "api_key=super-secret",
            "source_evidence": [{"kind": "message", "message": "user approved"}],
        },
    ]
    expected_codes = {
        "MEMORY_TARGET_SOURCE_EVIDENCE_REQUIRED",
        "MEMORY_TARGET_PRIVATE_SCOPE_REQUIRED",
        "MEMORY_TARGET_RAW_SECRET_FORBIDDEN",
    }

    observed_codes: set[str] = set()
    for payload in payloads:
        proposal_id = await _create_proposal(tenant_id, user_id, target_type="memory", payload=payload)
        verification = await _verify_only(proposal_id, tenant_id, user_id)
        observed_codes.update(item["code"] for item in verification.actual_result["v2_target_errors"])

    assert expected_codes <= observed_codes


async def test_memory_target_activation_writes_private_memory_through_memory_owner(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="memory",
        payload={
            "name": f"Release checklist {uuid.uuid4().hex}",
            "content": "Always include upgrade notes and rollback notes.",
            "tags": ["release"],
            "source_evidence": [{"kind": "message", "message": "User asked to remember this checklist."}],
        },
    )

    activated = await _activate_proposal(proposal_id, tenant_id, user_id)

    async with _async_session_factory() as db:
        target = (await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))).scalar_one()
        memory = await db.get(Memory, uuid.UUID(target.activated_resource_ref["memory_id"]))

    assert activated.status == "activated"
    assert memory is not None
    assert memory.user_id == user_id
    assert memory.content == "Always include upgrade notes and rollback notes."
    assert memory.meta_data["source"]["proposal_id"] == str(proposal_id)


async def test_memory_target_rollback_archives_or_deletes_memory(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="memory",
        payload={
            "name": f"Rollback memory {uuid.uuid4().hex}",
            "content": "Temporary memory created by acquisition.",
            "source_evidence": [{"kind": "message", "message": "User accepted memory."}],
        },
    )
    await _activate_proposal(proposal_id, tenant_id, user_id)

    async with _async_session_factory() as db:
        before_target = (
            await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))
        ).scalar_one()
        memory_id = uuid.UUID(before_target.activated_resource_ref["memory_id"])
        await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            reason="test rollback",
            idempotency_key=f"rollback-{uuid.uuid4().hex}",
        )
        await db.commit()

    async with _async_session_factory() as db:
        target = (await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id))).scalar_one()
        memory = await db.get(Memory, memory_id)

    assert target.activation_status == "rolled_back"
    assert memory is None


async def test_memory_target_partial_rollback_retry_does_not_redelete_compensated_memory(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    skill_target = _target(
        "skill",
        {"name": f"Failing rollback skill {uuid.uuid4().hex}", "trigger_terms": ["failing rollback"]},
        name="failing-skill",
    )
    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="memory",
        payload={
            "name": f"Partial rollback memory {uuid.uuid4().hex}",
            "content": "Memory should be deleted only once.",
            "source_evidence": [{"kind": "message", "message": "User accepted memory."}],
        },
        secondary_targets=[skill_target],
    )
    await _activate_proposal(proposal_id, tenant_id, user_id)

    async with _async_session_factory() as db:
        targets = list(
            (
                await db.execute(
                    select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id)
                )
            ).scalars()
        )
        skill_target_row = next(target for target in targets if target.target_type == "skill")
        skill = await db.get(Skill, uuid.UUID(skill_target_row.activated_resource_ref["skill_id"]))
        assert skill is not None
        await db.delete(skill)
        await db.commit()

    async with _async_session_factory() as db:
        first = await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            reason="partial rollback",
            idempotency_key=f"rollback-{uuid.uuid4().hex}",
        )
        await db.commit()

    async with _async_session_factory() as db:
        second = await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            reason="partial rollback retry",
            idempotency_key=f"rollback-{uuid.uuid4().hex}",
        )
        await db.commit()

    first_memory = next(item for item in first.target_results if item["target_type"] == "memory")
    second_memory = next(item for item in second.target_results if item["target_type"] == "memory")
    second_skill = next(item for item in second.target_results if item["target_type"] == "skill")
    assert first.status == "needs_user_recovery"
    assert first_memory["status"] == "rolled_back"
    assert second.status == "needs_user_recovery"
    assert second_memory["status"] == "rolled_back"
    assert second_memory["compensation"]["already_rolled_back"] is True
    assert second_skill["status"] == "needs_user_recovery"


async def test_v2_target_activation_failure_keeps_saga_transaction_recordable(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    conflicting_name = f"Conflicting skill {uuid.uuid4().hex}"
    async with _async_session_factory() as db:
        db.add(
            Skill(
                tenant_id=tenant_id,
                user_id=user_id,
                scope="private",
                name=conflicting_name,
                description="Existing private skill",
                trigger_terms=["existing"],
                enabled=True,
                metadata_={},
            )
        )
        await db.commit()

    skill_target = _target(
        "skill",
        {"name": conflicting_name, "trigger_terms": ["conflict"]},
        name="conflicting-skill",
    )
    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="memory",
        payload={
            "name": f"Transaction memory {uuid.uuid4().hex}",
            "content": "Primary should remain active when secondary fails.",
            "source_evidence": [{"kind": "message", "message": "User accepted memory."}],
        },
        secondary_targets=[skill_target],
    )

    activated = await _activate_proposal(proposal_id, tenant_id, user_id)

    async with _async_session_factory() as db:
        targets = list(
            (
                await db.execute(
                    select(ActivationTarget).where(ActivationTarget.proposal_id == proposal_id)
                )
            ).scalars()
        )
        memory_target = next(target for target in targets if target.target_type == "memory")
        skill_target = next(target for target in targets if target.target_type == "skill")
        memory = await db.get(Memory, uuid.UUID(memory_target.activated_resource_ref["memory_id"]))

    assert activated.status == "partial_activation"
    assert memory_target.activation_status == "active"
    assert memory is not None
    assert skill_target.activation_status == "activation_failed"
    assert skill_target.activation_result["error_code"] in {"IntegrityError", "CAPABILITY_ACCEPTANCE_CONFLICT"}


async def test_v2_target_activation_does_not_store_v3_state_in_capability_candidate_metadata(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    async with _async_session_factory() as db:
        candidate = CapabilityCandidate(
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_type="skill",
            title="Existing candidate",
            evidence={"source": "test"},
            payload={"name": "candidate"},
            metadata_={"existing": "kept"},
        )
        db.add(candidate)
        await db.commit()
        candidate_id = candidate.id

    proposal_id = await _create_proposal(
        tenant_id,
        user_id,
        target_type="skill",
        payload={"name": f"No candidate pollution {uuid.uuid4().hex}", "trigger_terms": ["no pollution"]},
    )
    await _activate_proposal(proposal_id, tenant_id, user_id)

    async with _async_session_factory() as db:
        candidate = await db.get(CapabilityCandidate, candidate_id)
        all_candidates = list(
            (
                await db.execute(
                    select(CapabilityCandidate).where(
                        CapabilityCandidate.tenant_id == tenant_id,
                        CapabilityCandidate.user_id == user_id,
                    )
                )
            ).scalars()
        )

    assert candidate is not None
    assert candidate.metadata_ == {"existing": "kept"}
    assert len(all_candidates) == 1
    assert "activation_snapshot_hash" not in candidate.metadata_
    assert "proposal_id" not in candidate.metadata_
