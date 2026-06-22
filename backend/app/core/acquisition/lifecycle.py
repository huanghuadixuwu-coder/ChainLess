"""Canonical lifecycle owner for V3 capability acquisition records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error
from app.core.audit.service import AuditRecord, add_audit_log
from app.core.acquisition import repository
from app.core.acquisition.activation import ActivationHooks, approved_snapshot_hash, run_activation_saga
from app.models.acquisition import AcquisitionProposal, CapabilityGap, CapabilityRecommendation, ExplorationRun
from app.models.conversation import Conversation
from app.models.tool_confirmation import ToolConfirmation


NO_GAP_FAILURE_CLASSES = {
    "missing_user_input",
    "greeting",
    "casual_chat",
    "ambiguous_request",
    "transient_retryable_failure",
    "planner_missed_existing_tool",
}
GAP_FAILURE_TO_TYPE = {
    "tool_not_found": "missing_tool",
    "mcp_not_registered": "missing_mcp",
    "auth_required": "missing_credential",
    "permission_denied": "missing_workspace_access",
    "unsupported_domain": "unsupported_external_action",
    "unsupported_action": "unsupported_external_action",
    "rate_limited": "unstable_public_source",
    "requires_login": "missing_credential",
    "requires_paid_api": "missing_api",
    "requires_credential": "missing_credential",
    "requires_host_filesystem": "missing_workspace_access",
    "requires_browser_automation": "missing_browser_automation",
    "requires_dependency_install": "requires_code_patch",
    "requires_external_write": "unsupported_external_action",
    "unstable_workaround": "unstable_public_source",
}
TERMINAL_REJECTED_PROPOSAL_STATUSES = {"activation_rejected", "dismissed", "superseded"}


@dataclass(frozen=True)
class GapClassification:
    should_create_gap: bool
    reason: str
    gap_type: str | None = None


@dataclass(frozen=True)
class ExplorationBoundsDecision:
    can_auto_run: bool
    requires_approval: bool
    reasons: tuple[str, ...]


def classify_failure_for_gap(
    failure_class: str,
    *,
    has_existing_tool: bool = False,
) -> GapClassification:
    normalized = failure_class.strip().casefold()
    if normalized in NO_GAP_FAILURE_CLASSES:
        return GapClassification(False, normalized)
    if has_existing_tool:
        return GapClassification(False, "planner_missed_existing_tool")
    gap_type = GAP_FAILURE_TO_TYPE.get(normalized)
    if gap_type is None:
        return GapClassification(False, "no_strong_gap_signal")
    return GapClassification(True, normalized, gap_type)


def evaluate_exploration_bounds(bounds: dict[str, Any]) -> ExplorationBoundsDecision:
    """Return whether exploration may start automatically inside W2.1 safe bounds."""

    reasons: list[str] = []
    if bounds.get("requires_login") or bounds.get("uses_login"):
        reasons.append("login_required")
    if bounds.get("uses_credentials") or bounds.get("requires_credentials"):
        reasons.append("credential_required")
    if bounds.get("uses_payment") or bounds.get("paid_api") or bounds.get("quota_consuming"):
        reasons.append("paid_or_quota_service")
    if bounds.get("private_network") or bounds.get("network_scope") in {"private_network", "arbitrary_network"}:
        reasons.append("private_or_arbitrary_network")
    if bounds.get("external_write") or bounds.get("write_scope") in {"external_service", "approved_workspace"}:
        reasons.append("external_write")
    if bounds.get("dependency_install") or bounds.get("package_install") or bounds.get("service_startup"):
        reasons.append("dependency_install")
    if bounds.get("non_idempotent_side_effect") or bounds.get("message_send") or bounds.get("form_submit"):
        reasons.append("non_idempotent_side_effect")
    if bounds.get("browser_automation"):
        reasons.append("browser_automation")
    if bounds.get("host_directory") or bounds.get("data_scope") in {"host_directory", "project_workspace"}:
        reasons.append("host_or_project_workspace")
    if bounds.get("bypasses_access_controls") or bounds.get("paywall") or bounds.get("captcha_bypass"):
        reasons.append("access_control_bypass")
    if not bounds.get("read_only", False):
        reasons.append("not_read_only")

    data_scope = bounds.get("data_scope", "run_workspace")
    network_scope = bounds.get("network_scope", "none")
    write_scope = bounds.get("write_scope", "run_workspace")
    safe_data = data_scope in {"current_run", "uploaded_files", "run_workspace", "public_web", "approved_tools", "none"}
    safe_network = network_scope in {"none", "public_web", "allowlisted_public_web"}
    safe_write = write_scope in {"none", "temporary_artifacts", "run_workspace"}
    if not safe_data:
        reasons.append("unsafe_data_scope")
    if not safe_network:
        reasons.append("unsafe_network_scope")
    if not safe_write:
        reasons.append("unsafe_write_scope")
    if bounds.get("cleanup_supported") is False:
        reasons.append("cleanup_not_supported")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return ExplorationBoundsDecision(
        can_auto_run=not unique_reasons,
        requires_approval=bool(unique_reasons),
        reasons=unique_reasons,
    )


async def _audit(
    db: AsyncSession,
    *,
    action: str,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    details: dict[str, Any] | None = None,
) -> None:
    await add_audit_log(
        db,
        AuditRecord(
            action=action,
            method="SYSTEM",
            path="/internal/acquisition/lifecycle",
            status_code=200,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=str(resource_id),
            details=details or {},
        ),
    )


async def _validate_exploration_approval(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    approval_id: uuid.UUID,
) -> None:
    approved = (
        await db.execute(
            select(ToolConfirmation.id)
            .join(Conversation, ToolConfirmation.conversation_id == Conversation.id)
            .where(
                ToolConfirmation.id == approval_id,
                ToolConfirmation.status == "approved",
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if approved is None:
        raise api_error(
            409,
            "EXPLORATION_APPROVAL_INVALID",
            "Exploration approval must be an approved confirmation owned by this tenant and user",
            {"approval_id": str(approval_id)},
        )


async def record_gap(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_kind: str,
    source_run_id: str,
    dedupe_key: str,
    title: str,
    description: str,
    gap_type: str,
    severity: str = "medium",
    conversation_id: uuid.UUID | None = None,
    source_evidence: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
    source_class: str | None = None,
    idempotency_key: str | None = None,
) -> CapabilityGap:
    gap, created, changed = await repository.create_or_increment_gap(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        source_kind=source_kind,
        source_run_id=source_run_id,
        conversation_id=conversation_id,
        dedupe_key=dedupe_key,
        title=title,
        description=description,
        gap_type=gap_type,
        severity=severity,
        source_evidence=source_evidence,
        evidence=evidence,
        source_class=source_class,
        idempotency_key=idempotency_key,
    )
    if changed:
        await _audit(
            db,
            action="acquisition.gap.created" if created else "acquisition.gap.deduped",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="capability_gap",
            resource_id=gap.id,
            details={
                "gap_type": gap.gap_type,
                "dedupe_key": gap.dedupe_key,
                "occurrence_count": gap.occurrence_count,
                "idempotency_key": idempotency_key,
            },
        )
        await db.refresh(gap)
    return gap


async def record_failure(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    failure_class: str,
    source_kind: str,
    source_run_id: str,
    dedupe_key: str,
    title: str,
    description: str,
    severity: str = "medium",
    has_existing_tool: bool = False,
    evidence: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> CapabilityGap | None:
    classification = classify_failure_for_gap(failure_class, has_existing_tool=has_existing_tool)
    if not classification.should_create_gap or classification.gap_type is None:
        return None
    return await record_gap(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        source_kind=source_kind,
        source_run_id=source_run_id,
        dedupe_key=dedupe_key,
        title=title,
        description=description,
        gap_type=classification.gap_type,
        severity=severity,
        evidence={"failure_class": failure_class, **(evidence or {})},
        idempotency_key=idempotency_key,
    )


async def start_exploration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    source_run_id: str,
    strategy: str,
    risk_level: str,
    bounds: dict[str, Any],
    approval_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> ExplorationRun:
    await repository.get_gap(db, tenant_id=tenant_id, user_id=user_id, gap_id=gap_id)
    decision = evaluate_exploration_bounds(bounds)
    if decision.requires_approval and approval_id is None:
        raise api_error(
            409,
            "EXPLORATION_APPROVAL_REQUIRED",
            "Exploration requires explicit approval before it can start",
            {"reasons": list(decision.reasons)},
        )
    if decision.requires_approval and approval_id is not None:
        await _validate_exploration_approval(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            approval_id=approval_id,
        )
    status = "running" if decision.can_auto_run or approval_id is not None else "queued"
    exploration, created = await repository.create_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        source_run_id=source_run_id,
        risk_level=risk_level,
        strategy=strategy,
        status=status,
        approval_id=approval_id,
        tool_events=[{"kind": "bounds", "decision": decision.__dict__, "bounds": bounds}],
        idempotency_key=idempotency_key,
    )
    if created:
        await repository.transition_gap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap_id,
            status="exploring" if status == "running" else "exploration_approved",
            idempotency_key=f"{idempotency_key}:gap-status" if idempotency_key else None,
        )
        await _audit(
            db,
            action="acquisition.exploration.started",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="exploration_run",
            resource_id=exploration.id,
            details={
                "gap_id": str(gap_id),
                "strategy": strategy,
                "risk_level": risk_level,
                "bounds_reasons": list(decision.reasons),
                "idempotency_key": idempotency_key,
            },
        )
        await db.refresh(exploration)
    return exploration


async def complete_exploration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    exploration_id: uuid.UUID,
    status: str,
    result_summary: str | None = None,
    failure_reason: str | None = None,
    idempotency_key: str | None = None,
) -> ExplorationRun:
    if status not in {"succeeded", "failed", "blocked_by_policy", "cancelled", "timed_out"}:
        raise api_error(422, "INVALID_EXPLORATION_STATUS", "Invalid exploration completion status")
    exploration, changed = await repository.transition_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        exploration_id=exploration_id,
        status=status,
        result_summary=result_summary,
        failure_reason=failure_reason,
        idempotency_key=idempotency_key,
    )
    if not changed:
        return exploration
    gap_status = "explored_success" if status == "succeeded" else "explored_failed"
    await repository.transition_gap(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=exploration.gap_id,
        status=gap_status,
        idempotency_key=f"{idempotency_key}:gap-status" if idempotency_key else None,
    )
    await _audit(
        db,
        action="acquisition.exploration.succeeded" if status == "succeeded" else "acquisition.exploration.failed",
        tenant_id=tenant_id,
        user_id=user_id,
        resource_type="exploration_run",
        resource_id=exploration.id,
        details={"status": status, "gap_id": str(exploration.gap_id), "idempotency_key": idempotency_key},
    )
    await db.refresh(exploration)
    return exploration


async def create_recommendation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    recommendation_type: str,
    title: str,
    summary: str,
    reason: str,
    evidence: dict[str, Any],
    risk_level: str,
    expected_value: dict[str, Any] | None = None,
    required_permissions: dict[str, Any] | None = None,
    candidate_targets: list[dict[str, Any]] | None = None,
    exploration_run_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> CapabilityRecommendation:
    recommendation, created = await repository.create_recommendation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        exploration_run_id=exploration_run_id,
        recommendation_type=recommendation_type,
        title=title,
        summary=summary,
        reason=reason,
        evidence=evidence,
        risk_level=risk_level,
        expected_value=expected_value,
        required_permissions=required_permissions,
        candidate_targets=candidate_targets,
        idempotency_key=idempotency_key,
    )
    if created:
        await repository.transition_gap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap_id,
            status="recommendation_created",
            idempotency_key=f"{idempotency_key}:gap-status" if idempotency_key else None,
        )
        await _audit(
            db,
            action="acquisition.recommendation.created",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="capability_recommendation",
            resource_id=recommendation.id,
            details={"gap_id": str(gap_id), "recommendation_type": recommendation_type, "idempotency_key": idempotency_key},
        )
        await db.refresh(recommendation)
    return recommendation


async def create_proposal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_kind: str,
    gap_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    title: str,
    reason: str,
    evidence: dict[str, Any],
    risk_level: str,
    permission_bundle: dict[str, Any],
    verification_plan: dict[str, Any],
    rollback_plan: dict[str, Any],
    user_visible_effect: str,
    primary_target: dict[str, Any] | None = None,
    secondary_targets: list[dict[str, Any]] | None = None,
    development_handoff: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> AcquisitionProposal:
    proposal, created = await repository.create_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_kind=proposal_kind,
        gap_id=gap_id,
        recommendation_id=recommendation_id,
        title=title,
        reason=reason,
        evidence=evidence,
        risk_level=risk_level,
        permission_bundle=permission_bundle,
        primary_target=primary_target,
        secondary_targets=secondary_targets,
        development_handoff=development_handoff,
        verification_plan=verification_plan,
        rollback_plan=rollback_plan,
        user_visible_effect=user_visible_effect,
        idempotency_key=idempotency_key,
    )
    if created:
        await repository.transition_gap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap_id,
            status="proposal_drafted",
            idempotency_key=f"{idempotency_key}:gap-status" if idempotency_key else None,
        )
        await _audit(
            db,
            action="acquisition.proposal.created",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="acquisition_proposal",
            resource_id=proposal.id,
            details={
                "gap_id": str(gap_id),
                "recommendation_id": str(recommendation_id),
                "proposal_kind": proposal_kind,
                "idempotency_key": idempotency_key,
            },
        )
        await db.refresh(proposal)
    return proposal


async def reject_activation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> AcquisitionProposal:
    proposal, changed = await repository.transition_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        status="activation_rejected",
        actor_user_id=user_id,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    if changed:
        await _audit(
            db,
            action="acquisition.activation.rejected",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="acquisition_proposal",
            resource_id=proposal.id,
            details={"reason": reason, "idempotency_key": idempotency_key},
        )
        await db.refresh(proposal)
    return proposal


async def activate_proposal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    idempotency_key: str | None = None,
    hooks: ActivationHooks | None = None,
) -> AcquisitionProposal:
    proposal = await repository.get_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.status in TERMINAL_REJECTED_PROPOSAL_STATUSES:
        raise api_error(
            409,
            "PROPOSAL_CANNOT_ACTIVATE",
            "Rejected, dismissed, or superseded proposals cannot activate",
            {"status": proposal.status},
        )
    if proposal.status != "activation_approved":
        raise api_error(
            409,
            "PROPOSAL_NOT_ACTIVATION_APPROVED",
            "Proposal must be activation_approved before activation",
            {"status": proposal.status},
        )
    bound_hash = approved_snapshot_hash(proposal)
    if not bound_hash:
        raise api_error(
            409,
            "APPROVED_SNAPSHOT_HASH_MISSING",
            "Activation requires a bound approved snapshot hash",
            {"status": proposal.status, "idempotency_key": idempotency_key},
        )
    return await run_activation_saga(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        approved_hash=bound_hash,
        idempotency_key=idempotency_key,
        hooks=hooks,
    )


def is_activation_rejection(exc: HTTPException) -> bool:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    error = detail.get("error") if isinstance(detail.get("error"), dict) else {}
    return error.get("code") == "PROPOSAL_CANNOT_ACTIVATE"
