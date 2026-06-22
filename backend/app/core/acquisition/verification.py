"""Verification run lifecycle for runtime acquisition activation snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error
from app.core.acquisition import repository
from app.core.acquisition.snapshot import (
    build_activation_snapshot_payload,
    credential_ref_ids_from_bundles,
    permission_bundles_for_proposal,
    snapshot_hash,
)
from app.core.capabilities.bounds import validate_bounded_json
from app.models.acquisition import AcquisitionProposal, AcquisitionVerification, CredentialConnection


def _now() -> datetime:
    return datetime.now(timezone.utc)


COMPLETED_VERIFICATION_STATUSES = {"passed", "failed", "blocked_by_policy", "cancelled", "timed_out"}


def _idempotency_conflict(*, idempotency_key: str | None) -> None:
    if not idempotency_key:
        raise api_error(
            409,
            "VERIFICATION_ALREADY_COMPLETED",
            "Completed verification runs are immutable; create a new verification run to re-verify",
            {"scope": "verification:completion"},
        )
    detail = {"scope": "verification:completion"}
    detail["idempotency_key"] = idempotency_key
    raise api_error(
        409,
        "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST",
        "Idempotency key was reused with a different verification completion request",
        detail,
    )


def _completed_replay_matches(
    verification: AcquisitionVerification,
    *,
    status: str,
    actual_result: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    error_code: str | None,
    error_message: str | None,
) -> bool:
    return (
        verification.status == status
        and verification.actual_result == actual_result
        and verification.artifact_refs == artifact_refs
        and verification.error_code == error_code
        and verification.error_message == error_message
    )


async def _credential_generations(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal: AcquisitionProposal,
) -> list[dict[str, Any]]:
    credential_ids = credential_ref_ids_from_bundles(permission_bundles_for_proposal(proposal))
    if not credential_ids:
        return []
    try:
        parsed_ids = [uuid.UUID(item) for item in credential_ids]
    except (TypeError, ValueError, AttributeError):
        raise api_error(
            409,
            "CREDENTIAL_REFERENCE_NOT_FOUND",
            "Snapshot verification references credentials that are not available to this user",
            {"credential_connection_refs": credential_ids},
        )
    rows = list(
        (
            await db.execute(
                select(CredentialConnection).where(
                    CredentialConnection.tenant_id == tenant_id,
                    CredentialConnection.user_id == user_id,
                    CredentialConnection.id.in_(parsed_ids),
                )
            )
        ).scalars()
    )
    found = {str(row.id): row for row in rows}
    missing = [credential_id for credential_id in credential_ids if credential_id not in found]
    if missing:
        raise api_error(
            409,
            "CREDENTIAL_REFERENCE_NOT_FOUND",
            "Snapshot verification references credentials that are not available to this user",
            {"credential_connection_refs": missing},
        )
    inactive = [
        {
            "credential_connection_id": str(row.id),
            "status": row.status,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        }
        for row in rows
        if row.status != "active" or (row.expires_at is not None and row.expires_at <= _now())
    ]
    if inactive:
        raise api_error(
            409,
            "CREDENTIAL_REFERENCE_NOT_ACTIVE",
            "Snapshot verification references credentials that are not active",
            {"credential_connections": inactive},
        )
    return [
        {
            "credential_connection_id": str(row.id),
            "secret_generation": row.secret_generation,
            "status": row.status,
        }
        for row in sorted(rows, key=lambda item: str(item.id))
    ]


async def create_verification_run(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    verification_kind: str,
    input_fixture: dict[str, Any],
    expected_result: dict[str, Any],
    target_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> AcquisitionVerification:
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
            "Development patch proposals do not create activation verification snapshots",
            {"proposal_kind": proposal.proposal_kind},
        )
    if proposal.status == "drafted":
        await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            status="verification_requested",
            actor_user_id=user_id,
            idempotency_key=f"{idempotency_key}:verification-requested" if idempotency_key else None,
        )
    if proposal.status != "verifying":
        await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            status="verifying",
            actor_user_id=user_id,
            idempotency_key=f"{idempotency_key}:verifying" if idempotency_key else None,
        )
    verification = AcquisitionVerification(
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        target_id=target_id,
        status="running",
        verification_kind=verification_kind,
        input_fixture=validate_bounded_json(input_fixture, field="input_fixture"),
        expected_result=validate_bounded_json(expected_result, field="expected_result"),
        actual_result={},
        artifact_refs=[],
        verified_snapshot_payload={},
        started_at=_now(),
    )
    db.add(verification)
    await db.flush()
    return verification


async def complete_verification_run(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    verification_id: uuid.UUID,
    status: str,
    actual_result: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    idempotency_key: str | None = None,
) -> AcquisitionVerification:
    verification = (
        await db.execute(
            select(AcquisitionVerification)
            .where(
                AcquisitionVerification.id == verification_id,
                AcquisitionVerification.tenant_id == tenant_id,
                AcquisitionVerification.user_id == user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if verification is None:
        raise api_error(404, "VERIFICATION_NOT_FOUND", "Acquisition verification run not found")
    if status not in {"passed", "failed", "blocked_by_policy", "cancelled", "timed_out"}:
        raise api_error(422, "INVALID_VERIFICATION_STATUS", "Invalid verification completion status")
    bounded_actual_result = validate_bounded_json(actual_result or {}, field="actual_result")
    bounded_artifact_refs = validate_bounded_json(artifact_refs or [], field="artifact_refs")
    if verification.status in COMPLETED_VERIFICATION_STATUSES:
        if _completed_replay_matches(
            verification,
            status=status,
            actual_result=bounded_actual_result,
            artifact_refs=bounded_artifact_refs,
            error_code=error_code,
            error_message=error_message,
        ):
            return verification
        _idempotency_conflict(idempotency_key=idempotency_key)
    proposal = await repository.get_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=verification.proposal_id,
        for_update=True,
    )
    verification.status = status
    verification.actual_result = bounded_actual_result
    verification.artifact_refs = bounded_artifact_refs
    verification.error_code = error_code
    verification.error_message = error_message
    verification.completed_at = _now()
    if status != "passed":
        await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            status="verification_failed",
            actor_user_id=user_id,
            reason=error_message,
            idempotency_key=f"{idempotency_key}:verification-failed" if idempotency_key else None,
        )
        await db.flush()
        return verification

    credential_generations = await _credential_generations(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal=proposal,
    )
    payload = build_activation_snapshot_payload(
        proposal=proposal,
        verification=verification,
        credential_generations=credential_generations,
    )
    verified_hash = snapshot_hash(payload)
    verification.verified_snapshot_hash = verified_hash
    verification.verified_snapshot_payload = validate_bounded_json(payload, field="verified_snapshot_payload")
    proposal.activation_snapshot_hash = verified_hash
    proposal.snapshot_created_at = _now()
    if proposal.status != "verified":
        await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            status="verified",
            actor_user_id=user_id,
            idempotency_key=f"{idempotency_key}:verified" if idempotency_key else None,
        )
    await db.flush()
    return verification


async def verify_proposal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    verification_kind: str = "contract",
    input_fixture: dict[str, Any] | None = None,
    expected_result: dict[str, Any] | None = None,
    actual_result: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
    target_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> AcquisitionVerification:
    verification = await create_verification_run(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        target_id=target_id,
        verification_kind=verification_kind,
        input_fixture=input_fixture or {},
        expected_result=expected_result or {},
        idempotency_key=idempotency_key,
    )
    return await complete_verification_run(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        verification_id=verification.id,
        status="passed",
        actual_result=actual_result or {},
        artifact_refs=artifact_refs or [],
        idempotency_key=idempotency_key,
    )
