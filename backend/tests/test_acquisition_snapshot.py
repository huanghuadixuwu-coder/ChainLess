"""Activation snapshot hashing and drift guard tests."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.acquisition import lifecycle, repository
from app.core.acquisition.activation import approve_activation, start_activation
from app.core.acquisition.snapshot import canonical_json, snapshot_hash
from app.core.acquisition.verification import complete_verification_run, verify_proposal
from app.core.credentials.service import revoke_credential_connection, rotate_credential_connection
from app.models.acquisition import (
    AcquisitionProposal,
    AcquisitionVerification,
    CapabilityGap,
    CapabilityRecommendation,
    CredentialConnection,
)
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


def _permission_bundle(*, credential_id: uuid.UUID | None = None, generation: int | None = None) -> dict:
    refs = [credential_id] if credential_id else []
    bundle = {
        "target_type": "api_tool",
        "permission_scope": {"hosts": ["api.weather.example"], "methods": ["GET"]},
        "risk_level": "safe",
        "confirmation_policy": "never_for_safe",
        "credential_scope": "user_provided_token" if credential_id else "none",
        "credential_connection_refs": refs,
        "data_scope": "none",
        "network_scope": "public_web",
        "egress_policy": {"allow_hosts": ["api.weather.example"]},
        "write_scope": "none",
        "execution_scope": "api_tool",
        "duration": "one_run",
        "revocation_plan": {"disable": True},
        "audit_events": [],
    }
    if generation is not None:
        bundle["test_expected_generation"] = generation
    return bundle


def _primary_target(*, credential_id: uuid.UUID | None = None) -> dict:
    return {
        "target_type": "api_tool",
        "target_name": "weather",
        "target_owner": "core.api_tools",
        "target_payload": {"base_url": "https://api.weather.example", "path_template": "/v1/weather"},
        "permission_bundle": _permission_bundle(credential_id=credential_id),
        "verification_plan": {"kind": "contract"},
        "rollback_plan": {"disable": True},
        "activation_status": "draft",
        "activation_result": {},
    }


async def _gap(tenant_id: uuid.UUID, user_id: uuid.UUID, *, dedupe_key: str | None = None) -> CapabilityGap:
    async with _async_session_factory() as db:
        gap = await lifecycle.record_gap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_kind="agent_runtime",
            source_run_id=f"snapshot-test-{uuid.uuid4().hex}",
            dedupe_key=dedupe_key or f"Tool: Weather API {uuid.uuid4().hex}",
            title="Missing weather API",
            description="The task needs a reusable weather API capability.",
            gap_type="missing_api",
            severity="medium",
            evidence={"target": "weather"},
            source_evidence=[{"kind": "tool_error", "message": "TOOL_NOT_FOUND"}],
            idempotency_key=f"gap-{uuid.uuid4().hex}",
        )
        await db.commit()
        return gap


async def _recommendation(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
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
            evidence={"source": "snapshot-test"},
            risk_level="safe",
            expected_value={"reusable": True},
            required_permissions={"network": "public_web"},
            candidate_targets=[{"target_type": "api_tool", "name": "weather"}],
            idempotency_key=f"recommendation-{uuid.uuid4().hex}",
        )
        await db.commit()
        return recommendation


async def _credential(tenant_id: uuid.UUID, user_id: uuid.UUID) -> CredentialConnection:
    async with _async_session_factory() as db:
        credential = CredentialConnection(
            tenant_id=tenant_id,
            user_id=user_id,
            name="Weather API token",
            provider="weather.example",
            connection_type="api_key",
            credential_kind="api_key",
            secret_storage_kind="external_vault_ref",
            secret_ref=f"vault://weather/{uuid.uuid4().hex}",
            secret_generation=1,
            scopes=["weather:read"],
            allowed_target_types=["api_tool"],
            allowed_target_refs=[],
            status="active",
            metadata_redacted={"last4": "1234"},
        )
        db.add(credential)
        await db.commit()
        return credential


async def _proposal(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    credential_id: uuid.UUID | None = None,
) -> AcquisitionProposal:
    gap = await _gap(tenant_id, user_id)
    recommendation = await _recommendation(tenant_id, user_id, gap.id)
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
            evidence={"source": "snapshot-test"},
            risk_level="safe",
            permission_bundle=_permission_bundle(credential_id=credential_id),
            primary_target=_primary_target(credential_id=credential_id),
            verification_plan={"kind": "contract"},
            rollback_plan={"disable": True},
            user_visible_effect="Weather lookups can use a configured API tool.",
            idempotency_key=f"proposal-{uuid.uuid4().hex}",
        )
        await db.commit()
        return proposal


async def _verify(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    *,
    actual_result: dict | None = None,
    artifact_refs: list[dict] | None = None,
):
    async with _async_session_factory() as db:
        verification = await verify_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            verification_kind="contract",
            input_fixture={"city": "London"},
            expected_result={"ok": True},
            actual_result=actual_result or {"ok": True},
            artifact_refs=artifact_refs or [{"artifact_id": "verify-weather", "digest": "sha256:evidence"}],
            idempotency_key=f"verify-{uuid.uuid4().hex}",
        )
        await db.commit()
        return verification


def _error_code(exc: HTTPException) -> str:
    return exc.detail["error"]["code"]


async def test_snapshot_hash_is_stable_for_canonical_json() -> None:
    left = {"b": [3, 1, 2], "a": {"z": "last", "m": "middle"}}
    right = {"a": {"m": "middle", "z": "last"}, "b": [2, 3, 1]}

    assert canonical_json(left) == canonical_json(right)
    assert snapshot_hash(left) == snapshot_hash(right)


async def test_snapshot_hash_changes_when_permission_or_credential_generation_changes() -> None:
    base = {
        "snapshot_schema_version": "v3.activation_snapshot.v1",
        "permission_bundles": [_permission_bundle(generation=1)],
        "credential_generations": [{"credential_connection_id": str(uuid.uuid4()), "secret_generation": 1}],
    }
    permission_drift = {
        **base,
        "permission_bundles": [{**_permission_bundle(generation=1), "write_scope": "external_service"}],
    }
    credential_drift = {
        **base,
        "credential_generations": [
            {**base["credential_generations"][0], "secret_generation": 2},
        ],
    }

    assert snapshot_hash(base) != snapshot_hash(permission_drift)
    assert snapshot_hash(base) != snapshot_hash(credential_drift)


async def test_activation_approval_before_verification_is_forbidden(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await approve_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash="sha256:not-verified",
            )

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "VERIFICATION_REQUIRED_BEFORE_ACTIVATION_APPROVAL"


async def test_completed_verification_exact_replay_returns_current_row(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    actual_result = {"ok": True, "version": 1}
    artifact_refs = [{"artifact_id": "verify-weather", "digest": "sha256:evidence"}]
    verification = await _verify(
        tenant_id,
        user_id,
        proposal.id,
        actual_result=actual_result,
        artifact_refs=artifact_refs,
    )

    async with _async_session_factory() as db:
        replay = await complete_verification_run(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            verification_id=verification.id,
            status="passed",
            actual_result=actual_result,
            artifact_refs=artifact_refs,
            idempotency_key="verification-complete-replay",
        )
        await db.commit()

    assert replay.id == verification.id
    assert replay.verified_snapshot_hash == verification.verified_snapshot_hash
    assert replay.completed_at == verification.completed_at


async def test_completed_verification_different_replay_conflicts(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id, actual_result={"ok": True, "version": 1})

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await complete_verification_run(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                verification_id=verification.id,
                status="passed",
                actual_result={"ok": True, "version": 2},
                artifact_refs=[{"artifact_id": "verify-weather", "digest": "sha256:evidence"}],
                idempotency_key="verification-complete-replay",
            )

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"
    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionVerification).where(AcquisitionVerification.id == verification.id))
        ).scalar_one()
    assert persisted.actual_result == {"ok": True, "version": 1}
    assert persisted.verified_snapshot_hash == verification.verified_snapshot_hash


async def test_activation_approval_idempotent_replay_returns_current_proposal(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id)
    idempotency_key = "approval-replay"

    async with _async_session_factory() as db:
        approved = await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            idempotency_key=idempotency_key,
        )
        await db.commit()

    async with _async_session_factory() as db:
        replay = await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            idempotency_key=idempotency_key,
        )

    assert approved.id == replay.id
    assert replay.status == "activation_approved"


async def test_activation_approval_idempotent_replay_hash_mismatch_conflicts(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id)
    idempotency_key = "approval-replay-mismatch"

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            idempotency_key=idempotency_key,
        )
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await approve_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash="sha256:different",
                idempotency_key=idempotency_key,
            )

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"


async def test_activation_approval_idempotent_replay_reason_mismatch_conflicts(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id)
    idempotency_key = "approval-replay-reason-mismatch"

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            reason="first approval reason",
            idempotency_key=idempotency_key,
        )
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await approve_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=verification.verified_snapshot_hash,
                reason="changed approval reason",
                idempotency_key=idempotency_key,
            )

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"


async def test_activation_approval_rejects_tampered_verification_payload(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        persisted_verification = (
            await db.execute(select(AcquisitionVerification).where(AcquisitionVerification.id == verification.id))
        ).scalar_one()
        persisted_verification.verified_snapshot_payload = {
            **persisted_verification.verified_snapshot_payload,
            "tampered": True,
        }
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await approve_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=verification.verified_snapshot_hash,
            )
        await db.commit()

    assert _error_code(exc.value) == "VERIFICATION_STALE"
    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
    assert persisted.status == "verification_stale"


async def test_activation_approval_denies_permission_drift_after_verification(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        persisted.permission_bundle = {**persisted.permission_bundle, "write_scope": "external_service"}
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await approve_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=verification.verified_snapshot_hash,
            )
        await db.commit()

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "VERIFICATION_STALE"
    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
    assert persisted.status == "verification_stale"


async def test_activation_approval_denies_credential_generation_drift_after_verification(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    credential = await _credential(tenant_id, user_id)
    proposal = await _proposal(tenant_id, user_id, credential_id=credential.id)
    verification = await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        persisted_credential = (
            await db.execute(select(CredentialConnection).where(CredentialConnection.id == credential.id))
        ).scalar_one()
        persisted_credential.secret_generation += 1
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await approve_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=verification.verified_snapshot_hash,
            )
        await db.commit()

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "VERIFICATION_STALE"
    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
    assert persisted.status == "verification_stale"


async def test_rotated_credential_generation_invalidates_activation_snapshot(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    credential = await _credential(tenant_id, user_id)
    proposal = await _proposal(tenant_id, user_id, credential_id=credential.id)
    verification = await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        rotated = await rotate_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            credential_connection_id=credential.id,
            secret_ref=f"vault://weather/rotated/{uuid.uuid4().hex}",
        )
        await db.commit()

    assert rotated.secret_generation == 2
    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        persisted_verification = (
            await db.execute(select(AcquisitionVerification).where(AcquisitionVerification.id == verification.id))
        ).scalar_one()

    assert persisted.status == "verification_stale"
    assert persisted.activation_snapshot_hash is None
    assert persisted.snapshot_created_at is None
    assert persisted_verification.verified_snapshot_hash is None
    assert persisted_verification.verified_snapshot_payload["invalidated_by_credential_connection_id"] == str(
        credential.id
    )


async def test_reverify_after_approval_requires_new_approval_hash(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    first_verification = await _verify(tenant_id, user_id, proposal.id, actual_result={"ok": True, "version": 1})

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=first_verification.verified_snapshot_hash,
        )
        await db.commit()

    second_verification = await _verify(tenant_id, user_id, proposal.id, actual_result={"ok": True, "version": 2})
    assert second_verification.verified_snapshot_hash != first_verification.verified_snapshot_hash

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await approve_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=first_verification.verified_snapshot_hash,
            )

    assert _error_code(exc.value) == "APPROVED_SNAPSHOT_HASH_MISMATCH"


async def test_repository_cannot_enter_activation_approved_without_guard(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            status="activation_requested",
            actor_user_id=user_id,
        )
        with pytest.raises(HTTPException) as exc:
            await repository.transition_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                status="activation_approved",
                actor_user_id=user_id,
            )

    assert _error_code(exc.value) == "GUARDED_PROPOSAL_STATUS_TRANSITION_REQUIRED"


async def test_repository_cannot_enter_activating_or_activated_without_guard(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
        )
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await repository.transition_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                status="activating",
                actor_user_id=user_id,
            )

    assert _error_code(exc.value) == "GUARDED_PROPOSAL_STATUS_TRANSITION_REQUIRED"

    async with _async_session_factory() as db:
        activating = await start_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            verification_id=verification.id,
        )
        await db.commit()

    assert activating.status == "activating"

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await repository.transition_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                status="activated",
                actor_user_id=user_id,
            )

    assert _error_code(exc.value) == "GUARDED_PROPOSAL_STATUS_TRANSITION_REQUIRED"


async def test_activation_start_idempotent_replay_returns_current_proposal(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id)
    start_key = "start-replay"

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
        )
        started = await start_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            verification_id=verification.id,
            idempotency_key=start_key,
        )
        await db.commit()

    async with _async_session_factory() as db:
        replay = await start_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            verification_id=verification.id,
            idempotency_key=start_key,
        )

    assert started.id == replay.id
    assert replay.status == "activating"


async def test_activation_start_idempotent_replay_hash_mismatch_conflicts(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id)
    start_key = "start-replay-mismatch"

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
        )
        await start_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            verification_id=verification.id,
            idempotency_key=start_key,
        )
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await start_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash="sha256:different",
                verification_id=verification.id,
                idempotency_key=start_key,
            )

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"


async def test_activation_start_idempotent_replay_verification_id_mismatch_conflicts(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id)
    start_key = "start-replay-verification-id-mismatch"

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
        )
        await start_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            verification_id=verification.id,
            idempotency_key=start_key,
        )
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await start_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=verification.verified_snapshot_hash,
                verification_id=uuid.uuid4(),
                idempotency_key=start_key,
            )

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"


async def test_activation_start_idempotent_replay_target_ids_order_mismatch_conflicts(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    verification = await _verify(tenant_id, user_id, proposal.id)
    start_key = "start-replay-target-order-mismatch"
    first_target = uuid.uuid4()
    second_target = uuid.uuid4()

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
        )
        await start_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            verification_id=verification.id,
            target_ids=[first_target, second_target],
            idempotency_key=start_key,
        )
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await start_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=verification.verified_snapshot_hash,
                verification_id=verification.id,
                target_ids=[second_target, first_target],
                idempotency_key=start_key,
            )

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"


async def test_runtime_proposal_cannot_transition_verified_to_handoff_ready(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await repository.transition_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                status="handoff_ready",
                actor_user_id=user_id,
            )

    assert _error_code(exc.value) == "INVALID_PROPOSAL_STATUS_TRANSITION"


async def test_activation_denies_stale_snapshot(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    credential = await _credential(tenant_id, user_id)
    proposal = await _proposal(tenant_id, user_id, credential_id=credential.id)
    verification = await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
        )
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        persisted.permission_bundle = {**persisted.permission_bundle, "write_scope": "external_service"}
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await start_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=verification.verified_snapshot_hash,
                verification_id=verification.id,
            )
        await db.commit()

    assert _error_code(exc.value) == "VERIFICATION_STALE"
    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
    assert persisted.status == "verification_stale"


async def test_activation_denies_credential_generation_drift_after_approval(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    credential = await _credential(tenant_id, user_id)
    proposal = await _proposal(tenant_id, user_id, credential_id=credential.id)
    verification = await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
        )
        persisted_credential = (
            await db.execute(select(CredentialConnection).where(CredentialConnection.id == credential.id))
        ).scalar_one()
        persisted_credential.secret_generation += 1
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await start_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=verification.verified_snapshot_hash,
                verification_id=verification.id,
            )
        await db.commit()

    assert _error_code(exc.value) == "VERIFICATION_STALE"
    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
    assert persisted.status == "verification_stale"


async def test_revoked_credential_invalidates_dependent_activation_snapshot(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    credential = await _credential(tenant_id, user_id)
    proposal = await _proposal(tenant_id, user_id, credential_id=credential.id)
    verification = await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
        )
        await revoke_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            credential_connection_id=credential.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        persisted_verification = (
            await db.execute(select(AcquisitionVerification).where(AcquisitionVerification.id == verification.id))
        ).scalar_one()

    assert persisted.status == "verification_stale"
    assert persisted.activation_snapshot_hash is None
    assert persisted.snapshot_created_at is None
    assert persisted_verification.verified_snapshot_hash is None
    assert persisted_verification.verified_snapshot_payload["credential_invalidation_reason"] == "revoked"


async def test_revoked_credential_blocks_fresh_verification_snapshot(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    credential = await _credential(tenant_id, user_id)
    proposal = await _proposal(tenant_id, user_id, credential_id=credential.id)

    async with _async_session_factory() as db:
        await revoke_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            credential_connection_id=credential.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await verify_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                verification_kind="contract",
                input_fixture={"city": "London"},
                expected_result={"ok": True},
                actual_result={"ok": True},
                artifact_refs=[{"artifact_id": "verify-weather", "digest": "sha256:evidence"}],
                idempotency_key=f"verify-{uuid.uuid4().hex}",
            )

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "CREDENTIAL_REFERENCE_NOT_ACTIVE"
    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        verification = (
            await db.execute(
                select(AcquisitionVerification).where(AcquisitionVerification.proposal_id == proposal.id)
            )
        ).scalar_one_or_none()

    assert persisted.status == "drafted"
    assert persisted.activation_snapshot_hash is None
    assert verification is None


async def test_malformed_credential_ref_blocks_fresh_verification_snapshot(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    malformed_ref = "not-a-uuid"

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        persisted.permission_bundle = {
            **persisted.permission_bundle,
            "credential_scope": "user_provided_token",
            "credential_connection_refs": [malformed_ref],
        }
        primary_target = dict(persisted.primary_target)
        primary_target["permission_bundle"] = {
            **primary_target["permission_bundle"],
            "credential_scope": "user_provided_token",
            "credential_connection_refs": [malformed_ref],
        }
        persisted.primary_target = primary_target
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await verify_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                verification_kind="contract",
                input_fixture={"city": "London"},
                expected_result={"ok": True},
                actual_result={"ok": True},
                artifact_refs=[{"artifact_id": "verify-weather", "digest": "sha256:evidence"}],
                idempotency_key=f"verify-{uuid.uuid4().hex}",
            )

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "CREDENTIAL_REFERENCE_NOT_FOUND"
    assert exc.value.detail["error"]["detail"]["credential_connection_refs"] == [malformed_ref]


async def test_non_iterable_credential_refs_block_fresh_verification_snapshot(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    malformed_ref = 123

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        persisted.permission_bundle = {
            **persisted.permission_bundle,
            "credential_scope": "user_provided_token",
            "credential_connection_refs": malformed_ref,
        }
        primary_target = dict(persisted.primary_target)
        primary_target["permission_bundle"] = {
            **primary_target["permission_bundle"],
            "credential_scope": "user_provided_token",
            "credential_connection_refs": malformed_ref,
        }
        persisted.primary_target = primary_target
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await verify_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                verification_kind="contract",
                input_fixture={"city": "London"},
                expected_result={"ok": True},
                actual_result={"ok": True},
                artifact_refs=[{"artifact_id": "verify-weather", "digest": "sha256:evidence"}],
                idempotency_key=f"verify-{uuid.uuid4().hex}",
            )

    assert exc.value.status_code == 409
    assert _error_code(exc.value) == "CREDENTIAL_REFERENCE_NOT_FOUND"
    assert exc.value.detail["error"]["detail"]["credential_connection_refs"] == [str(malformed_ref)]


async def test_activation_denies_credential_ref_drift_after_approval(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    original_credential = await _credential(tenant_id, user_id)
    replacement_credential = await _credential(tenant_id, user_id)
    proposal = await _proposal(tenant_id, user_id, credential_id=original_credential.id)
    verification = await _verify(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
        )
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        replacement_ref = str(replacement_credential.id)
        persisted.permission_bundle = {
            **persisted.permission_bundle,
            "credential_connection_refs": [replacement_ref],
        }
        primary_target = dict(persisted.primary_target)
        primary_target["permission_bundle"] = {
            **primary_target["permission_bundle"],
            "credential_connection_refs": [replacement_ref],
        }
        persisted.primary_target = primary_target
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await start_activation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=verification.verified_snapshot_hash,
                verification_id=verification.id,
            )
        await db.commit()

    assert _error_code(exc.value) == "VERIFICATION_STALE"
    async with _async_session_factory() as db:
        persisted = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
    assert persisted.status == "verification_stale"


async def test_snapshot_payload_keeps_safe_credential_refs_but_not_secret_refs(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    credential = await _credential(tenant_id, user_id)
    proposal = await _proposal(tenant_id, user_id, credential_id=credential.id)
    verification = await _verify(tenant_id, user_id, proposal.id)

    payload = verification.verified_snapshot_payload
    payload_text = json.dumps(payload, sort_keys=True)

    assert payload["credential_generations"] == [
        {
            "credential_connection_id": str(credential.id),
            "secret_generation": 1,
            "status": "active",
        }
    ]
    assert "credential_connection_refs" in payload_text
    assert str(credential.id) in payload_text
    assert "secret_ref" not in payload_text
    assert credential.secret_ref not in payload_text


async def test_snapshot_uses_digest_refs_not_mutable_blob_text(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _proposal(tenant_id, user_id)
    mutable_blob = "mutable raw verification body that must not be stored directly"
    verification = await _verify(
        tenant_id,
        user_id,
        proposal.id,
        actual_result={"ok": True, "blob_text": mutable_blob, "secret_token": "super-secret"},
        artifact_refs=[
            {
                "artifact_id": "verify-weather",
                "digest": "sha256:immutable-evidence",
                "display_url": "https://mutable.example/report",
                "blob_text": mutable_blob,
            }
        ],
    )

    payload_text = json.dumps(verification.verified_snapshot_payload, sort_keys=True)

    assert mutable_blob not in payload_text
    assert "super-secret" not in payload_text
    assert "https://mutable.example/report" not in payload_text
    assert "sha256:immutable-evidence" in payload_text
    assert "actual_result_digest" in payload_text
