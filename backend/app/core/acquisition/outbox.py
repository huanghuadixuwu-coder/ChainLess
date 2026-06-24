"""Durable bounded outbox for V3 acquisition analysis."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import validation_error
from app.core.capabilities.bounds import truncate_error_message, validate_bounded_json
from app.core.observability import increment_acquisition_metric
from app.models.acquisition import AcquisitionAnalysisJob

DEFAULT_BATCH_LIMIT = 10
MAX_BATCH_LIMIT = 50
DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 30

AnalysisHandler = Callable[[AsyncSession, AcquisitionAnalysisJob], dict[str, Any] | Awaitable[dict[str, Any]]]


class AcquisitionAnalysisLeaseLost(RuntimeError):
    """Raised when a stale worker attempts to finish a reclaimed outbox lease."""


async def _execute_or_validation_error(db: AsyncSession, stmt):
    try:
        return await db.execute(stmt)
    except IntegrityError as exc:
        await db.rollback()
        if "ck_acquisition_analysis_jobs_" in str(exc):
            raise validation_error("Acquisition analysis metadata exceeds durable bounds") from exc
        raise


async def _flush_or_validation_error(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "ck_acquisition_analysis_jobs_" in str(exc):
            raise validation_error("Acquisition analysis metadata exceeds durable bounds") from exc
        raise


def _bounded_batch_limit(batch_limit: int | None) -> int:
    if batch_limit is None:
        return DEFAULT_BATCH_LIMIT
    return max(1, min(int(batch_limit), MAX_BATCH_LIMIT))


async def enqueue_analysis_job(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_run_id: str,
    source_kind: str | None,
    payload: dict[str, Any],
) -> AcquisitionAnalysisJob:
    """Idempotently enqueue one acquisition analysis job for a runtime run."""

    bounded_payload = validate_bounded_json(payload, field="payload")
    stmt = (
        insert(AcquisitionAnalysisJob)
        .values(
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=source_run_id,
            source_kind=source_kind,
            payload=bounded_payload,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "user_id", "source_run_id"],
        )
        .returning(AcquisitionAnalysisJob.id)
    )
    job_id = (await _execute_or_validation_error(db, stmt)).scalar_one_or_none()
    if job_id is None:
        increment_acquisition_metric("acquisition_analysis_duplicate_enqueues")
        job_id = (
            await db.execute(
                select(AcquisitionAnalysisJob.id).where(
                    AcquisitionAnalysisJob.tenant_id == tenant_id,
                    AcquisitionAnalysisJob.user_id == user_id,
                    AcquisitionAnalysisJob.source_run_id == source_run_id,
                )
            )
        ).scalar_one()
    else:
        increment_acquisition_metric("acquisition_analysis_jobs_enqueued")
    job = (
        await db.execute(select(AcquisitionAnalysisJob).where(AcquisitionAnalysisJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:  # pragma: no cover - PostgreSQL RETURNING should resolve.
        raise RuntimeError("Acquisition analysis job enqueue returned no row")
    return job


async def enqueue_run_analysis(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_run_id: str,
    source_kind: str | None,
    payload: dict[str, Any],
) -> AcquisitionAnalysisJob:
    """Facade-friendly alias for enqueueing a run-level analysis job."""

    return await enqueue_analysis_job(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        source_run_id=source_run_id,
        source_kind=source_kind,
        payload=payload,
    )


async def claim_pending_analysis_jobs(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    batch_limit: int | None = None,
    lease_seconds: int = 300,
    retry_seconds: int = 60,
    max_attempts: int = 3,
) -> list[AcquisitionAnalysisJob]:
    """Claim pending, stale-running, or retryable failed jobs with a hard batch cap."""

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(seconds=max(1, lease_seconds))
    retry_cutoff = now - timedelta(seconds=max(0, retry_seconds))
    filters = [
        or_(
            AcquisitionAnalysisJob.status == "pending",
            and_(
                AcquisitionAnalysisJob.status == "running",
                AcquisitionAnalysisJob.claimed_at.is_not(None),
                AcquisitionAnalysisJob.claimed_at < stale_cutoff,
                AcquisitionAnalysisJob.attempts < max(1, max_attempts),
            ),
            and_(
                AcquisitionAnalysisJob.status.in_(("failed", "timed_out")),
                AcquisitionAnalysisJob.attempts < max(1, max_attempts),
                or_(
                    AcquisitionAnalysisJob.completed_at.is_(None),
                    AcquisitionAnalysisJob.completed_at <= retry_cutoff,
                ),
            ),
        )
    ]
    if tenant_id is not None:
        filters.append(AcquisitionAnalysisJob.tenant_id == tenant_id)
    if user_id is not None:
        filters.append(AcquisitionAnalysisJob.user_id == user_id)

    jobs = list(
        (
            await db.execute(
                select(AcquisitionAnalysisJob)
                .where(*filters)
                .order_by(AcquisitionAnalysisJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(_bounded_batch_limit(batch_limit))
            )
        ).scalars()
    )
    stale_count = 0
    retry_count = 0
    for job in jobs:
        if job.status == "running":
            stale_count += 1
        elif job.status in {"failed", "timed_out"}:
            retry_count += 1
        job.status = "running"
        job.attempts += 1
        job.claimed_at = now
        job.completed_at = None
    if jobs:
        await _flush_or_validation_error(db)
        increment_acquisition_metric("acquisition_analysis_jobs_claimed", len(jobs))
    if stale_count:
        increment_acquisition_metric("acquisition_analysis_stale_reclaims", stale_count)
    if retry_count:
        increment_acquisition_metric("acquisition_analysis_retries", retry_count)
    return jobs


async def claim_pending_analysis(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    lease_seconds: int = 300,
    retry_seconds: int = 60,
    max_attempts: int = 3,
) -> AcquisitionAnalysisJob | None:
    jobs = await claim_pending_analysis_jobs(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        batch_limit=1,
        lease_seconds=lease_seconds,
        retry_seconds=retry_seconds,
        max_attempts=max_attempts,
    )
    return jobs[0] if jobs else None


async def process_pending_acquisition_analysis(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    batch_limit: int | None = None,
    lease_seconds: int = 300,
    retry_seconds: int = 60,
    max_attempts: int = 3,
    timeout_seconds: int = DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    handler: AnalysisHandler | None = None,
) -> list[AcquisitionAnalysisJob]:
    """Process claimed jobs with timeout, retry, and idempotent completion evidence."""

    jobs = await claim_pending_analysis_jobs(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        batch_limit=batch_limit,
        lease_seconds=lease_seconds,
        retry_seconds=retry_seconds,
        max_attempts=max_attempts,
    )
    processed: list[AcquisitionAnalysisJob] = []
    for job in jobs:
        try:
            result = await asyncio.wait_for(
                _run_analysis_handler(db, job, handler=handler),
                timeout=max(1, int(timeout_seconds)),
            )
            processed.append(await complete_analysis_job(db, job, result_metadata=result))
        except asyncio.TimeoutError:
            processed.append(
                await fail_analysis_job(
                    db,
                    job,
                    error_code="ANALYZER_TIMEOUT",
                    error_message="acquisition analysis timed out",
                    timed_out=True,
                )
            )
        except AcquisitionAnalysisLeaseLost:
            increment_acquisition_metric("acquisition_analysis_failures")
        except Exception as exc:
            processed.append(
                await fail_analysis_job(
                    db,
                    job,
                    error_code=exc.__class__.__name__[:120],
                    error_message=str(exc),
                )
            )
    return processed


async def _run_analysis_handler(
    db: AsyncSession,
    job: AcquisitionAnalysisJob,
    *,
    handler: AnalysisHandler | None,
) -> dict[str, Any]:
    candidate = handler or _default_analysis_handler
    result = candidate(db, job)
    if inspect.isawaitable(result):
        result = await result
    return validate_bounded_json(dict(result or {}), field="result_metadata")


async def _default_analysis_handler(db: AsyncSession, job: AcquisitionAnalysisJob) -> dict[str, Any]:
    """Default durable analyzer for runtime evidence produced after a chat run."""

    from app.core.planning_issues.service import classify_runtime_issue, create_runtime_planning_issue

    payload = job.payload if isinstance(job.payload, dict) else {}
    issue_payload = payload.get("runtime_planning_issue")
    available_ref = (
        issue_payload.get("available_capability_ref")
        if isinstance(issue_payload, dict)
        else payload.get("available_capability_ref")
    )
    missing_prompt_context = bool(payload.get("missing_prompt_context"))
    classification = classify_runtime_issue(
        failure_reason=str(payload.get("failure_reason") or payload.get("status") or ""),
        available_capability_ref=available_ref if isinstance(available_ref, dict) else None,
        missing_prompt_context=missing_prompt_context,
    )
    if classification.issue_type is None:
        return {
            "processed": True,
            "analysis_result": "no_runtime_planning_issue",
            "classification_reason": classification.reason,
            "source_kind": job.source_kind,
        }

    issue_data = issue_payload if isinstance(issue_payload, dict) else payload
    issue = await create_runtime_planning_issue(
        db,
        tenant_id=job.tenant_id,
        user_id=job.user_id,
        source_run_id=job.source_run_id,
        conversation_id=_parse_uuid(payload.get("conversation_id")),
        issue_type=classification.issue_type,
        available_capability_ref=available_ref if isinstance(available_ref, dict) else {},
        missed_signal=str(issue_data.get("missed_signal") or classification.reason),
        planner_decision_summary=str(
            issue_data.get("planner_decision_summary") or "Agent did not select the available capability."
        ),
        expected_decision_summary=str(
            issue_data.get("expected_decision_summary") or "Planner should use the existing capability or explain why not."
        ),
        severity=classification.severity,
        evidence={
            "source_kind": job.source_kind,
            "payload_status": payload.get("status"),
        },
    )
    return {
        "processed": True,
        "analysis_result": "runtime_planning_issue_created",
        "runtime_planning_issue_id": str(issue.id),
        "issue_type": issue.issue_type,
    }


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def complete_analysis_job(
    db: AsyncSession,
    job: AcquisitionAnalysisJob,
    *,
    result_metadata: dict[str, Any],
) -> AcquisitionAnalysisJob:
    job = await _finish_claimed_job(
        db,
        job,
        status="succeeded",
        result_metadata=validate_bounded_json(result_metadata, field="result_metadata"),
        error_code=None,
        error_message=None,
    )
    increment_acquisition_metric("acquisition_analysis_succeeded")
    return job


async def skip_duplicate_analysis_job(
    db: AsyncSession,
    job: AcquisitionAnalysisJob,
    *,
    result_metadata: dict[str, Any],
) -> AcquisitionAnalysisJob:
    job = await _finish_claimed_job(
        db,
        job,
        status="skipped_duplicate",
        result_metadata=validate_bounded_json(result_metadata, field="result_metadata"),
        error_code=None,
        error_message=None,
    )
    increment_acquisition_metric("acquisition_analysis_duplicate_enqueues")
    return job


async def fail_analysis_job(
    db: AsyncSession,
    job: AcquisitionAnalysisJob,
    *,
    error_code: str,
    error_message: str,
    result_metadata: dict[str, Any] | None = None,
    timed_out: bool = False,
) -> AcquisitionAnalysisJob:
    job = await _finish_claimed_job(
        db,
        job,
        status="timed_out" if timed_out else "failed",
        result_metadata=validate_bounded_json(
            {"attempts": job.attempts, "error_code": error_code, **(result_metadata or {})},
            field="result_metadata",
        ),
        error_code=error_code,
        error_message=truncate_error_message(error_message),
    )
    increment_acquisition_metric("acquisition_analysis_timeouts" if timed_out else "acquisition_analysis_failures")
    return job


async def _finish_claimed_job(
    db: AsyncSession,
    job: AcquisitionAnalysisJob,
    *,
    status: str,
    result_metadata: dict[str, Any],
    error_code: str | None,
    error_message: str | None,
) -> AcquisitionAnalysisJob:
    if job.status != "running" or job.claimed_at is None:
        raise AcquisitionAnalysisLeaseLost("acquisition analysis job is not currently leased")
    stmt = (
        update(AcquisitionAnalysisJob)
        .where(
            AcquisitionAnalysisJob.id == job.id,
            AcquisitionAnalysisJob.status == "running",
            AcquisitionAnalysisJob.attempts == job.attempts,
            AcquisitionAnalysisJob.claimed_at == job.claimed_at,
        )
        .values(
            status=status,
            result_metadata=result_metadata,
            error_code=error_code,
            error_message=error_message,
            completed_at=datetime.now(timezone.utc),
        )
        .returning(AcquisitionAnalysisJob.id)
    )
    updated_id = (await _execute_or_validation_error(db, stmt)).scalar_one_or_none()
    if updated_id is None:
        raise AcquisitionAnalysisLeaseLost("acquisition analysis job lease was reclaimed")
    refreshed = (
        await db.execute(select(AcquisitionAnalysisJob).where(AcquisitionAnalysisJob.id == updated_id))
    ).scalar_one()
    return refreshed
