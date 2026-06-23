"""Thin Worker CRUD and activation-gate service."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found, validation_error
from app.core.capabilities.bounds import validate_bounded_json
from app.models.worker import Worker, WorkerMatchFeedback, WorkerRun, WorkerVersion


def _scope(model: type[Worker] | type[WorkerVersion], tenant_id: uuid.UUID, user_id: uuid.UUID) -> list[Any]:
    return [model.tenant_id == tenant_id, model.user_id == user_id]


async def _commit_or_validation_error(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        message = str(exc)
        if any(name in message for name in ("ck_workers_", "ck_worker_versions_", "ck_worker_runs_")):
            raise validation_error("Worker metadata exceeds durable bounds or violates status contract") from exc
        raise


async def _flush_or_validation_error(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        message = str(exc)
        if any(name in message for name in ("ck_workers_", "ck_worker_versions_", "ck_worker_runs_")):
            raise validation_error("Worker metadata exceeds durable bounds or violates status contract") from exc
        raise


def _require_activation_request(worker: Worker, version: WorkerVersion, activation_token: str | None) -> None:
    if (
        not worker.activation_token
        or activation_token != worker.activation_token
        or worker.activation_requested_version_id != version.id
    ):
        raise api_error(409, "WORKER_ACTIVATION_NOT_REQUESTED", "Activation confirmation was not requested")


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return uuid.UUID(str(value))


def _datetime_or_none(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value)


async def _worker_restore_state(db: AsyncSession, worker: Worker, *, mode: str) -> dict[str, Any]:
    version: WorkerVersion | None = None
    if worker.active_version_id is not None:
        version = await db.get(WorkerVersion, worker.active_version_id)
    return {
        "mode": mode,
        "worker_id": str(worker.id),
        "name": worker.name,
        "description": worker.description,
        "status": worker.status,
        "enabled": worker.enabled,
        "trigger": worker.trigger or {},
        "policy": worker.policy or {},
        "active_version_id": str(worker.active_version_id) if worker.active_version_id else None,
        "activation_token": worker.activation_token,
        "activation_requested_version_id": str(worker.activation_requested_version_id)
        if worker.activation_requested_version_id
        else None,
        "activation_requested_at": _dt(worker.activation_requested_at),
        "activation_confirmed_at": _dt(worker.activation_confirmed_at),
        "activation_confirmed_by": str(worker.activation_confirmed_by) if worker.activation_confirmed_by else None,
        "activation_evidence": worker.activation_evidence or {},
        "rollback_reason": worker.rollback_reason,
        "version_status": version.status if version else None,
        "version_activated_at": _dt(version.activated_at) if version else None,
        "version_archived_at": _dt(version.archived_at) if version else None,
    }


def serialize_worker(worker: Worker) -> dict[str, Any]:
    return {
        "id": str(worker.id),
        "tenant_id": str(worker.tenant_id),
        "user_id": str(worker.user_id),
        "name": worker.name,
        "description": worker.description,
        "status": worker.status,
        "enabled": worker.enabled,
        "trigger": worker.trigger or {},
        "policy": worker.policy or {},
        "active_version_id": str(worker.active_version_id) if worker.active_version_id else None,
        "activation_confirmed_by": str(worker.activation_confirmed_by)
        if worker.activation_confirmed_by
        else None,
        "activation_evidence": worker.activation_evidence or {},
        "rollback_reason": worker.rollback_reason,
        "soft_deleted_at": worker.soft_deleted_at.isoformat() if worker.soft_deleted_at else None,
        "created_at": worker.created_at.isoformat(),
        "updated_at": worker.updated_at.isoformat(),
    }


def serialize_version(version: WorkerVersion) -> dict[str, Any]:
    return {
        "id": str(version.id),
        "tenant_id": str(version.tenant_id),
        "user_id": str(version.user_id),
        "worker_id": str(version.worker_id),
        "version": version.version,
        "status": version.status,
        "definition": version.definition or {},
        "verification_plan": version.verification_plan or {},
        "verification_evidence": version.verification_evidence or {},
        "verified_at": version.verified_at.isoformat() if version.verified_at else None,
        "verified_by": str(version.verified_by) if version.verified_by else None,
        "activated_at": version.activated_at.isoformat() if version.activated_at else None,
        "archived_at": version.archived_at.isoformat() if version.archived_at else None,
        "created_at": version.created_at.isoformat(),
        "updated_at": version.updated_at.isoformat(),
    }


def serialize_run(run: WorkerRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "user_id": str(run.user_id),
        "worker_id": str(run.worker_id),
        "version_id": str(run.version_id) if run.version_id else None,
        "source_run_id": run.source_run_id,
        "status": run.status,
        "input_payload": run.input_payload or {},
        "output_payload": run.output_payload or {},
        "error_code": run.error_code,
        "error_message": run.error_message,
        "confirmation_metadata": run.confirmation_metadata or {},
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def serialize_feedback(feedback: WorkerMatchFeedback) -> dict[str, Any]:
    return {
        "id": str(feedback.id),
        "worker_id": str(feedback.worker_id),
        "source_run_id": feedback.source_run_id,
        "feedback": feedback.feedback,
        "reason": feedback.reason,
        "metadata": feedback.metadata_ or {},
        "created_at": feedback.created_at.isoformat(),
        "updated_at": feedback.updated_at.isoformat(),
    }


async def create_worker(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    description: str | None,
    trigger: dict[str, Any],
    policy: dict[str, Any],
) -> Worker:
    bounded_trigger = validate_bounded_json(trigger, field="trigger")
    bounded_policy = validate_bounded_json(policy, field="policy")
    worker = Worker(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        description=description,
        trigger=bounded_trigger,
        policy=bounded_policy,
    )
    db.add(worker)
    await _commit_or_validation_error(db)
    await db.refresh(worker)
    return worker


async def count_workers(db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).select_from(Worker).where(
                    *_scope(Worker, tenant_id, user_id),
                    Worker.soft_deleted_at.is_(None),
                )
            )
        ).scalar()
        or 0
    )


async def list_workers(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> list[Worker]:
    return list(
        (
            await db.execute(
                select(Worker)
                .where(*_scope(Worker, tenant_id, user_id), Worker.soft_deleted_at.is_(None))
                .order_by(Worker.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )


async def get_worker(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    worker_id: uuid.UUID,
) -> Worker:
    worker = (
        await db.execute(
            select(Worker).where(
                Worker.id == worker_id,
                *_scope(Worker, tenant_id, user_id),
                Worker.soft_deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if worker is None:
        raise not_found("WORKER_NOT_FOUND", "Worker not found")
    return worker


async def update_worker(
    db: AsyncSession,
    worker: Worker,
    *,
    name: str | None = None,
    description: str | None = None,
    trigger: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> Worker:
    match_text_changed = False
    if name is not None:
        match_text_changed = match_text_changed or worker.name != name
        worker.name = name
    if description is not None:
        match_text_changed = match_text_changed or worker.description != description
        worker.description = description
    if trigger is not None:
        bounded_trigger = validate_bounded_json(trigger, field="trigger")
        match_text_changed = match_text_changed or worker.trigger != bounded_trigger
        worker.trigger = bounded_trigger
    if policy is not None:
        worker.policy = validate_bounded_json(policy, field="policy")
    if match_text_changed and worker.active_version_id is not None:
        version = await db.get(WorkerVersion, worker.active_version_id)
        if version is not None:
            version.match_embedding = None
    await _commit_or_validation_error(db)
    await db.refresh(worker)
    return worker


async def create_version(
    db: AsyncSession,
    *,
    worker: Worker,
    version: int,
    definition: dict[str, Any],
    verification_plan: dict[str, Any],
) -> WorkerVersion:
    bounded_definition = validate_bounded_json(definition, field="definition")
    bounded_verification_plan = validate_bounded_json(verification_plan, field="verification_plan")
    worker_version = WorkerVersion(
        tenant_id=worker.tenant_id,
        user_id=worker.user_id,
        worker_id=worker.id,
        version=version,
        definition=bounded_definition,
        verification_plan=bounded_verification_plan,
    )
    db.add(worker_version)
    await _commit_or_validation_error(db)
    await db.refresh(worker_version)
    return worker_version


async def create_candidate_draft(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    description: str | None,
    trigger: dict[str, Any],
    policy: dict[str, Any],
    definition: dict[str, Any],
    verification_plan: dict[str, Any],
    metadata: dict[str, Any],
    worker_id: uuid.UUID | None = None,
) -> tuple[Worker, WorkerVersion]:
    bounded_definition = validate_bounded_json(definition, field="definition")
    bounded_verification_plan = validate_bounded_json(verification_plan, field="verification_plan")
    bounded_metadata = validate_bounded_json(metadata, field="metadata")
    if worker_id is None:
        worker = Worker(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            description=description,
            trigger=validate_bounded_json(trigger, field="trigger"),
            policy=validate_bounded_json(policy, field="policy"),
            metadata_=bounded_metadata,
        )
        db.add(worker)
        await db.flush()
        next_version = 1
    else:
        worker = await get_worker(db, tenant_id=tenant_id, user_id=user_id, worker_id=worker_id)
        next_version = int(
            (
                await db.execute(
                    select(func.max(WorkerVersion.version)).where(WorkerVersion.worker_id == worker.id)
                )
            ).scalar()
            or 0
        ) + 1

    version = WorkerVersion(
        tenant_id=tenant_id,
        user_id=user_id,
        worker_id=worker.id,
        version=next_version,
        definition=bounded_definition,
        verification_plan=bounded_verification_plan,
    )
    db.add(version)
    await db.flush()
    return worker, version


async def get_version(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    worker_id: uuid.UUID,
    version_id: uuid.UUID,
) -> WorkerVersion:
    version = (
        await db.execute(
            select(WorkerVersion).where(
                WorkerVersion.id == version_id,
                WorkerVersion.worker_id == worker_id,
                *_scope(WorkerVersion, tenant_id, user_id),
            )
        )
    ).scalar_one_or_none()
    if version is None:
        raise not_found("WORKER_VERSION_NOT_FOUND", "Worker version not found")
    return version


async def list_versions(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    worker_id: uuid.UUID,
) -> list[WorkerVersion]:
    return list(
        (
            await db.execute(
                select(WorkerVersion)
                .where(
                    WorkerVersion.worker_id == worker_id,
                    *_scope(WorkerVersion, tenant_id, user_id),
                )
                .order_by(WorkerVersion.version.desc())
            )
        ).scalars()
    )


async def list_runs(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    worker_id: uuid.UUID,
    limit: int,
) -> list[WorkerRun]:
    return list(
        (
            await db.execute(
                select(WorkerRun)
                .where(
                    WorkerRun.worker_id == worker_id,
                    WorkerRun.tenant_id == tenant_id,
                    WorkerRun.user_id == user_id,
                )
                .order_by(WorkerRun.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def record_match_feedback(
    db: AsyncSession,
    *,
    worker: Worker,
    feedback: str,
    source_run_id: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> WorkerMatchFeedback:
    if feedback not in {"positive", "negative", "accepted", "rejected", "success", "failure"}:
        raise validation_error("Invalid Worker feedback")
    row = WorkerMatchFeedback(
        tenant_id=worker.tenant_id,
        user_id=worker.user_id,
        worker_id=worker.id,
        source_run_id=source_run_id,
        feedback=feedback,
        reason=reason,
        metadata_=validate_bounded_json(metadata or {}, field="metadata"),
    )
    db.add(row)
    await _commit_or_validation_error(db)
    await db.refresh(row)
    return row


async def verify_version(
    db: AsyncSession,
    *,
    version: WorkerVersion,
    verified_by: uuid.UUID,
    verification_evidence: dict[str, Any],
) -> WorkerVersion:
    if not verification_evidence:
        raise validation_error("verification_evidence is required")
    bounded_evidence = validate_bounded_json(verification_evidence, field="verification_evidence")
    version.status = "verified"
    version.verification_evidence = bounded_evidence
    version.verified_by = verified_by
    version.verified_at = datetime.now(timezone.utc)
    await _commit_or_validation_error(db)
    await db.refresh(version)
    return version


def _require_verified(version: WorkerVersion) -> None:
    if version.status not in {"verified", "active"}:
        raise api_error(409, "WORKER_VERSION_NOT_VERIFIED", "Worker version must be verified before activation")


async def request_activation(db: AsyncSession, *, worker: Worker, version: WorkerVersion) -> dict[str, Any]:
    _require_verified(version)
    token = secrets.token_urlsafe(32)
    worker.activation_token = token
    worker.activation_requested_version_id = version.id
    worker.activation_requested_at = datetime.now(timezone.utc)
    await _commit_or_validation_error(db)
    await db.refresh(worker)
    return {
        "worker_id": str(worker.id),
        "version_id": str(version.id),
        "requires_confirmation": True,
        "activation_token": token,
    }


async def activate_after_confirmation(
    db: AsyncSession,
    *,
    worker: Worker,
    version: WorkerVersion,
    user_id: uuid.UUID,
    activation_token: str,
    confirmation_evidence: dict[str, Any] | None,
) -> Worker:
    _require_verified(version)
    _require_activation_request(worker, version, activation_token)
    if not confirmation_evidence:
        raise validation_error("confirmation_evidence is required")
    bounded_evidence = validate_bounded_json(confirmation_evidence, field="confirmation_evidence")
    now = datetime.now(timezone.utc)
    worker.status = "active"
    worker.enabled = True
    worker.active_version_id = version.id
    worker.activation_token = None
    worker.activation_requested_version_id = None
    worker.activation_confirmed_at = now
    worker.activation_confirmed_by = user_id
    worker.activation_evidence = bounded_evidence
    version.status = "active"
    version.activated_at = now
    await _commit_or_validation_error(db)
    await db.refresh(worker)
    return worker


async def disable_worker(db: AsyncSession, worker: Worker) -> Worker:
    worker.status = "disabled"
    worker.enabled = False
    await _commit_or_validation_error(db)
    await db.refresh(worker)
    return worker


async def enable_worker(db: AsyncSession, worker: Worker) -> Worker:
    if worker.active_version_id is None:
        raise api_error(409, "WORKER_VERSION_NOT_ACTIVE", "Worker has no active version")
    worker.status = "active"
    worker.enabled = True
    await _commit_or_validation_error(db)
    await db.refresh(worker)
    return worker


async def soft_delete_worker(db: AsyncSession, worker: Worker) -> Worker:
    worker.status = "soft_deleted"
    worker.enabled = False
    worker.soft_deleted_at = datetime.now(timezone.utc)
    await _commit_or_validation_error(db)
    await db.refresh(worker)
    return worker


async def rollback_worker(
    db: AsyncSession,
    *,
    worker: Worker,
    version: WorkerVersion,
    user_id: uuid.UUID,
    activation_token: str | None,
    reason: str | None,
    confirmation_evidence: dict[str, Any] | None,
) -> Worker:
    _require_verified(version)
    if not confirmation_evidence:
        raise validation_error("confirmation_evidence is required")
    _require_activation_request(worker, version, activation_token)
    bounded_evidence = validate_bounded_json(confirmation_evidence, field="confirmation_evidence")
    now = datetime.now(timezone.utc)
    worker.active_version_id = version.id
    worker.status = "active"
    worker.enabled = True
    worker.rollback_reason = reason
    worker.activation_token = None
    worker.activation_requested_version_id = None
    worker.activation_confirmed_at = now
    worker.activation_confirmed_by = user_id
    worker.activation_evidence = bounded_evidence
    version.status = "active"
    version.activated_at = now
    await _commit_or_validation_error(db)
    await db.refresh(worker)
    return worker


async def activate_worker_from_acquisition(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    description: str | None,
    trigger: dict[str, Any],
    policy: dict[str, Any],
    definition: dict[str, Any],
    verification_plan: dict[str, Any],
    verification_evidence: dict[str, Any],
    activation_evidence: dict[str, Any],
    worker_id: uuid.UUID | None = None,
) -> tuple[Worker, WorkerVersion, dict[str, Any]]:
    """Activate a V3-verified Worker without committing the acquisition saga."""

    if not verification_evidence:
        raise validation_error("verification_evidence is required")
    if not activation_evidence:
        raise validation_error("activation_evidence is required")

    now = datetime.now(timezone.utc)
    bounded_trigger = validate_bounded_json(trigger, field="trigger")
    bounded_policy = validate_bounded_json(policy, field="policy")
    bounded_definition = validate_bounded_json(definition, field="definition")
    bounded_verification_plan = validate_bounded_json(verification_plan, field="verification_plan")
    bounded_verification_evidence = validate_bounded_json(verification_evidence, field="verification_evidence")
    bounded_activation_evidence = validate_bounded_json(activation_evidence, field="activation_evidence")

    if worker_id is None:
        worker = Worker(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            description=description,
            trigger=bounded_trigger,
            policy=bounded_policy,
        )
        db.add(worker)
        await _flush_or_validation_error(db)
        next_version = 1
        restore_state = {"mode": "created"}
    else:
        worker = (
            await db.execute(
                select(Worker)
                .where(
                    Worker.id == worker_id,
                    *_scope(Worker, tenant_id, user_id),
                    Worker.soft_deleted_at.is_(None),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if worker is None:
            raise not_found("WORKER_NOT_FOUND", "Worker not found")
        restore_state = await _worker_restore_state(db, worker, mode="updated")
        worker.name = name
        worker.description = description
        worker.trigger = bounded_trigger
        worker.policy = bounded_policy
        if worker.active_version_id is not None:
            old_version = await db.get(WorkerVersion, worker.active_version_id)
            if old_version is not None and old_version.status == "active":
                old_version.status = "archived"
                old_version.archived_at = now
        next_version = int(
            (
                await db.execute(
                    select(func.max(WorkerVersion.version)).where(WorkerVersion.worker_id == worker.id)
                )
            ).scalar()
            or 0
        ) + 1

    version = WorkerVersion(
        tenant_id=tenant_id,
        user_id=user_id,
        worker_id=worker.id,
        version=next_version,
        status="active",
        definition=bounded_definition,
        verification_plan=bounded_verification_plan,
        verification_evidence=bounded_verification_evidence,
        verified_by=user_id,
        verified_at=now,
        activated_at=now,
    )
    db.add(version)
    await _flush_or_validation_error(db)

    worker.status = "active"
    worker.enabled = True
    worker.active_version_id = version.id
    worker.activation_token = None
    worker.activation_requested_version_id = None
    worker.activation_confirmed_at = now
    worker.activation_confirmed_by = user_id
    worker.activation_evidence = bounded_activation_evidence
    await _flush_or_validation_error(db)
    return worker, version, validate_bounded_json(restore_state, field="worker_restore_state")


async def rollback_worker_from_acquisition(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    worker_id: uuid.UUID,
    version_id: uuid.UUID,
    reason: str | None,
    restore_state: dict[str, Any] | None = None,
) -> Worker:
    """Disable an acquired Worker target without committing the acquisition saga."""

    worker = (
        await db.execute(
            select(Worker)
            .where(
                Worker.id == worker_id,
                *_scope(Worker, tenant_id, user_id),
                Worker.soft_deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise not_found("WORKER_NOT_FOUND", "Worker not found")
    version = (
        await db.execute(
            select(WorkerVersion)
            .where(
                WorkerVersion.id == version_id,
                WorkerVersion.worker_id == worker.id,
                *_scope(WorkerVersion, tenant_id, user_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if version is None:
        raise not_found("WORKER_VERSION_NOT_FOUND", "Worker version not found")
    restore_state = restore_state if isinstance(restore_state, dict) else {}
    if version.status == "active":
        version.status = "archived"
        version.archived_at = datetime.now(timezone.utc)
    if restore_state.get("mode") == "updated":
        previous_version_id = _uuid_or_none(restore_state.get("active_version_id"))
        worker.name = str(restore_state.get("name") or worker.name)
        worker.description = restore_state.get("description")
        worker.status = str(restore_state.get("status") or "draft")
        worker.enabled = bool(restore_state.get("enabled"))
        worker.trigger = validate_bounded_json(restore_state.get("trigger") or {}, field="trigger")
        worker.policy = validate_bounded_json(restore_state.get("policy") or {}, field="policy")
        worker.active_version_id = previous_version_id
        worker.activation_token = restore_state.get("activation_token")
        worker.activation_requested_version_id = _uuid_or_none(restore_state.get("activation_requested_version_id"))
        worker.activation_requested_at = _datetime_or_none(restore_state.get("activation_requested_at"))
        worker.activation_confirmed_at = _datetime_or_none(restore_state.get("activation_confirmed_at"))
        worker.activation_confirmed_by = _uuid_or_none(restore_state.get("activation_confirmed_by"))
        worker.activation_evidence = validate_bounded_json(
            restore_state.get("activation_evidence") or {},
            field="activation_evidence",
        )
        worker.rollback_reason = restore_state.get("rollback_reason")
        if previous_version_id is not None and previous_version_id != version.id:
            previous_version = await db.get(WorkerVersion, previous_version_id)
            if previous_version is not None:
                previous_version.status = str(restore_state.get("version_status") or previous_version.status)
                previous_version.activated_at = _datetime_or_none(restore_state.get("version_activated_at"))
                previous_version.archived_at = _datetime_or_none(restore_state.get("version_archived_at"))
    else:
        worker.status = "disabled"
        worker.enabled = False
        worker.rollback_reason = reason
    await _flush_or_validation_error(db)
    return worker
