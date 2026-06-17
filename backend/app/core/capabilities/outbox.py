"""Durable candidate-analysis outbox helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import validation_error
from app.core.capabilities.bounds import truncate_error_message, validate_bounded_json
from app.core.observability import increment_runtime_metric
from app.models.capability import CapabilityAnalysisJob


async def _flush_or_validation_error(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "ck_capability_analysis_jobs_" in str(exc):
            raise validation_error("Capability analysis metadata exceeds durable bounds") from exc
        raise


async def _execute_or_validation_error(db: AsyncSession, stmt):
    try:
        return await db.execute(stmt)
    except IntegrityError as exc:
        await db.rollback()
        if "ck_capability_analysis_jobs_" in str(exc):
            raise validation_error("Capability analysis metadata exceeds durable bounds") from exc
        raise


async def enqueue_analysis_job(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_run_id: str,
    source_kind: str | None,
    payload: dict[str, Any],
) -> CapabilityAnalysisJob:
    bounded_payload = validate_bounded_json(payload, field="payload")
    stmt = (
        insert(CapabilityAnalysisJob)
        .values(
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=source_run_id,
            source_kind=source_kind,
            payload=bounded_payload,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "user_id", "source_run_id"],
            # No-op update lets PostgreSQL serialize concurrent enqueues and
            # return the existing row id without a check-then-insert race.
            set_={"source_kind": CapabilityAnalysisJob.source_kind},
        )
        .returning(CapabilityAnalysisJob.id)
    )
    inserted_id = (await _execute_or_validation_error(db, stmt)).scalar_one()
    job = (
        await db.execute(
            select(CapabilityAnalysisJob).where(CapabilityAnalysisJob.id == inserted_id)
        )
    ).scalar_one_or_none()
    if job is None:  # pragma: no cover - RETURNING id should always resolve.
        raise RuntimeError("Capability analysis job enqueue returned no row")
    return job


async def enqueue_run_analysis(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_run_id: str,
    source_kind: str | None,
    payload: dict[str, Any],
) -> CapabilityAnalysisJob:
    """W2 facade name for durable run-analysis enqueue with duplicate evidence."""

    existing = (
        await db.execute(
            select(CapabilityAnalysisJob).where(
                CapabilityAnalysisJob.tenant_id == tenant_id,
                CapabilityAnalysisJob.user_id == user_id,
                CapabilityAnalysisJob.source_run_id == source_run_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        increment_runtime_metric("capability_analysis_duplicate_enqueues")
    return await enqueue_analysis_job(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        source_run_id=source_run_id,
        source_kind=source_kind,
        payload=payload,
    )


async def claim_analysis_job(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> CapabilityAnalysisJob | None:
    job = (
        await db.execute(
            select(CapabilityAnalysisJob)
            .where(
                CapabilityAnalysisJob.tenant_id == tenant_id,
                CapabilityAnalysisJob.user_id == user_id,
                CapabilityAnalysisJob.status == "pending",
            )
            .order_by(CapabilityAnalysisJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.claimed_at = datetime.now(timezone.utc)
    await _flush_or_validation_error(db)
    return job


async def claim_pending_analysis(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    lease_seconds: int = 300,
) -> CapabilityAnalysisJob | None:
    """Claim pending or stale-running analysis work with a bounded lease."""

    stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, lease_seconds))
    filters = [
        or_(
            CapabilityAnalysisJob.status == "pending",
            and_(
                CapabilityAnalysisJob.status == "running",
                CapabilityAnalysisJob.claimed_at.is_not(None),
                CapabilityAnalysisJob.claimed_at < stale_cutoff,
            ),
        )
    ]
    if tenant_id is not None:
        filters.append(CapabilityAnalysisJob.tenant_id == tenant_id)
    if user_id is not None:
        filters.append(CapabilityAnalysisJob.user_id == user_id)
    job = (
        await db.execute(
            select(CapabilityAnalysisJob)
            .where(*filters)
            .order_by(CapabilityAnalysisJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    was_stale_running = job.status == "running"
    job.status = "running"
    job.attempts += 1
    job.claimed_at = datetime.now(timezone.utc)
    await _flush_or_validation_error(db)
    increment_runtime_metric("capability_analysis_jobs_claimed")
    if was_stale_running:
        increment_runtime_metric("capability_analysis_stale_reclaims")
    return job


async def complete_analysis_job(
    db: AsyncSession,
    job: CapabilityAnalysisJob,
    *,
    result_metadata: dict[str, Any],
) -> CapabilityAnalysisJob:
    bounded_result = validate_bounded_json(result_metadata, field="result_metadata")
    job.status = "succeeded"
    job.result_metadata = bounded_result
    job.error_code = None
    job.error_message = None
    job.completed_at = datetime.now(timezone.utc)
    await _flush_or_validation_error(db)
    return job


async def skip_duplicate_analysis_job(
    db: AsyncSession,
    job: CapabilityAnalysisJob,
    *,
    result_metadata: dict[str, Any],
) -> CapabilityAnalysisJob:
    bounded_result = validate_bounded_json(result_metadata, field="result_metadata")
    job.status = "skipped_duplicate"
    job.result_metadata = bounded_result
    job.completed_at = datetime.now(timezone.utc)
    await _flush_or_validation_error(db)
    return job


async def fail_analysis_job(
    db: AsyncSession,
    job: CapabilityAnalysisJob,
    *,
    error_code: str,
    error_message: str,
    result_metadata: dict[str, Any] | None = None,
) -> CapabilityAnalysisJob:
    metadata = {
        "attempts": job.attempts,
        "error_code": error_code,
        **(result_metadata or {}),
    }
    bounded_metadata = validate_bounded_json(metadata, field="result_metadata")
    job.status = "failed"
    job.error_code = error_code
    job.error_message = truncate_error_message(error_message)
    job.result_metadata = bounded_metadata
    job.completed_at = datetime.now(timezone.utc)
    await _flush_or_validation_error(db)
    return job
