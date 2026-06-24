"""Acquisition permission gate for V3-activated Workers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.acquisition.activation import approved_snapshot_hash
from app.core.acquisition.policy import RuntimePermissionRequest, evaluate_runtime_permission
from app.models.acquisition import ActivationTarget, AcquisitionProposal
from app.models.worker import Worker, WorkerVersion


@dataclass(frozen=True)
class WorkerAcquisitionPolicyDecision:
    """Small adapter result for Worker owners."""

    action: str
    code: str = "ALLOWED"
    message: str = "Worker is allowed by acquisition policy"
    confirmation_context: dict[str, Any] | None = None


async def evaluate_acquired_worker_policy(
    db: AsyncSession,
    *,
    worker: Worker,
    version: WorkerVersion | None,
    input_payload: dict[str, Any],
    source_run_id: str | None,
    worker_context: dict[str, Any] | None = None,
) -> WorkerAcquisitionPolicyDecision:
    """Return allow/confirm/block for Workers created by acquisition activation."""

    evidence = worker.activation_evidence if isinstance(worker.activation_evidence, dict) else {}
    if evidence.get("source") != "acquisition":
        return WorkerAcquisitionPolicyDecision("allow")
    target_id = _uuid_or_none(evidence.get("target_id"))
    proposal_id = _uuid_or_none(evidence.get("proposal_id"))
    if target_id is None or proposal_id is None:
        return WorkerAcquisitionPolicyDecision(
            "block",
            "ACQUIRED_WORKER_EVIDENCE_INCOMPLETE",
            "Acquired Worker execution requires proposal and target evidence",
        )

    target = await _load_active_worker_target(db, worker=worker, version=version, target_id=target_id)
    if target is None:
        return WorkerAcquisitionPolicyDecision(
            "block",
            "ACQUIRED_WORKER_TARGET_NOT_ACTIVE",
            "Acquired Worker target is not active or no longer exposed to runtime",
        )

    proposal = (
        await db.execute(
            select(AcquisitionProposal).where(
                AcquisitionProposal.id == target.proposal_id,
                AcquisitionProposal.tenant_id == worker.tenant_id,
                AcquisitionProposal.user_id == worker.user_id,
            )
        )
    ).scalar_one_or_none()
    approved_hash = approved_snapshot_hash(proposal) if proposal else None
    current_hash = proposal.activation_snapshot_hash if proposal else None
    if not proposal or not approved_hash or not current_hash:
        return WorkerAcquisitionPolicyDecision(
            "block",
            "ACQUIRED_WORKER_APPROVAL_MISSING",
            "Acquired Worker execution requires verified and approved activation snapshot evidence",
        )

    bundle = target.permission_bundle if isinstance(target.permission_bundle, Mapping) else {}
    request = RuntimePermissionRequest(
        tenant_id=worker.tenant_id,
        user_id=worker.user_id,
        proposal_id=proposal.id,
        target_id=target.id,
        target_type="worker",
        permission_bundle=bundle,
        approved_snapshot_hash=approved_hash,
        current_snapshot_hash=current_hash,
        permission_scope=bundle.get("permission_scope") if isinstance(bundle.get("permission_scope"), Mapping) else None,
        risk_level=str(bundle.get("risk_level") or (worker.policy or {}).get("risk") or "risky"),
        action_category=str(bundle.get("action_category") or bundle.get("side_effect_category") or "read"),
        tool_context={
            "worker_id": str(worker.id),
            "worker_version_id": str(version.id) if version is not None else None,
            "source_run_id": source_run_id,
            "input_fields": sorted(str(key) for key in input_payload.keys()),
            "parent_worker_run_id": (worker_context or {}).get("worker_run_id"),
        },
        confirmation_context=(worker_context or {}).get("acquisition_confirmation_context"),
    )
    decision = await evaluate_runtime_permission(db, request)
    if decision.confirmation_required:
        return WorkerAcquisitionPolicyDecision(
            "confirm",
            decision.code,
            decision.message,
            confirmation_context=decision.context,
        )
    if not decision.allowed:
        return WorkerAcquisitionPolicyDecision("block", decision.code, decision.message)
    return WorkerAcquisitionPolicyDecision("allow")

async def _load_active_worker_target(
    db: AsyncSession,
    *,
    worker: Worker,
    version: WorkerVersion | None,
    target_id: uuid.UUID,
) -> ActivationTarget | None:
    target = (
        await db.execute(
            select(ActivationTarget).where(
                ActivationTarget.id == target_id,
                ActivationTarget.tenant_id == worker.tenant_id,
                ActivationTarget.user_id == worker.user_id,
                ActivationTarget.target_type == "worker",
                ActivationTarget.activation_status == "active",
            )
        )
    ).scalar_one_or_none()
    if target is None:
        return None
    ref = target.activated_resource_ref if isinstance(target.activated_resource_ref, dict) else {}
    if ref.get("hidden") is True or ref.get("exposed_to_runtime") is False:
        return None
    if ref.get("worker_id") and ref.get("worker_id") != str(worker.id):
        return None
    if version is not None and ref.get("worker_version_id") and ref.get("worker_version_id") != str(version.id):
        return None
    return target


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
