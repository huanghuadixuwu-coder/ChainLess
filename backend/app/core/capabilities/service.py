"""Thin Capability Candidate CRUD service with no Agent side effects."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found, validation_error
from app.api.deps import _async_session_factory
from app.core.capabilities.analyzer import AnalyzerCandidate, analyze_run_for_candidates
from app.core.capabilities.bounds import validate_bounded_json
from app.core.capabilities.hooks import emit_capability_hook
from app.core.capabilities.outbox import (
    claim_pending_analysis,
    complete_analysis_job,
    enqueue_run_analysis,
    fail_analysis_job,
)
from app.core.capabilities.rules import RunAnalysisSignal, should_analyze_run, signal_from_payload
from app.core.capabilities.schemas import (
    ACTIVE_RETRIEVAL_STATUSES,
    CANDIDATE_TYPES,
    serialize_candidate,
)
from app.core.memory.persistent import create_memory, write_memory_source_safe
from app.core.observability import increment_runtime_metric
from app.core.workers.service import create_candidate_draft
from app.models.capability import CapabilityAnalysisJob, CapabilityCandidate
from app.models.memory import Memory
from app.models.skill import Skill
from app.models.worker import WorkerVersion


logger = logging.getLogger(__name__)

STREAM_TAIL_ANALYSIS_TIMEOUT_S = 1.5
BACKGROUND_ANALYSIS_TIMEOUT_S = 30.0
INBOX_CANDIDATE_STATUSES = {"new", "seen", "snoozed"}
SUPPRESSED_CANDIDATE_STATUSES = {"dismissed", "muted_pattern"}
ACCEPTABLE_CANDIDATE_STATUSES = {"new", "seen", "snoozed"}


def _candidate_scope(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[Any]:
    return [CapabilityCandidate.tenant_id == tenant_id, CapabilityCandidate.user_id == user_id]


async def _flush_or_validation_error(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        message = str(exc)
        if "ck_capability_candidates_" in message:
            raise validation_error("Capability candidate metadata exceeds durable bounds") from exc
        raise


async def create_candidate(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_type: str,
    title: str,
    body: str | None = None,
    source_run_id: str | None = None,
    source_event_id: str | None = None,
    source_message_id: str | None = None,
    source_uri: str | None = None,
    source_kind: str | None = None,
    dedupe_key: str | None = None,
    evidence: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    worker_id: uuid.UUID | None = None,
) -> CapabilityCandidate:
    if candidate_type not in CANDIDATE_TYPES:
        raise validation_error("Invalid capability candidate type")
    bounded_evidence = validate_bounded_json(evidence or {}, field="evidence")
    bounded_payload = validate_bounded_json(payload or {}, field="payload")
    candidate = CapabilityCandidate(
        tenant_id=tenant_id,
        user_id=user_id,
        candidate_type=candidate_type,
        title=title,
        body=body,
        source_run_id=source_run_id,
        source_event_id=source_event_id,
        source_message_id=source_message_id,
        source_uri=source_uri,
        source_kind=source_kind,
        dedupe_key=dedupe_key,
        evidence=bounded_evidence,
        payload=bounded_payload,
        worker_id=worker_id,
    )
    db.add(candidate)
    await _flush_or_validation_error(db)
    await emit_capability_hook(
        "on_capability_candidate_created",
        {
            "candidate_id": str(candidate.id),
            "candidate_type": candidate.candidate_type,
            "tenant_id": str(candidate.tenant_id),
            "user_id": str(candidate.user_id),
            "source_run_id": candidate.source_run_id,
            "worker_id": str(candidate.worker_id) if candidate.worker_id else None,
        },
    )
    return candidate


async def count_candidates(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).select_from(CapabilityCandidate).where(*_candidate_scope(tenant_id, user_id))
            )
        ).scalar()
        or 0
    )


async def list_candidates(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> list[CapabilityCandidate]:
    rows = await db.execute(
        select(CapabilityCandidate)
        .where(*_candidate_scope(tenant_id, user_id))
        .order_by(CapabilityCandidate.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows.scalars())


async def get_candidate(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> CapabilityCandidate:
    candidate = (
        await db.execute(
            select(CapabilityCandidate).where(
                CapabilityCandidate.id == candidate_id,
                *_candidate_scope(tenant_id, user_id),
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise not_found("CAPABILITY_CANDIDATE_NOT_FOUND", "Capability candidate not found")
    return candidate


async def _get_candidate_for_update(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> CapabilityCandidate:
    candidate = (
        await db.execute(
            select(CapabilityCandidate)
            .where(
                CapabilityCandidate.id == candidate_id,
                *_candidate_scope(tenant_id, user_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise not_found("CAPABILITY_CANDIDATE_NOT_FOUND", "Capability candidate not found")
    return candidate


async def transition_candidate(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_id: uuid.UUID,
    status: str,
    snoozed_until: datetime | None = None,
    mute_pattern: str | None = None,
) -> CapabilityCandidate:
    candidate = await get_candidate(db, tenant_id=tenant_id, user_id=user_id, candidate_id=candidate_id)
    now = datetime.now(timezone.utc)
    candidate.status = status
    if status == "accepted":
        candidate.accepted_at = now
        candidate.accepted_by = user_id
    elif status == "dismissed":
        candidate.dismissed_at = now
    elif status == "archived":
        candidate.archived_at = now
    elif status == "snoozed":
        candidate.snoozed_until = snoozed_until
    elif status == "muted_pattern":
        candidate.mute_pattern = mute_pattern
        candidate.muted_at = now
    await db.commit()
    await db.refresh(candidate)
    return candidate


async def accept_candidate(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_id: uuid.UUID,
    edited_proposal: dict[str, Any] | None = None,
) -> CapabilityCandidate:
    candidate = await _get_candidate_for_update(db, tenant_id=tenant_id, user_id=user_id, candidate_id=candidate_id)
    if candidate.status not in ACCEPTABLE_CANDIDATE_STATUSES:
        raise api_error(
            409,
            "CAPABILITY_CANDIDATE_NOT_ACCEPTABLE",
            "Capability candidate cannot be accepted from its current status",
            {"status": candidate.status},
        )

    proposal = validate_bounded_json(edited_proposal or {}, field="edited_proposal")
    source_metadata = _candidate_source_metadata(candidate)
    resource_metadata = validate_bounded_json(
        {
            "source": source_metadata,
            "candidate": {
                "id": str(candidate.id),
                "type": candidate.candidate_type,
                "dedupe_key": candidate.dedupe_key,
            },
        },
        field="metadata",
    )
    memory: Memory | None = None
    try:
        if candidate.candidate_type == "memory":
            memory = await _accept_memory_candidate(
                db,
                candidate=candidate,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal=proposal,
                metadata=resource_metadata,
            )
            target = {"type": "memory", "memory_id": str(memory.id)}
        elif candidate.candidate_type == "skill":
            skill = await _accept_skill_candidate(
                db,
                candidate=candidate,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal=proposal,
                metadata=resource_metadata,
            )
            target = {"type": "skill", "skill_id": str(skill.id)}
        elif candidate.candidate_type == "worker":
            version = await _accept_worker_candidate(
                db,
                candidate=candidate,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal=proposal,
                metadata=resource_metadata,
            )
            target = {
                "type": "worker",
                "worker_id": str(version.worker_id),
                "worker_version_id": str(version.id),
            }
            candidate.worker_id = version.worker_id
        else:
            raise validation_error("Invalid capability candidate type")

        now = datetime.now(timezone.utc)
        candidate.status = "edited_accepted" if proposal else "accepted"
        candidate.accepted_at = now
        candidate.accepted_by = user_id
        candidate.snoozed_until = None
        candidate.metadata_ = validate_bounded_json(
            {
                **(candidate.metadata_ or {}),
                "target": target,
                "acceptance": {
                    "accepted_by": str(user_id),
                    "accepted_at": now.isoformat(),
                    "edited": bool(proposal),
                },
            },
            field="metadata",
        )
        await _flush_or_validation_error(db)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(409, "CAPABILITY_ACCEPTANCE_CONFLICT", "Accepted capability conflicts with an existing resource") from exc

    await db.refresh(candidate)
    if memory is not None:
        await db.refresh(memory)
        if memory.embedding is None and memory.content:
            from app.core.memory.persistent import _enqueue_embedding_safe

            asyncio.ensure_future(_enqueue_embedding_safe(str(memory.id), memory.content))
        asyncio.ensure_future(write_memory_source_safe(memory))
    return candidate


async def _accept_memory_candidate(
    db: AsyncSession,
    *,
    candidate: CapabilityCandidate,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal: dict[str, Any],
    metadata: dict[str, Any],
) -> Memory:
    payload = candidate.payload or {}
    content = _first_text(
        proposal.get("content"),
        proposal.get("body"),
        payload.get("memory_text"),
        payload.get("content"),
        candidate.body,
        candidate.title,
    )
    return await create_memory(
        db=db,
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        memory_type=_first_text(proposal.get("memory_type"), payload.get("memory_type"), payload.get("type"), "user"),
        name=_first_text(proposal.get("name"), proposal.get("title"), payload.get("name"), candidate.title),
        content=content,
        tags=_string_list(proposal.get("tags") if "tags" in proposal else payload.get("tags")),
        description=_first_optional_text(proposal.get("description"), payload.get("description")),
        metadata=metadata,
        commit=False,
        write_source=False,
        compute_inline_embedding=False,
    )


async def _accept_skill_candidate(
    db: AsyncSession,
    *,
    candidate: CapabilityCandidate,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal: dict[str, Any],
    metadata: dict[str, Any],
) -> Skill:
    payload = candidate.payload or {}
    trigger_source = proposal.get("trigger_terms") if "trigger_terms" in proposal else payload.get("trigger_terms")
    skill = Skill(
        tenant_id=tenant_id,
        user_id=user_id,
        scope="private",
        name=_first_text(proposal.get("name"), proposal.get("title"), payload.get("name"), candidate.title),
        description=_first_optional_text(
            proposal.get("description"),
            proposal.get("body"),
            payload.get("description"),
            candidate.body,
        ),
        trigger_terms=_normalize_terms(_string_list(trigger_source)),
        enabled=True,
        metadata_=metadata,
    )
    db.add(skill)
    await db.flush()
    return skill


async def _accept_worker_candidate(
    db: AsyncSession,
    *,
    candidate: CapabilityCandidate,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal: dict[str, Any],
    metadata: dict[str, Any],
) -> WorkerVersion:
    payload = candidate.payload or {}
    _, version = await create_candidate_draft(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        name=_first_text(proposal.get("name"), proposal.get("title"), payload.get("name"), candidate.title),
        description=_first_optional_text(
            proposal.get("description"),
            proposal.get("body"),
            payload.get("description"),
            candidate.body,
        ),
        trigger=_dict_value(proposal.get("trigger") if "trigger" in proposal else payload.get("trigger")),
        policy=_dict_value(proposal.get("policy") if "policy" in proposal else payload.get("policy")),
        definition=_dict_value(
            proposal.get("definition") if "definition" in proposal else payload.get("definition"),
            default={"proposal": candidate.body or candidate.title},
        ),
        verification_plan=_dict_value(
            proposal.get("verification_plan") if "verification_plan" in proposal else payload.get("verification_plan"),
            default={"requires_review": True, "source": "capability_candidate"},
        ),
        metadata=metadata,
        worker_id=candidate.worker_id,
    )
    return version


def _candidate_source_metadata(candidate: CapabilityCandidate) -> dict[str, Any]:
    return {
        "candidate_id": str(candidate.id),
        "candidate_type": candidate.candidate_type,
        "source_run_id": candidate.source_run_id,
        "source_event_id": candidate.source_event_id,
        "source_message_id": candidate.source_message_id,
        "source_uri": candidate.source_uri,
        "source_kind": candidate.source_kind,
        "dedupe_key": candidate.dedupe_key,
    }


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Accepted capability"


def _first_optional_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            cleaned.append(" ".join(item.strip().split()))
    return cleaned


def _normalize_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for term in terms:
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(term)
    return normalized


def _dict_value(value: Any, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return default or {}


async def merge_candidate(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_id: uuid.UUID,
    target_candidate_id: uuid.UUID,
    merge_reason: str | None = None,
) -> CapabilityCandidate:
    candidate = await get_candidate(db, tenant_id=tenant_id, user_id=user_id, candidate_id=candidate_id)
    target = await get_candidate(db, tenant_id=tenant_id, user_id=user_id, candidate_id=target_candidate_id)
    if candidate.id == target.id:
        raise api_error(409, "CANDIDATE_MERGE_SELF", "Candidate cannot merge into itself")
    candidate.status = "merged"
    candidate.merge_target_candidate_id = target.id
    candidate.merge_reason = merge_reason
    candidate.merged_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(candidate)
    return candidate


async def get_active_candidate_for_retrieval(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> CapabilityCandidate | None:
    return (
        await db.execute(
            select(CapabilityCandidate).where(
                CapabilityCandidate.id == candidate_id,
                *_candidate_scope(tenant_id, user_id),
                CapabilityCandidate.status.in_(ACTIVE_RETRIEVAL_STATUSES),
            )
        )
    ).scalar_one_or_none()


async def analyze_run_tail_for_candidates(
    db: AsyncSession,
    *,
    gateway: Any,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    source_run_id: str,
    user_messages: list[str],
    assistant_content: str,
    provider: str = "default",
    tool_events: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    timeout_s: float = STREAM_TAIL_ANALYSIS_TIMEOUT_S,
) -> dict[str, Any] | None:
    """Durably enqueue eligible runs and best-effort analyze before stream end."""

    tenant_uuid = uuid.UUID(str(tenant_id))
    user_uuid = uuid.UUID(str(user_id))
    signal = should_analyze_run(
        user_messages=user_messages,
        assistant_messages=[assistant_content],
        tool_events=tool_events or [],
        artifacts=artifacts or [],
    )
    if not signal.should_analyze:
        return None

    payload = _analysis_payload(
        source_run_id=source_run_id,
        conversation_id=conversation_id,
        user_messages=user_messages,
        assistant_content=assistant_content,
        signal=signal,
        provider=provider,
        tool_events=tool_events or [],
        artifacts=artifacts or [],
    )
    job = await enqueue_run_analysis(
        db,
        tenant_id=tenant_uuid,
        user_id=user_uuid,
        source_run_id=source_run_id,
        source_kind="conversation",
        payload=payload,
    )
    await db.commit()

    try:
        analyzed = await asyncio.wait_for(
            analyze_run_for_candidates(
                gateway,
                provider=provider,
                tenant_id=str(tenant_uuid),
                signal=signal,
                run_payload=payload,
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        increment_runtime_metric("capability_analysis_timeouts")
        logger.info(
            "Capability analysis timed out; pending job preserved",
            extra={"source_run_id": source_run_id, "job_id": str(job.id)},
        )
        return None
    except Exception as exc:
        await _record_analysis_failure(db, job, exc)
        await db.commit()
        return None

    persisted = await _persist_analyzed_candidates(
        db,
        tenant_id=tenant_uuid,
        user_id=user_uuid,
        source_run_id=source_run_id,
        source_uri=f"conversation://{conversation_id}",
        source_kind="conversation",
        candidates=analyzed,
        signal=signal,
    )
    await complete_analysis_job(
        db,
        job,
        result_metadata={
            "candidate_count": len(persisted),
            "analyzer_candidate_count": len(analyzed),
            "source_run_id": source_run_id,
        },
    )
    await db.commit()
    if not persisted:
        return None
    return _candidate_sse_hint(persisted[0])


async def process_pending_capability_analysis(
    ctx: dict[str, Any],
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    limit: int = 10,
    analyzer_timeout_s: float = BACKGROUND_ANALYSIS_TIMEOUT_S,
) -> dict[str, int]:
    """ARQ-compatible background processor for pending analysis jobs."""

    gateway = ctx.get("llm_gateway")
    if gateway is None:
        from app.main import app_state

        gateway = app_state.llm_gateway
    if gateway is None:
        raise RuntimeError("Capability analyzer gateway is unavailable")

    tenant_uuid = uuid.UUID(str(tenant_id)) if tenant_id else None
    user_uuid = uuid.UUID(str(user_id)) if user_id else None
    summary = {"claimed": 0, "succeeded": 0, "failed": 0}

    for _ in range(max(0, limit)):
        async with _async_session_factory() as db:
            job = await claim_pending_analysis(db, tenant_id=tenant_uuid, user_id=user_uuid)
            if job is None:
                await db.rollback()
                break
            await db.commit()
            summary["claimed"] += 1

            try:
                await asyncio.wait_for(
                    _process_claimed_analysis_job(db, job, gateway),
                    timeout=max(0.001, analyzer_timeout_s),
                )
            except asyncio.TimeoutError:
                await _record_analysis_timeout(db, job)
                summary["failed"] += 1
            except Exception as exc:
                await _record_analysis_failure(db, job, exc)
                summary["failed"] += 1
            else:
                summary["succeeded"] += 1
            await db.commit()

    return summary


def as_dict(candidate: CapabilityCandidate) -> dict[str, Any]:
    return serialize_candidate(candidate)


async def _process_claimed_analysis_job(
    db: AsyncSession,
    job: CapabilityAnalysisJob,
    gateway: Any,
) -> None:
    payload = job.payload or {}
    signal = signal_from_payload(payload)
    if not signal.should_analyze:
        await complete_analysis_job(
            db,
            job,
            result_metadata={
                "candidate_count": 0,
                "analyzer_candidate_count": 0,
                "skipped_reason": "rule_signal_absent",
            },
        )
        return

    analyzed = await analyze_run_for_candidates(
        gateway,
        provider=str(payload.get("provider") or "default"),
        tenant_id=str(job.tenant_id),
        signal=signal,
        run_payload=payload,
    )
    persisted = await _persist_analyzed_candidates(
        db,
        tenant_id=job.tenant_id,
        user_id=job.user_id,
        source_run_id=job.source_run_id,
        source_uri=f"conversation://{payload.get('conversation_id')}",
        source_kind=job.source_kind or "conversation",
        candidates=analyzed,
        signal=signal,
    )
    await complete_analysis_job(
        db,
        job,
        result_metadata={
            "candidate_count": len(persisted),
            "analyzer_candidate_count": len(analyzed),
            "source_run_id": job.source_run_id,
        },
    )


async def _persist_analyzed_candidates(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_run_id: str,
    source_uri: str,
    source_kind: str,
    candidates: list[AnalyzerCandidate],
    signal: RunAnalysisSignal,
) -> list[CapabilityCandidate]:
    persisted: list[CapabilityCandidate] = []
    for analyzed in candidates:
        existing = await _find_candidate_by_dedupe(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_type=analyzed.candidate_type,
            dedupe_key=analyzed.dedupe_key,
        )
        if existing is not None and _candidate_suppresses_hint(existing, analyzed):
            increment_runtime_metric("capability_candidate_suppressed")
            continue
        if existing is not None and _candidate_is_future_snoozed(existing):
            increment_runtime_metric("capability_candidate_suppressed")
            continue
        muted_pattern = await _find_matching_muted_pattern(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_type=analyzed.candidate_type,
            analyzed=analyzed,
        )
        if muted_pattern is not None:
            increment_runtime_metric("capability_candidate_suppressed")
            continue
        evidence = _candidate_evidence(
            analyzed,
            signal=signal,
            source_run_id=source_run_id,
            existing=existing,
        )
        payload = _candidate_payload(analyzed)
        if existing is not None and existing.status in INBOX_CANDIDATE_STATUSES:
            if existing.status == "snoozed":
                existing.status = "new"
                existing.snoozed_until = None
            existing.title = analyzed.title
            existing.body = analyzed.body
            existing.source_run_id = source_run_id
            existing.source_uri = source_uri
            existing.source_kind = source_kind
            existing.evidence = validate_bounded_json(evidence, field="evidence")
            existing.payload = validate_bounded_json(payload, field="payload")
            await _flush_or_validation_error(db)
            persisted.append(existing)
            continue
        if existing is not None and existing.status in ACTIVE_RETRIEVAL_STATUSES:
            increment_runtime_metric("capability_candidate_suppressed")
            continue

        created = await create_candidate(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_type=analyzed.candidate_type,
            title=analyzed.title,
            body=analyzed.body,
            source_run_id=source_run_id,
            source_uri=source_uri,
            source_kind=source_kind,
            dedupe_key=analyzed.dedupe_key,
            evidence=evidence,
            payload=payload,
        )
        persisted.append(created)
    return persisted


async def _find_candidate_by_dedupe(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_type: str,
    dedupe_key: str,
) -> CapabilityCandidate | None:
    result = await db.execute(
        select(CapabilityCandidate)
        .where(
            CapabilityCandidate.tenant_id == tenant_id,
            CapabilityCandidate.user_id == user_id,
            CapabilityCandidate.candidate_type == candidate_type,
            CapabilityCandidate.dedupe_key == dedupe_key,
        )
        .order_by(CapabilityCandidate.created_at.desc())
    )
    rows = list(result.scalars())
    for row in rows:
        if row.status != "merged" or row.merge_target_candidate_id is None:
            continue
        target = await _get_merge_target(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_type=candidate_type,
            target_candidate_id=row.merge_target_candidate_id,
        )
        if target is not None:
            return target
    if not rows:
        return None
    return min(rows, key=_dedupe_status_priority)


async def _get_merge_target(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_type: str,
    target_candidate_id: uuid.UUID,
) -> CapabilityCandidate | None:
    return (
        await db.execute(
            select(CapabilityCandidate).where(
                CapabilityCandidate.id == target_candidate_id,
                CapabilityCandidate.tenant_id == tenant_id,
                CapabilityCandidate.user_id == user_id,
                CapabilityCandidate.candidate_type == candidate_type,
            )
        )
    ).scalar_one_or_none()


def _dedupe_status_priority(candidate: CapabilityCandidate) -> tuple[int, float]:
    priority = {
        "accepted": 0,
        "edited_accepted": 0,
        "new": 1,
        "seen": 1,
        "snoozed": 1,
        "dismissed": 2,
        "muted_pattern": 2,
        "archived": 3,
        "merged": 4,
    }.get(candidate.status, 5)
    created_at = candidate.created_at
    if created_at is None:
        created_at = datetime.min.replace(tzinfo=timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (priority, -created_at.timestamp())


async def _find_matching_muted_pattern(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_type: str,
    analyzed: AnalyzerCandidate,
) -> CapabilityCandidate | None:
    muted_candidates = (
        await db.execute(
            select(CapabilityCandidate).where(
                CapabilityCandidate.tenant_id == tenant_id,
                CapabilityCandidate.user_id == user_id,
                CapabilityCandidate.candidate_type == candidate_type,
                CapabilityCandidate.status == "muted_pattern",
            )
        )
    ).scalars()
    for candidate in muted_candidates:
        if _candidate_suppresses_hint(candidate, analyzed):
            return candidate
    return None


def _candidate_suppresses_hint(
    existing: CapabilityCandidate,
    analyzed: AnalyzerCandidate,
) -> bool:
    if existing.status == "dismissed":
        return True
    if existing.status != "muted_pattern":
        return False
    pattern = existing.mute_pattern or existing.dedupe_key or ""
    return bool(
        pattern
        and (
            fnmatch.fnmatch(analyzed.dedupe_key, pattern)
            or fnmatch.fnmatch(analyzed.title, pattern)
        )
    )


def _candidate_is_future_snoozed(candidate: CapabilityCandidate) -> bool:
    if candidate.status != "snoozed" or candidate.snoozed_until is None:
        return False
    snoozed_until = candidate.snoozed_until
    if snoozed_until.tzinfo is None:
        snoozed_until = snoozed_until.replace(tzinfo=timezone.utc)
    return snoozed_until > datetime.now(timezone.utc)


def _analysis_payload(
    *,
    source_run_id: str,
    conversation_id: str,
    user_messages: list[str],
    assistant_content: str,
    signal: RunAnalysisSignal,
    provider: str,
    tool_events: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    return validate_bounded_json(
        {
            "source_run_id": source_run_id,
            "conversation_id": conversation_id,
            "user_messages": [str(message)[-1000:] for message in user_messages[-5:]],
            "assistant_content": assistant_content[-2000:],
            "provider": provider,
            "signal": signal.to_payload(),
            "tool_events": _bounded_event_refs(tool_events),
            "artifacts": _bounded_event_refs(artifacts),
        },
        field="payload",
    )


def _bounded_event_refs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in items[:10]:
        refs.append({str(key)[:80]: str(value)[:240] for key, value in item.items() if value is not None})
    return refs


def _candidate_evidence(
    analyzed: AnalyzerCandidate,
    *,
    signal: RunAnalysisSignal,
    source_run_id: str,
    existing: CapabilityCandidate | None,
) -> dict[str, Any]:
    prior = existing.evidence if existing is not None and isinstance(existing.evidence, dict) else {}
    source_run_ids = list(dict.fromkeys([*(prior.get("source_run_ids") or []), source_run_id]))[-10:]
    source_evidence = list(
        dict.fromkeys([*(prior.get("source_evidence") or []), *analyzed.source_evidence])
    )[-10:]
    return validate_bounded_json(
        {
            "confidence": analyzed.confidence,
            "source_evidence": source_evidence,
            "source_run_ids": source_run_ids,
            "signal_reasons": signal.reasons,
            "user_correction": signal.user_correction,
        },
        field="evidence",
    )


def _candidate_payload(analyzed: AnalyzerCandidate) -> dict[str, Any]:
    return validate_bounded_json(
        {
            **analyzed.payload,
            "analyzer": {
                "confidence": analyzed.confidence,
                "candidate_type": analyzed.candidate_type,
            },
        },
        field="payload",
    )


def _candidate_sse_hint(candidate: CapabilityCandidate) -> dict[str, Any]:
    return {
        "id": str(candidate.id),
        "candidate_type": candidate.candidate_type,
        "status": candidate.status,
        "active": False,
        "title": candidate.title,
        "message": "Inactive capability candidate is ready for review.",
    }


async def _record_analysis_failure(
    db: AsyncSession,
    job: CapabilityAnalysisJob,
    exc: Exception,
) -> None:
    increment_runtime_metric("capability_analysis_failures")
    logger.warning(
        "Capability analysis failed",
        extra={"source_run_id": job.source_run_id, "job_id": str(job.id)},
    )
    await fail_analysis_job(
        db,
        job,
        error_code="ANALYZER_ERROR",
        error_message=str(exc),
        result_metadata={"source_run_id": job.source_run_id},
    )


async def _record_analysis_timeout(
    db: AsyncSession,
    job: CapabilityAnalysisJob,
) -> None:
    increment_runtime_metric("capability_analysis_timeouts")
    increment_runtime_metric("capability_analysis_failures")
    logger.warning(
        "Capability analysis timed out in background worker",
        extra={"source_run_id": job.source_run_id, "job_id": str(job.id)},
    )
    await fail_analysis_job(
        db,
        job,
        error_code="ANALYZER_TIMEOUT",
        error_message="Capability analyzer timed out",
        result_metadata={"source_run_id": job.source_run_id},
    )
