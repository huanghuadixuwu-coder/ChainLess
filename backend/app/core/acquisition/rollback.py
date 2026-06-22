"""Rollback owner for W2.3 acquisition activation compensation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error
from app.core.audit.service import AuditRecord, add_audit_log
from app.core.acquisition import repository
from app.core.acquisition.tool_manifest import hide_target_manifest_refs
from app.core.capabilities.bounds import validate_bounded_json
from app.models.acquisition import AcquisitionJournalEntry, AcquisitionProposal, ActivationTarget, StandingPermission


ROLLBACKABLE_STATUSES = {"activated", "partial_activation", "activation_failed", "rolled_back"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


@dataclass(frozen=True)
class RollbackHookResult:
    success: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class RollbackResult:
    status: str
    user_visible_recovery_state: str
    target_results: tuple[dict[str, Any], ...]
    changed: bool


class RollbackHooks(Protocol):
    async def terminate_session(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        resource_ref: dict[str, Any],
        idempotency_key: str | None,
    ) -> RollbackHookResult:
        ...

    async def compensate_target(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        resource_ref: dict[str, Any],
        idempotency_key: str | None,
    ) -> RollbackHookResult:
        ...


class NoopRollbackHooks:
    """No runtime side effects; returns compensation evidence for tests and W2.3."""

    async def terminate_session(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        resource_ref: dict[str, Any],
        idempotency_key: str | None,
    ) -> RollbackHookResult:
        return RollbackHookResult(success=True, evidence={"hook": "noop", "session_terminated": True})

    async def compensate_target(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        resource_ref: dict[str, Any],
        idempotency_key: str | None,
    ) -> RollbackHookResult:
        return RollbackHookResult(success=True, evidence={"hook": "noop", "compensated": True})


def _rollback_entry(
    proposal: AcquisitionProposal,
    *,
    idempotency_key: str | None,
) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    for item in reversed(proposal.approval_history or []):
        if (
            isinstance(item, dict)
            and item.get("status") in {"rolled_back", "rollback_failed"}
            and item.get("idempotency_key") == idempotency_key
        ):
            return item
    return None


def _target_phase(target: ActivationTarget) -> tuple[str, int]:
    result = target.activation_result if isinstance(target.activation_result, dict) else {}
    role = str(result.get("role") or "secondary")
    try:
        order = int(result.get("order", 0))
    except (TypeError, ValueError):
        order = 0
    return role, order


def _rollback_order(targets: list[ActivationTarget]) -> list[ActivationTarget]:
    def key(target: ActivationTarget) -> tuple[int, int, str, str]:
        role, order = _target_phase(target)
        return (1 if role == "primary" else 0, -order, target.target_name, str(target.id))

    return sorted(targets, key=key)


async def _audit_rollback(
    db: AsyncSession,
    *,
    action: str,
    proposal: AcquisitionProposal,
    details: dict[str, Any],
) -> None:
    await add_audit_log(
        db,
        AuditRecord(
            action=action,
            method="SYSTEM",
            path="/internal/acquisition/rollback",
            status_code=200,
            tenant_id=proposal.tenant_id,
            user_id=proposal.user_id,
            resource_type="acquisition_proposal",
            resource_id=str(proposal.id),
            details=details,
        ),
    )


async def _write_journal(
    db: AsyncSession,
    *,
    proposal: AcquisitionProposal,
    status: str,
    user_visible_recovery_state: str,
    target_results: list[dict[str, Any]],
    idempotency_key: str | None,
) -> None:
    entry = AcquisitionJournalEntry(
        tenant_id=proposal.tenant_id,
        user_id=proposal.user_id,
        entry_kind="activation_rollback",
        subject_ref=validate_bounded_json(
            {
                "proposal_id": str(proposal.id),
                "status": status,
                "idempotency_key": idempotency_key,
            },
            field="subject_ref",
        ),
        rendered_markdown=(
            f"Activation rollback `{status}` for proposal `{proposal.id}`.\n\n"
            f"Recovery state: {user_visible_recovery_state}"
        ),
        source_refs=validate_bounded_json(
            [{"kind": "activation_target", "target_id": item.get("target_id"), "status": item.get("status")} for item in target_results],
            field="source_refs",
        ),
    )
    db.add(entry)
    await db.flush()


async def _revoke_permissions(
    db: AsyncSession,
    *,
    target: ActivationTarget,
    idempotency_key: str | None,
) -> list[dict[str, Any]]:
    now = _now()
    revoked: list[dict[str, Any]] = []
    rows = list(
        (
            await db.execute(
                select(StandingPermission)
                .where(
                    StandingPermission.tenant_id == target.tenant_id,
                    StandingPermission.user_id == target.user_id,
                    StandingPermission.proposal_id == target.proposal_id,
                    StandingPermission.target_id == target.id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    for permission in rows:
        if permission.status != "revoked":
            permission.status = "revoked"
            permission.revoked_at = now
        events = list(permission.audit_events or [])
        if not any(isinstance(item, dict) and item.get("idempotency_key") == idempotency_key for item in events):
            events.append(
                {
                    "event": "permission_revoked_for_rollback",
                    "target_id": str(target.id),
                    "idempotency_key": idempotency_key,
                    "recorded_at": now.isoformat(),
                }
            )
        permission.audit_events = validate_bounded_json(_jsonable(events[-50:]), field="audit_events")
        revoked.append({"permission_id": str(permission.id), "status": permission.status})
    return revoked


def _resource_ref(target: ActivationTarget) -> dict[str, Any]:
    ref = target.activated_resource_ref if isinstance(target.activated_resource_ref, dict) else {}
    result = target.activation_result if isinstance(target.activation_result, dict) else {}
    if "runtime_session_ref" not in ref and isinstance(result.get("runtime_session_ref"), dict):
        ref = {**ref, "runtime_session_ref": result["runtime_session_ref"]}
    return ref


async def _record_recovery_state(
    db: AsyncSession,
    *,
    proposal: AcquisitionProposal,
    status: str,
    user_visible_recovery_state: str,
    target_results: list[dict[str, Any]],
    idempotency_key: str | None,
) -> None:
    evidence = proposal.evidence if isinstance(proposal.evidence, dict) else {}
    proposal.evidence = validate_bounded_json(
        _jsonable(
            {
                **evidence,
                "rollback": {
                    "status": status,
                    "user_visible_recovery_state": user_visible_recovery_state,
                    "target_results": target_results,
                    "idempotency_key": idempotency_key,
                    "recorded_at": _now().isoformat(),
                },
            }
        ),
        field="evidence",
    )
    await db.flush()


async def rollback_activation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    reason: str | None = None,
    idempotency_key: str | None = None,
    hooks: RollbackHooks | None = None,
) -> RollbackResult:
    proposal = await repository.get_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    replay = _rollback_entry(proposal, idempotency_key=idempotency_key)
    if proposal.status == "rolled_back" or replay is not None:
        evidence = proposal.evidence if isinstance(proposal.evidence, dict) else {}
        rollback_state = evidence.get("rollback") if isinstance(evidence.get("rollback"), dict) else {}
        return RollbackResult(
            status=str(rollback_state.get("status") or "rolled_back"),
            user_visible_recovery_state=str(rollback_state.get("user_visible_recovery_state") or "Rollback already completed."),
            target_results=tuple(rollback_state.get("target_results") or ()),
            changed=False,
        )
    if proposal.status not in ROLLBACKABLE_STATUSES:
        raise api_error(
            409,
            "PROPOSAL_NOT_ROLLBACKABLE",
            "Only activated, partial, failed, or already rolled-back proposals can roll back",
            {"status": proposal.status},
        )

    rollback_hooks = hooks or NoopRollbackHooks()
    targets = list(
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
    target_results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for target in _rollback_order(targets):
        resource_ref = _resource_ref(target)
        manifest = await hide_target_manifest_refs(db, target=target, idempotency_key=idempotency_key)
        result = target.activation_result if isinstance(target.activation_result, dict) else {}
        revoked_permissions = await _revoke_permissions(db, target=target, idempotency_key=idempotency_key)
        try:
            terminate_result = await rollback_hooks.terminate_session(
                db,
                proposal=proposal,
                target=target,
                resource_ref=resource_ref,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # pragma: no cover - explicit failure results are easier to assert.
            terminate_result = RollbackHookResult(False, {"hook_exception": exc.__class__.__name__}, exc.__class__.__name__, str(exc))
        try:
            compensate_result = await rollback_hooks.compensate_target(
                db,
                proposal=proposal,
                target=target,
                resource_ref=resource_ref,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # pragma: no cover
            compensate_result = RollbackHookResult(False, {"hook_exception": exc.__class__.__name__}, exc.__class__.__name__, str(exc))

        target_status = "rolled_back" if terminate_result.success and compensate_result.success else "needs_user_recovery"
        target_result = {
            "target_id": str(target.id),
            "target_type": target.target_type,
            "target_name": target.target_name,
            "status": target_status,
            "manifest": manifest,
            "revoked_permissions": revoked_permissions,
            "terminate_session": terminate_result.evidence,
            "compensation": compensate_result.evidence,
        }
        if target_status == "rolled_back":
            target.activation_status = "rolled_back"
        else:
            failure = {
                "target_id": str(target.id),
                "terminate_error_code": terminate_result.error_code,
                "compensate_error_code": compensate_result.error_code,
                "terminate_error_message": terminate_result.error_message,
                "compensate_error_message": compensate_result.error_message,
            }
            failures.append(failure)
            target_result["failure"] = failure
        target.activation_result = validate_bounded_json(
            _jsonable(
                {
                    **result,
                    "rollback": {
                        "status": target_status,
                        "idempotency_key": idempotency_key,
                        "recorded_at": _now().isoformat(),
                        "manifest": manifest,
                        "revoked_permissions": revoked_permissions,
                    },
                }
            ),
            field="activation_result",
        )
        target_results.append(target_result)

    if failures:
        status = "needs_user_recovery"
        user_visible_recovery_state = (
            "Rollback needs manual recovery for one or more targets. "
            "The tool has been hidden where possible, permissions were revoked where possible, "
            "and runtime compensation failure details are available in rollback evidence."
        )
        await _record_recovery_state(
            db,
            proposal=proposal,
            status=status,
            user_visible_recovery_state=user_visible_recovery_state,
            target_results=target_results,
            idempotency_key=idempotency_key,
        )
        history = list(proposal.approval_history or [])
        history.append(
            {
                "status": "rollback_failed",
                "actor_user_id": str(user_id),
                "reason": reason,
                "idempotency_key": idempotency_key,
                "recorded_at": _now().isoformat(),
                "rollback": {"status": status, "failures": failures},
            }
        )
        proposal.approval_history = validate_bounded_json(_jsonable(history[-50:]), field="approval_history")
        await _write_journal(
            db,
            proposal=proposal,
            status=status,
            user_visible_recovery_state=user_visible_recovery_state,
            target_results=target_results,
            idempotency_key=idempotency_key,
        )
        await _audit_rollback(
            db,
            action="acquisition.rollback.failed",
            proposal=proposal,
            details={"status": status, "failures": failures, "idempotency_key": idempotency_key},
        )
        await db.flush()
        return RollbackResult(status, user_visible_recovery_state, tuple(target_results), changed=True)

    proposal, _ = await repository.transition_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal.id,
        status="rolled_back",
        actor_user_id=user_id,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    status = "rolled_back"
    user_visible_recovery_state = "Rollback completed. Activated tools are hidden, permissions are revoked, and runtime sessions were terminated."
    await _record_recovery_state(
        db,
        proposal=proposal,
        status=status,
        user_visible_recovery_state=user_visible_recovery_state,
        target_results=target_results,
        idempotency_key=idempotency_key,
    )
    await _write_journal(
        db,
        proposal=proposal,
        status=status,
        user_visible_recovery_state=user_visible_recovery_state,
        target_results=target_results,
        idempotency_key=idempotency_key,
    )
    await _audit_rollback(
        db,
        action="acquisition.activation.rolled_back",
        proposal=proposal,
        details={"status": status, "target_results": target_results, "idempotency_key": idempotency_key},
    )
    await db.flush()
    return RollbackResult(status, user_visible_recovery_state, tuple(target_results), changed=True)
