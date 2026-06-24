"""Activation approval binding, start guards, and saga execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error
from app.core.audit.service import AuditRecord, add_audit_log
from app.core.acquisition import repository
from app.core.acquisition.policy import (
    build_standing_permission_scope,
    normalize_permission_expires_at,
    validate_permission_bundle,
)
from app.core.acquisition.snapshot import build_activation_snapshot_payload, snapshot_hash
from app.core.acquisition.verification import _credential_generations
from app.core.capabilities.bounds import validate_bounded_json
from app.models.acquisition import ActivationTarget, AcquisitionProposal, AcquisitionVerification, StandingPermission


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TargetActivationResult:
    """Result returned by a target runtime owner hook.

    The default hook intentionally records a no-side-effect activation reference
    so W2.3 can verify saga behavior without starting real target runtimes.
    """

    success: bool
    activated_resource_ref: dict[str, Any] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    runtime_session_ref: dict[str, Any] | None = None


class ActivationHooks(Protocol):
    async def activate_target(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        approved_hash: str,
        idempotency_key: str | None,
    ) -> TargetActivationResult:
        ...


class NoopActivationHooks:
    """No runtime side effects; only returns deterministic acquisition evidence."""

    async def activate_target(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        approved_hash: str,
        idempotency_key: str | None,
    ) -> TargetActivationResult:
        return TargetActivationResult(
            success=True,
            activated_resource_ref={
                "kind": "acquisition_noop_activation",
                "target_id": str(target.id),
                "target_type": target.target_type,
                "exposed_to_runtime": False,
            },
            evidence={"hook": "noop", "runtime_side_effects": False},
        )


class ProductionActivationHooks:
    """Production activation owner dispatcher.

    Runtime-specific hooks stay in their runtime packages. This dispatcher is
    the default lifecycle owner and lazily imports them to avoid top-level
    acquisition/runtime circular imports.
    """

    def __init__(self) -> None:
        self._noop = NoopActivationHooks()

    async def activate_target(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        approved_hash: str,
        idempotency_key: str | None,
    ) -> TargetActivationResult:
        if target.target_type == "api_tool":
            from app.core.tools.api_runtime.activation import APIToolActivationHooks

            return await APIToolActivationHooks().activate_target(
                db,
                proposal=proposal,
                target=target,
                approved_hash=approved_hash,
                idempotency_key=idempotency_key,
            )
        if target.target_type == "browser_automation":
            from app.core.browser_automation.activation import BrowserAutomationActivationHooks

            return await BrowserAutomationActivationHooks().activate_target(
                db,
                proposal=proposal,
                target=target,
                approved_hash=approved_hash,
                idempotency_key=idempotency_key,
            )
        if target.target_type in {"worker", "skill", "memory"}:
            from app.core.acquisition.v2_targets import V2CapabilityActivationHooks

            return await V2CapabilityActivationHooks().activate_target(
                db,
                proposal=proposal,
                target=target,
                approved_hash=approved_hash,
                idempotency_key=idempotency_key,
            )
        if target.target_type == "development_patch_proposal":
            return TargetActivationResult(
                success=False,
                error_code="DEVELOPMENT_PATCH_NOT_RUNTIME_TARGET",
                error_message="Development patch proposals are durable handoffs, not runtime activation targets",
                evidence={"hook": "development_patch_guard", "runtime_side_effects": False},
            )
        return await self._noop.activate_target(
            db,
            proposal=proposal,
            target=target,
            approved_hash=approved_hash,
            idempotency_key=idempotency_key,
        )


def default_activation_hooks() -> ActivationHooks:
    """Return production activation hooks for default lifecycle calls."""

    return ProductionActivationHooks()


def approved_snapshot_hash(proposal: AcquisitionProposal) -> str | None:
    for item in reversed(proposal.approval_history or []):
        if isinstance(item, dict) and item.get("status") == "activation_approved":
            value = item.get("approved_snapshot_hash")
            return str(value) if value else None
    return None


def _idempotency_conflict(*, scope: str, idempotency_key: str, approved_hash: str) -> None:
    raise api_error(
        409,
        "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST",
        "Idempotency key was reused with a different acquisition request",
        {"scope": scope, "idempotency_key": idempotency_key, "approved_snapshot_hash": approved_hash},
    )


def _approval_request(
    *,
    idempotency_key: str | None,
    approved_hash: str,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "idempotency_key": idempotency_key,
        "approved_snapshot_hash": approved_hash,
        "reason": reason,
    }


def _activation_start_request(
    *,
    idempotency_key: str | None,
    approved_hash: str,
    verification_id: uuid.UUID | None,
    target_ids: list[uuid.UUID] | None,
) -> dict[str, Any]:
    return {
        "idempotency_key": idempotency_key,
        "approved_snapshot_hash": approved_hash,
        "verification_id": str(verification_id) if verification_id else None,
        # Preserve request order: activation targets are not declared unordered.
        "target_ids": [str(target_id) for target_id in target_ids] if target_ids is not None else None,
    }


def _base_activation_approval_key(idempotency_key: str | None) -> str | None:
    if not idempotency_key:
        return None
    suffix = ":activation-approved"
    if idempotency_key.endswith(suffix):
        return idempotency_key[: -len(suffix)]
    return idempotency_key


def _approval_replay_entry(
    proposal: AcquisitionProposal,
    idempotency_key: str | None,
) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    accepted_keys = {idempotency_key, f"{idempotency_key}:activation-approved"}
    for item in reversed(proposal.approval_history or []):
        if (
            isinstance(item, dict)
            and item.get("status") == "activation_approved"
            and item.get("idempotency_key") in accepted_keys
        ):
            return item
    return None


def _approval_replay_matches(
    item: dict[str, Any],
    *,
    idempotency_key: str | None,
    approved_hash: str,
    reason: str | None,
) -> bool:
    request = item.get("activation_approval_request")
    if not isinstance(request, dict):
        request = {
            "idempotency_key": _base_activation_approval_key(item.get("idempotency_key")),
            "approved_snapshot_hash": item.get("approved_snapshot_hash"),
            "reason": item.get("reason"),
        }
    return request == _approval_request(
        idempotency_key=idempotency_key,
        approved_hash=approved_hash,
        reason=reason,
    )


def _transition_replay_entry(
    proposal: AcquisitionProposal,
    *,
    status: str,
    idempotency_key: str | None,
) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    for item in reversed(proposal.approval_history or []):
        if (
            isinstance(item, dict)
            and item.get("status") == status
            and item.get("idempotency_key") == idempotency_key
        ):
            return item
    return None


def _activation_start_replay_matches(
    item: dict[str, Any],
    *,
    idempotency_key: str | None,
    approved_hash: str,
    verification_id: uuid.UUID | None,
    target_ids: list[uuid.UUID] | None,
) -> bool:
    request = item.get("activation_start_request")
    if not isinstance(request, dict):
        request = {
            "idempotency_key": item.get("idempotency_key"),
            "approved_snapshot_hash": item.get("approved_snapshot_hash"),
            "verification_id": item.get("verification_id"),
            "target_ids": item.get("target_ids"),
        }
    return request == _activation_start_request(
        idempotency_key=idempotency_key,
        approved_hash=approved_hash,
        verification_id=verification_id,
        target_ids=target_ids,
    )


async def _latest_passed_verification(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    snapshot_hash_value: str,
) -> AcquisitionVerification | None:
    return (
        await db.execute(
            select(AcquisitionVerification)
            .where(
                AcquisitionVerification.tenant_id == tenant_id,
                AcquisitionVerification.user_id == user_id,
                AcquisitionVerification.proposal_id == proposal_id,
                AcquisitionVerification.status == "passed",
                AcquisitionVerification.verified_snapshot_hash == snapshot_hash_value,
            )
            .order_by(desc(AcquisitionVerification.completed_at), desc(AcquisitionVerification.started_at))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalars().first()


async def approve_activation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    approved_hash: str,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> AcquisitionProposal:
    proposal = await repository.get_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.proposal_kind != "runtime_activation":
        raise api_error(
            409,
            "PROPOSAL_NOT_RUNTIME_ACTIVATION",
            "Development patch proposals cannot be activation-approved",
            {"proposal_kind": proposal.proposal_kind},
        )
    if proposal.status != "verified":
        replay_entry = _approval_replay_entry(proposal, idempotency_key)
        if replay_entry is not None:
            if _approval_replay_matches(
                replay_entry,
                idempotency_key=idempotency_key,
                approved_hash=approved_hash,
                reason=reason,
            ):
                return proposal
            _idempotency_conflict(
                scope="proposal:activation_approval",
                idempotency_key=idempotency_key or "",
                approved_hash=approved_hash,
            )
        raise api_error(
            409,
            "VERIFICATION_REQUIRED_BEFORE_ACTIVATION_APPROVAL",
            "Activation approval requires a verified proposal snapshot",
            {"status": proposal.status},
        )
    if not proposal.activation_snapshot_hash:
        raise api_error(
            409,
            "VERIFIED_SNAPSHOT_HASH_REQUIRED",
            "Activation approval requires verification to produce a snapshot hash",
            {"proposal_id": str(proposal.id)},
        )
    if proposal.activation_snapshot_hash != approved_hash:
        raise api_error(
            409,
            "APPROVED_SNAPSHOT_HASH_MISMATCH",
            "Activation approval must approve the exact verified snapshot hash",
            {"verified_snapshot_hash": proposal.activation_snapshot_hash, "approved_snapshot_hash": approved_hash},
        )
    verification = await _latest_passed_verification(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        snapshot_hash_value=approved_hash,
    )
    if verification is None:
        raise api_error(
            409,
            "VERIFICATION_EVIDENCE_NOT_FOUND",
            "Activation approval requires passed verification evidence for the approved hash",
            {"approved_snapshot_hash": approved_hash},
        )
    if snapshot_hash(verification.verified_snapshot_payload) != approved_hash:
        await _mark_verification_stale(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal=proposal,
            reason="Stored verification evidence no longer hashes to the approved snapshot hash",
        )
        raise api_error(409, "VERIFICATION_STALE", "Stored verification snapshot evidence is stale")
    credential_generations = await _credential_generations(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal=proposal,
    )
    current_payload = build_activation_snapshot_payload(
        proposal=proposal,
        verification=verification,
        credential_generations=credential_generations,
    )
    current_hash = snapshot_hash(current_payload)
    if current_hash != approved_hash:
        await _mark_verification_stale(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal=proposal,
            reason="Current activation snapshot differs from verified snapshot during approval",
        )
        raise api_error(
            409,
            "VERIFICATION_STALE",
            "Activation snapshot drifted after verification; re-verification is required before approval",
            {
                "approved_snapshot_hash": approved_hash,
                "current_snapshot_hash": current_hash,
            },
        )
    await repository.transition_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        status="activation_requested",
        actor_user_id=user_id,
        idempotency_key=f"{idempotency_key}:activation-requested" if idempotency_key else None,
    )
    proposal, _ = await repository.transition_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        status="activation_approved",
        actor_user_id=user_id,
        reason=reason,
        idempotency_key=f"{idempotency_key}:activation-approved" if idempotency_key else None,
        guarded_transition=True,
    )
    history = list(proposal.approval_history or [])
    if history:
        history[-1] = {
            **history[-1],
            "approved_snapshot_hash": approved_hash,
            "verification_id": str(verification.id),
            "activation_approval_request": _approval_request(
                idempotency_key=idempotency_key,
                approved_hash=approved_hash,
                reason=reason,
            ),
        }
        proposal.approval_history = validate_bounded_json(history[-50:], field="approval_history")
    await db.flush()
    return proposal


async def _mark_verification_stale(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal: AcquisitionProposal,
    reason: str,
) -> None:
    await repository.transition_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal.id,
        status="verification_stale",
        actor_user_id=user_id,
        reason=reason,
    )


async def start_activation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    approved_hash: str,
    verification_id: uuid.UUID | None = None,
    target_ids: list[uuid.UUID] | None = None,
    idempotency_key: str | None = None,
) -> AcquisitionProposal:
    proposal = await repository.get_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.proposal_kind != "runtime_activation":
        raise api_error(
            409,
            "PROPOSAL_NOT_RUNTIME_ACTIVATION",
            "Development patch proposals cannot start runtime activation",
            {"proposal_kind": proposal.proposal_kind},
    )
    if proposal.status != "activation_approved":
        replay_entry = _transition_replay_entry(proposal, status="activating", idempotency_key=idempotency_key)
        if replay_entry is not None:
            if _activation_start_replay_matches(
                replay_entry,
                idempotency_key=idempotency_key,
                approved_hash=approved_hash,
                verification_id=verification_id,
                target_ids=target_ids,
            ):
                return proposal
            _idempotency_conflict(
                scope="proposal:activation_start",
                idempotency_key=idempotency_key or "",
                approved_hash=approved_hash,
            )
        raise api_error(
            409,
            "PROPOSAL_NOT_ACTIVATION_APPROVED",
            "Proposal must be activation_approved before activation starts",
            {"status": proposal.status},
        )
    bound_hash = approved_snapshot_hash(proposal)
    if not bound_hash or bound_hash != approved_hash:
        raise api_error(
            409,
            "APPROVED_SNAPSHOT_HASH_MISMATCH",
            "Activation start requires the user-approved snapshot hash",
            {"approved_snapshot_hash": approved_hash, "bound_snapshot_hash": bound_hash},
        )
    if not proposal.activation_snapshot_hash or proposal.activation_snapshot_hash != approved_hash:
        raise api_error(
            409,
            "VERIFIED_SNAPSHOT_HASH_REQUIRED",
            "Activation start requires the current verified snapshot hash to match approval",
            {"activation_snapshot_hash": proposal.activation_snapshot_hash, "approved_snapshot_hash": approved_hash},
        )

    verification_query = select(AcquisitionVerification).where(
        AcquisitionVerification.tenant_id == tenant_id,
        AcquisitionVerification.user_id == user_id,
        AcquisitionVerification.proposal_id == proposal_id,
        AcquisitionVerification.status == "passed",
        AcquisitionVerification.verified_snapshot_hash == approved_hash,
    )
    if verification_id is not None:
        verification_query = verification_query.where(AcquisitionVerification.id == verification_id)
    else:
        verification_query = verification_query.order_by(
            desc(AcquisitionVerification.completed_at), desc(AcquisitionVerification.started_at)
        )
    verification_query = verification_query.with_for_update().execution_options(populate_existing=True)
    verification = (await db.execute(verification_query)).scalars().first()
    if verification is None:
        raise api_error(
            409,
            "VERIFICATION_EVIDENCE_NOT_FOUND",
            "Activation start requires passed verification evidence for the approved hash",
            {"approved_snapshot_hash": approved_hash, "verification_id": str(verification_id) if verification_id else None},
        )
    if snapshot_hash(verification.verified_snapshot_payload) != verification.verified_snapshot_hash:
        await _mark_verification_stale(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal=proposal,
            reason="Stored verification evidence no longer hashes to its verified snapshot hash",
        )
        raise api_error(409, "VERIFICATION_STALE", "Stored verification snapshot evidence is stale")

    credential_generations = await _credential_generations(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal=proposal,
    )
    current_payload = build_activation_snapshot_payload(
        proposal=proposal,
        verification=verification,
        credential_generations=credential_generations,
    )
    current_hash = snapshot_hash(current_payload)
    if current_hash != approved_hash:
        await _mark_verification_stale(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal=proposal,
            reason="Current activation snapshot differs from approved verification snapshot",
        )
        raise api_error(
            409,
            "VERIFICATION_STALE",
            "Activation snapshot drifted after approval; re-verification and new approval are required",
            {
                "approved_snapshot_hash": approved_hash,
                "current_snapshot_hash": current_hash,
                "target_ids": [str(target_id) for target_id in (target_ids or [])],
            },
        )

    proposal, _ = await repository.transition_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        status="activating",
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        guarded_transition=True,
    )
    history = list(proposal.approval_history or [])
    if history:
        history[-1] = {
            **history[-1],
            "approved_snapshot_hash": approved_hash,
            "verification_id": str(verification.id),
            "target_ids": [str(target_id) for target_id in target_ids] if target_ids is not None else None,
            "activation_start_request": _activation_start_request(
                idempotency_key=idempotency_key,
                approved_hash=approved_hash,
                verification_id=verification_id,
                target_ids=target_ids,
            ),
        }
        proposal.approval_history = validate_bounded_json(history[-50:], field="approval_history")
    await db.flush()
    return proposal


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _target_key(*, role: str, order: int, payload: dict[str, Any]) -> str:
    return str(
        payload.get("activation_target_key")
        or payload.get("target_id")
        or f"{role}:{order}:{payload.get('target_type')}:{payload.get('target_name')}"
    )


def _target_phase(target: ActivationTarget) -> tuple[str, int]:
    result = target.activation_result if isinstance(target.activation_result, dict) else {}
    role = str(result.get("role") or "secondary")
    try:
        order = int(result.get("order", 0))
    except (TypeError, ValueError):
        order = 0
    return role, order


def _activation_order(targets: list[ActivationTarget]) -> list[ActivationTarget]:
    return sorted(targets, key=lambda target: (0 if _target_phase(target)[0] == "primary" else 1, _target_phase(target)[1], target.target_name, str(target.id)))


async def _audit_activation(
    db: AsyncSession,
    *,
    action: str,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    details: dict[str, Any],
) -> None:
    await add_audit_log(
        db,
        AuditRecord(
            action=action,
            method="SYSTEM",
            path="/internal/acquisition/activation",
            status_code=200,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="acquisition_proposal",
            resource_id=str(proposal_id),
            details=details,
        ),
    )


async def _ensure_activation_targets(
    db: AsyncSession,
    *,
    proposal: AcquisitionProposal,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[ActivationTarget]:
    existing = list(
        (
            await db.execute(
                select(ActivationTarget)
                .where(
                    ActivationTarget.tenant_id == tenant_id,
                    ActivationTarget.user_id == user_id,
                    ActivationTarget.proposal_id == proposal.id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    by_key = {
        str((target.activation_result or {}).get("target_key")): target
        for target in existing
        if isinstance(target.activation_result, dict) and (target.activation_result or {}).get("target_key")
    }

    target_specs: list[tuple[str, int, dict[str, Any]]] = []
    if isinstance(proposal.primary_target, dict):
        target_specs.append(("primary", 0, proposal.primary_target))
    for index, secondary in enumerate(proposal.secondary_targets or [], start=1):
        if isinstance(secondary, dict):
            target_specs.append(("secondary", index, secondary))

    for role, order, payload in target_specs:
        key = _target_key(role=role, order=order, payload=payload)
        bundle_decision = validate_permission_bundle(
            payload.get("permission_bundle"),
            target_type=str(payload.get("target_type")),
        )
        if not bundle_decision.allowed:
            raise api_error(
                409,
                bundle_decision.code,
                bundle_decision.message,
                {
                    "proposal_id": str(proposal.id),
                    "target_key": key,
                    "target_role": role,
                    "target_order": order,
                    "reasons": list(bundle_decision.reasons),
                },
            )
        if key in by_key:
            continue
        target = ActivationTarget(
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            target_type=str(payload.get("target_type")),
            target_name=str(payload.get("target_name")),
            target_owner=str(payload.get("target_owner")),
            target_payload=validate_bounded_json(_jsonable(payload.get("target_payload") or {}), field="target_payload"),
            permission_bundle=validate_bounded_json(
                _jsonable(payload.get("permission_bundle") or {}),
                field="permission_bundle",
            ),
            verification_plan=validate_bounded_json(_jsonable(payload.get("verification_plan") or {}), field="verification_plan"),
            rollback_plan=validate_bounded_json(_jsonable(payload.get("rollback_plan") or {}), field="rollback_plan"),
            activation_status="activation_pending",
            activation_result=validate_bounded_json(
                {
                    "role": role,
                    "order": order,
                    "target_key": key,
                    "phase": "activation_pending",
                },
                field="activation_result",
            ),
        )
        db.add(target)
        existing.append(target)
        by_key[key] = target

    await db.flush()
    return _activation_order(existing)


async def _ensure_standing_permission(
    db: AsyncSession,
    *,
    proposal: AcquisitionProposal,
    target: ActivationTarget,
    approved_hash: str,
) -> None:
    bundle = target.permission_bundle if isinstance(target.permission_bundle, dict) else {}
    duration = bundle.get("duration")
    if duration not in {"until_revoked", "expires_at", "per_worker_run_confirmation"}:
        return
    expires_at = normalize_permission_expires_at(bundle)
    existing = (
        await db.execute(
            select(StandingPermission)
            .where(
                StandingPermission.tenant_id == target.tenant_id,
                StandingPermission.user_id == target.user_id,
                StandingPermission.proposal_id == proposal.id,
                StandingPermission.target_id == target.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    permission = StandingPermission(
        tenant_id=target.tenant_id,
        user_id=target.user_id,
        proposal_id=proposal.id,
        target_id=target.id,
        target_type=target.target_type,
        permission_scope=validate_bounded_json(_jsonable(build_standing_permission_scope(bundle)), field="permission_scope"),
        risk_level=str(bundle.get("risk_level") or proposal.risk_level),
        duration=str(duration),
        expires_at=expires_at,
        approved_snapshot_hash=approved_hash,
        revocation_plan=validate_bounded_json(_jsonable(bundle.get("revocation_plan") or {}), field="revocation_plan"),
        audit_events=validate_bounded_json(
            [
                {
                    "event": "permission_granted_for_activation",
                    "proposal_id": str(proposal.id),
                    "target_id": str(target.id),
                    "recorded_at": _now().isoformat(),
                }
            ],
            field="audit_events",
        ),
    )
    db.add(permission)
    await db.flush()


async def _record_target_activation(
    db: AsyncSession,
    *,
    proposal: AcquisitionProposal,
    target: ActivationTarget,
    result: TargetActivationResult,
    approved_hash: str,
    idempotency_key: str | None,
) -> None:
    now = _now()
    existing = target.activation_result if isinstance(target.activation_result, dict) else {}
    role, order = _target_phase(target)
    base = {
        **existing,
        "role": role,
        "order": order,
        "target_key": existing.get("target_key") or _target_key(
            role=role,
            order=order,
            payload={
                "target_type": target.target_type,
                "target_name": target.target_name,
            },
        ),
        "approved_snapshot_hash": approved_hash,
        "idempotency_key": idempotency_key,
        "activated_at": now.isoformat() if result.success else None,
        "failed_at": None if result.success else now.isoformat(),
        "evidence": result.evidence,
        "runtime_session_ref": result.runtime_session_ref,
    }
    tool_manifest = result.evidence.get("tool_manifest") if isinstance(result.evidence, dict) else None
    if isinstance(tool_manifest, dict):
        base["tool_manifest"] = tool_manifest
    if result.success:
        target.activation_status = "active"
        resource_ref = dict(result.activated_resource_ref or {})
        if result.runtime_session_ref:
            resource_ref["runtime_session_ref"] = result.runtime_session_ref
        target.activated_resource_ref = validate_bounded_json(_jsonable(resource_ref), field="activated_resource_ref")
        target.activation_result = validate_bounded_json({**base, "phase": "active"}, field="activation_result")
        await _ensure_standing_permission(db, proposal=proposal, target=target, approved_hash=approved_hash)
        await _audit_activation(
            db,
            action="acquisition.target.activated",
            tenant_id=target.tenant_id,
            user_id=target.user_id,
            proposal_id=proposal.id,
            details={
                "target_id": str(target.id),
                "target_type": target.target_type,
                "target_name": target.target_name,
                "role": role,
                "approved_snapshot_hash": approved_hash,
                "idempotency_key": idempotency_key,
                "runtime_side_effects": bool(result.evidence.get("runtime_side_effects")),
                "durable_side_effects": bool(result.evidence.get("durable_side_effects")),
            },
        )
    else:
        target.activation_status = "activation_failed"
        target.activated_resource_ref = None
        target.activation_result = validate_bounded_json(
            {
                **base,
                "phase": "activation_failed",
                "error_code": result.error_code or "TARGET_ACTIVATION_FAILED",
                "error_message": result.error_message or "Target activation failed",
            },
            field="activation_result",
        )
        await _audit_activation(
            db,
            action="acquisition.target.activation_failed",
            tenant_id=target.tenant_id,
            user_id=target.user_id,
            proposal_id=proposal.id,
            details={
                "target_id": str(target.id),
                "target_type": target.target_type,
                "target_name": target.target_name,
                "role": role,
                "error_code": result.error_code,
                "idempotency_key": idempotency_key,
            },
        )


async def run_activation_saga(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    approved_hash: str,
    verification_id: uuid.UUID | None = None,
    target_ids: list[uuid.UUID] | None = None,
    idempotency_key: str | None = None,
    hooks: ActivationHooks | None = None,
) -> AcquisitionProposal:
    """Run the W2.3 activation saga after preserving W2.2 start guards."""

    proposal = await repository.get_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.status in {"activated", "partial_activation", "activation_failed"}:
        return proposal
    if proposal.status == "activation_approved":
        proposal = await start_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            verification_id=verification_id,
            target_ids=target_ids,
            idempotency_key=f"{idempotency_key}:start" if idempotency_key else None,
        )
    if proposal.status != "activating":
        raise api_error(
            409,
            "PROPOSAL_NOT_ACTIVATING",
            "Activation saga must start from the guarded activating state",
            {"status": proposal.status},
        )

    activation_hooks = hooks or default_activation_hooks()
    all_targets = await _ensure_activation_targets(db, proposal=proposal, tenant_id=tenant_id, user_id=user_id)
    targets = all_targets
    requested_ids = set(target_ids or [])
    if requested_ids:
        targets = [target for target in targets if target.id in requested_ids]
    if not targets:
        raise api_error(
            409,
            "ACTIVATION_TARGETS_REQUIRED",
            "Activation saga requires at least one activation target",
            {"proposal_id": str(proposal.id)},
        )
    has_selected_secondary = any(_target_phase(target)[0] == "secondary" for target in targets)
    has_selected_primary = any(_target_phase(target)[0] == "primary" for target in targets)
    has_active_primary = any(
        _target_phase(target)[0] == "primary" and target.activation_status == "active"
        for target in all_targets
    )
    if has_selected_secondary and not (has_selected_primary or has_active_primary):
        raise api_error(
            409,
            "PRIMARY_TARGET_REQUIRED_FOR_SECONDARY_ACTIVATION",
            "Secondary target activation requires the primary target to be selected or already active",
            {
                "proposal_id": str(proposal.id),
                "target_ids": [str(target_id) for target_id in (target_ids or [])],
                "primary_target_ids": [
                    str(target.id) for target in all_targets if _target_phase(target)[0] == "primary"
                ],
            },
        )

    primary_failed = False
    secondary_failed = False
    target_results: list[dict[str, Any]] = []
    for target in targets:
        role, _ = _target_phase(target)
        if primary_failed:
            break
        if target.activation_status == "active":
            result = target.activation_result if isinstance(target.activation_result, dict) else {}
            evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
            target_results.append(
                {
                    "target_id": str(target.id),
                    "status": "active",
                    "role": role,
                    "replayed": True,
                    "runtime_side_effects": bool(evidence.get("runtime_side_effects")),
                    "durable_side_effects": bool(evidence.get("durable_side_effects")),
                }
            )
            continue
        try:
            result = await activation_hooks.activate_target(
                db,
                proposal=proposal,
                target=target,
                approved_hash=approved_hash,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # pragma: no cover - exercised through tests with explicit failure results.
            result = TargetActivationResult(
                success=False,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                evidence={"hook_exception": exc.__class__.__name__},
            )
        await _record_target_activation(
            db,
            proposal=proposal,
            target=target,
            result=result,
            approved_hash=approved_hash,
            idempotency_key=idempotency_key,
        )
        target_results.append(
            {
                "target_id": str(target.id),
                "status": "active" if result.success else "activation_failed",
                "role": role,
                "error_code": result.error_code,
                "runtime_side_effects": bool(result.evidence.get("runtime_side_effects")),
                "durable_side_effects": bool(result.evidence.get("durable_side_effects")),
            }
        )
        if not result.success and role == "primary":
            primary_failed = True
        elif not result.success:
            secondary_failed = True

    if primary_failed:
        proposal, _ = await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            status="activation_failed",
            actor_user_id=user_id,
            reason="Primary target activation failed",
            idempotency_key=f"{idempotency_key}:failed" if idempotency_key else None,
        )
        final_status = "activation_failed"
        audit_action = "acquisition.activation.failed"
    elif secondary_failed:
        proposal, _ = await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            status="partial_activation",
            actor_user_id=user_id,
            reason="Secondary target activation failed after primary activation",
            idempotency_key=f"{idempotency_key}:partial" if idempotency_key else None,
        )
        final_status = "partial_activation"
        audit_action = "acquisition.activation.partial"
    elif any(target.activation_status != "active" for target in all_targets):
        final_status = "activating"
        audit_action = "acquisition.activation.incomplete"
    else:
        proposal, _ = await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            status="activated",
            actor_user_id=user_id,
            reason="Activation saga completed",
            idempotency_key=f"{idempotency_key}:activated" if idempotency_key else None,
            guarded_transition=True,
        )
        final_status = "activated"
        audit_action = "acquisition.activation.activated"

    history = list(proposal.approval_history or [])
    if history:
        history[-1] = {
            **history[-1],
            "activation_saga": {
                "approved_snapshot_hash": approved_hash,
                "status": final_status,
                "target_results": target_results,
                "idempotency_key": idempotency_key,
                "runtime_side_effects": any(bool(item.get("runtime_side_effects")) for item in target_results),
                "durable_side_effects": any(bool(item.get("durable_side_effects")) for item in target_results),
            },
        }
        proposal.approval_history = validate_bounded_json(history[-50:], field="approval_history")
    await _audit_activation(
        db,
        action=audit_action,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal.id,
        details={
            "approved_snapshot_hash": approved_hash,
            "status": final_status,
            "target_results": target_results,
            "idempotency_key": idempotency_key,
            "runtime_side_effects": any(bool(item.get("runtime_side_effects")) for item in target_results),
            "durable_side_effects": any(bool(item.get("durable_side_effects")) for item in target_results),
        },
    )
    await db.flush()
    return proposal
