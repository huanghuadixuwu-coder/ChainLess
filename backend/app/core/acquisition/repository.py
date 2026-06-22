"""Repository helpers for the V3 acquisition lifecycle owner."""

from __future__ import annotations

import re
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import Select, func, null, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found, validation_error
from app.core.capabilities.bounds import validate_bounded_json
from app.models.acquisition import (
    AcquisitionIdempotencyRecord,
    CapabilityGap,
    CapabilityRecommendation,
    AcquisitionProposal,
    ExplorationRun,
)


ALLOWED_GAP_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "detected": {
        "exploration_recommended",
        "exploration_approved",
        "exploring",
        "explored_success",
        "explored_failed",
        "recommendation_created",
        "dismissed",
        "snoozed",
        "superseded",
        "blocked_by_policy",
    },
    "exploration_recommended": {
        "exploration_approved",
        "exploring",
        "dismissed",
        "snoozed",
        "superseded",
        "blocked_by_policy",
    },
    "exploration_approved": {"exploring", "dismissed", "snoozed", "superseded", "blocked_by_policy"},
    "exploring": {"explored_success", "explored_failed", "dismissed", "snoozed", "superseded", "blocked_by_policy"},
    "explored_success": {"recommendation_created", "dismissed", "snoozed", "superseded"},
    "explored_failed": {
        "exploration_recommended",
        "exploration_approved",
        "exploring",
        "recommendation_created",
        "dismissed",
        "snoozed",
        "superseded",
        "blocked_by_policy",
    },
    "recommendation_created": {"proposal_drafted", "dismissed", "snoozed", "superseded"},
    "proposal_drafted": {"dismissed", "snoozed", "superseded"},
    "dismissed": set(),
    "snoozed": {"exploration_recommended", "exploration_approved", "exploring", "dismissed", "superseded"},
    "superseded": set(),
    "blocked_by_policy": set(),
}

ALLOWED_EXPLORATION_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "cancelled", "blocked_by_policy", "timed_out"},
    "running": {"succeeded", "failed", "blocked_by_policy", "cancelled", "timed_out"},
    "succeeded": set(),
    "failed": set(),
    "blocked_by_policy": set(),
    "cancelled": set(),
    "timed_out": set(),
}

ALLOWED_PROPOSAL_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "drafted": {
        "verification_requested",
        "activation_rejected",
        "dismissed",
        "superseded",
    },
    "verification_requested": {"verifying", "dismissed", "superseded"},
    "verifying": {"verified", "verification_failed", "dismissed", "superseded"},
    "verified": {"activation_requested", "verification_stale", "dismissed", "superseded"},
    "verification_failed": {"verification_requested", "verifying", "dismissed", "superseded"},
    "verification_stale": {"verification_requested", "verifying", "dismissed", "superseded"},
    "activation_requested": {"activation_approved", "activation_rejected", "dismissed", "superseded"},
    "activation_approved": {"activating", "verifying", "verification_stale", "activation_rejected", "dismissed", "superseded"},
    "activating": {"activated", "partial_activation", "activation_failed"},
    "partial_activation": {"activation_failed", "rolled_back"},
    "activated": {"rolled_back"},
    "activation_failed": {"activation_requested", "rolled_back", "dismissed", "superseded"},
    "rolled_back": set(),
    "activation_rejected": set(),
    "handoff_ready": {"handoff_started", "dismissed", "superseded"},
    "handoff_started": {"dismissed", "superseded"},
    "dismissed": set(),
    "superseded": set(),
}
GUARDED_RUNTIME_ACTIVATION_STATUSES = {"activation_approved", "activating", "activated"}
ALLOWED_DEVELOPMENT_PATCH_PROPOSAL_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "drafted": {"verifying", "dismissed", "superseded"},
    "verifying": {"verified", "verification_failed", "dismissed", "superseded"},
    "verified": {"handoff_ready", "dismissed", "superseded"},
    "verification_failed": {"verifying", "dismissed", "superseded"},
    "handoff_ready": {"handoff_started", "dismissed", "superseded"},
    "handoff_started": {"dismissed", "superseded"},
    "dismissed": set(),
    "superseded": set(),
}
IDEMPOTENCY_RESOURCE_MODELS: dict[str, type[Any]] = {
    "capability_gap": CapabilityGap,
    "exploration_run": ExplorationRun,
    "capability_recommendation": CapabilityRecommendation,
    "acquisition_proposal": AcquisitionProposal,
}


def normalize_gap_dedupe_key(value: str, *, source_class: str | None = None) -> str:
    """Normalize user/runtime supplied gap dedupe keys into a stable private key."""

    raw = " ".join(str(value or "").strip().casefold().split())
    if not raw:
        raise validation_error("Gap dedupe key is required")
    parsed = urlparse(raw)
    if parsed.netloc:
        host = parsed.netloc.removeprefix("www.")
        path = parsed.path.rstrip("/")
        raw = f"{host}{path}"
    raw = re.sub(r"[^a-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", "-", raw).strip("-")
    raw = raw[:220] or "unknown"
    if source_class:
        prefix = re.sub(r"[^a-z0-9._-]+", "-", source_class.strip().casefold()).strip("-")
        if prefix and not raw.startswith(f"{prefix}:"):
            raw = f"{prefix}:{raw}"
    return raw[:255]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _with_lifecycle_metadata(
    evidence: dict[str, Any] | None,
    *,
    idempotency_key: str | None,
    existing_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(evidence or {})
    lifecycle = dict(payload.get("lifecycle") or {})
    existing_lifecycle = dict((existing_evidence or {}).get("lifecycle") or {})
    keys = [
        str(item)
        for item in [
            *(existing_lifecycle.get("idempotency_keys") or []),
            *(lifecycle.get("idempotency_keys") or []),
        ]
        if item
    ]
    if idempotency_key and idempotency_key not in keys:
        keys.append(idempotency_key)
    if keys:
        lifecycle["idempotency_keys"] = list(dict.fromkeys(keys))[-20:]
    if lifecycle:
        payload["lifecycle"] = lifecycle
    return validate_bounded_json(_jsonable(payload), field="evidence")


def _bounded_recent_json(items: list[dict[str, Any]], *, field: str) -> Any:
    recent = list(items)
    truncated = 0
    while True:
        payload = (
            [{"kind": "truncation", "omitted_oldest_count": truncated}]
            if truncated
            else []
        ) + recent
        try:
            return validate_bounded_json(_jsonable(payload), field=field)
        except HTTPException:
            if not recent:
                raise
            recent.pop(0)
            truncated += 1


def _merge_source_evidence(
    existing: list[dict[str, Any]] | None,
    occurrence: list[dict[str, Any]] | None,
) -> Any:
    entries = [
        item
        for item in [
            *(existing or []),
            *(occurrence or []),
        ]
        if isinstance(item, dict)
    ]
    return _bounded_recent_json(entries, field="source_evidence")


def _has_idempotency_key(row: Any, idempotency_key: str | None) -> bool:
    if not idempotency_key:
        return False
    evidence = row.evidence if isinstance(row.evidence, dict) else {}
    lifecycle = evidence.get("lifecycle") if isinstance(evidence.get("lifecycle"), dict) else {}
    return idempotency_key in set(lifecycle.get("idempotency_keys") or [])


def _remember_idempotency_key(row: Any, idempotency_key: str | None) -> None:
    if not idempotency_key:
        return
    row.evidence = _with_lifecycle_metadata(
        row.evidence if isinstance(row.evidence, dict) else {},
        idempotency_key=idempotency_key,
        existing_evidence=row.evidence if isinstance(row.evidence, dict) else {},
    )


def _has_tool_event_idempotency_key(row: ExplorationRun, idempotency_key: str | None) -> bool:
    if not idempotency_key:
        return False
    return any(
        isinstance(item, dict) and item.get("idempotency_key") == idempotency_key
        for item in (row.tool_events or [])
    )


def _remember_tool_event_idempotency_key(row: ExplorationRun, idempotency_key: str | None, *, scope: str) -> None:
    if not idempotency_key:
        return
    events = list(row.tool_events or [])
    if not any(isinstance(item, dict) and item.get("idempotency_key") == idempotency_key for item in events):
        events.append(
            {
                "kind": "lifecycle_idempotency",
                "scope": scope,
                "idempotency_key": idempotency_key,
                "recorded_at": _now().isoformat(),
            }
        )
    row.tool_events = validate_bounded_json(_jsonable(events[-50:]), field="tool_events")


def _idempotency_fingerprint(payload: dict[str, Any]) -> str:
    stable_payload = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()


def _idempotency_conflict(
    *,
    scope: str,
    idempotency_key: str,
    existing_resource_type: str | None = None,
    requested_resource_type: str | None = None,
) -> HTTPException:
    return api_error(
        409,
        "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST",
        "Idempotency key was reused with a different acquisition request",
        {
            "scope": scope,
            "idempotency_key": idempotency_key,
            "existing_resource_type": existing_resource_type,
            "requested_resource_type": requested_resource_type,
        },
    )


async def _resource_from_idempotency_record(
    db: AsyncSession,
    *,
    record: AcquisitionIdempotencyRecord,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Any | None:
    metadata = record.metadata_ if isinstance(record.metadata_, dict) else {}
    if metadata.get("status") == "in_progress":
        return None
    model = IDEMPOTENCY_RESOURCE_MODELS[record.resource_type]
    return (
        await db.execute(
            select(model).where(
                model.id == record.resource_id,
                model.tenant_id == tenant_id,
                model.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def _reserve_idempotency(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    scope: str,
    idempotency_key: str | None,
    resource_type: str,
    request: dict[str, Any],
) -> tuple[AcquisitionIdempotencyRecord | None, Any | None]:
    if not idempotency_key:
        return None, None
    fingerprint = _idempotency_fingerprint({"resource_type": resource_type, **request})
    metadata = validate_bounded_json(
        _jsonable(
            {
                "status": "in_progress",
                "request_fingerprint": fingerprint,
                "request": request,
            }
        ),
        field="idempotency_metadata",
    )
    stmt = (
        insert(AcquisitionIdempotencyRecord)
        .values(
            tenant_id=tenant_id,
            user_id=user_id,
            scope=scope,
            idempotency_key=idempotency_key,
            resource_type=resource_type,
            resource_id=uuid.uuid4(),
            metadata_=metadata,
        )
        .on_conflict_do_nothing(constraint="uq_acq_idem_scope_key")
        .returning(AcquisitionIdempotencyRecord.id)
    )
    inserted_id = (await db.execute(stmt)).scalar_one_or_none()
    record = (
        await db.execute(
            select(AcquisitionIdempotencyRecord)
            .where(
                AcquisitionIdempotencyRecord.tenant_id == tenant_id,
                AcquisitionIdempotencyRecord.user_id == user_id,
                AcquisitionIdempotencyRecord.scope == scope,
                AcquisitionIdempotencyRecord.idempotency_key == idempotency_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    existing_metadata = record.metadata_ if isinstance(record.metadata_, dict) else {}
    existing_fingerprint = existing_metadata.get("request_fingerprint")
    if record.resource_type != resource_type or (
        existing_fingerprint is not None and existing_fingerprint != fingerprint
    ):
        raise _idempotency_conflict(
            scope=scope,
            idempotency_key=idempotency_key,
            existing_resource_type=record.resource_type,
            requested_resource_type=resource_type,
        )
    if inserted_id is None:
        resource = await _resource_from_idempotency_record(
            db,
            record=record,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if resource is not None:
            return None, resource
        raise api_error(
            409,
            "IDEMPOTENCY_RECORD_IN_PROGRESS",
            "Idempotency request is still in progress; retry the request",
            {"scope": scope, "idempotency_key": idempotency_key},
        )
    return record, None


async def _complete_idempotency(
    db: AsyncSession,
    record: AcquisitionIdempotencyRecord | None,
    *,
    resource_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    if record is None:
        return
    existing_metadata = record.metadata_ if isinstance(record.metadata_, dict) else {}
    record.resource_id = resource_id
    record.metadata_ = validate_bounded_json(
        _jsonable({**existing_metadata, **(metadata or {}), "status": "completed"}),
        field="idempotency_metadata",
    )
    await _flush_or_validation_error(db)


async def _validate_exploration_parent_scope(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    exploration_run_id: uuid.UUID | None,
) -> None:
    if exploration_run_id is None:
        return
    matched = (
        await db.execute(
            select(ExplorationRun.id).where(
                ExplorationRun.id == exploration_run_id,
                ExplorationRun.tenant_id == tenant_id,
                ExplorationRun.user_id == user_id,
                ExplorationRun.gap_id == gap_id,
            )
        )
    ).scalar_one_or_none()
    if matched is None:
        raise api_error(
            409,
            "EXPLORATION_PARENT_SCOPE_MISMATCH",
            "Exploration run does not belong to this acquisition gap",
            {"gap_id": str(gap_id), "exploration_run_id": str(exploration_run_id)},
        )


async def _validate_recommendation_parent_scope(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    recommendation_id: uuid.UUID,
) -> None:
    matched = (
        await db.execute(
            select(CapabilityRecommendation.id).where(
                CapabilityRecommendation.id == recommendation_id,
                CapabilityRecommendation.tenant_id == tenant_id,
                CapabilityRecommendation.user_id == user_id,
                CapabilityRecommendation.gap_id == gap_id,
            )
        )
    ).scalar_one_or_none()
    if matched is None:
        raise api_error(
            409,
            "RECOMMENDATION_PARENT_SCOPE_MISMATCH",
            "Recommendation does not belong to this acquisition gap",
            {"gap_id": str(gap_id), "recommendation_id": str(recommendation_id)},
        )


def _validate_status_transition(
    *,
    resource: str,
    current_status: str,
    next_status: str,
    allowed: dict[str, set[str]],
) -> None:
    if current_status == next_status:
        return
    if next_status not in allowed.get(current_status, set()):
        raise api_error(
            409,
            f"INVALID_{resource}_STATUS_TRANSITION",
            f"Invalid {resource.lower()} status transition",
            {"current_status": current_status, "next_status": next_status},
        )


async def _flush_or_validation_error(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "ck_capability_" in str(exc) or "ck_acquisition_" in str(exc):
            raise validation_error("Acquisition lifecycle metadata exceeds durable bounds") from exc
        raise


async def _one(db: AsyncSession, query: Select[Any], code: str, message: str) -> Any:
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise not_found(code, message)
    return row


async def count_gaps(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(CapabilityGap)
                .where(CapabilityGap.tenant_id == tenant_id, CapabilityGap.user_id == user_id)
            )
        ).scalar()
        or 0
    )


async def get_gap(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    for_update: bool = False,
) -> CapabilityGap:
    query = select(CapabilityGap).where(
        CapabilityGap.id == gap_id,
        CapabilityGap.tenant_id == tenant_id,
        CapabilityGap.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await _one(db, query, "CAPABILITY_GAP_NOT_FOUND", "Capability gap not found")


async def create_or_increment_gap(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_kind: str,
    source_run_id: str,
    conversation_id: uuid.UUID | None,
    dedupe_key: str,
    title: str,
    description: str,
    gap_type: str,
    severity: str,
    source_evidence: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
    source_class: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[CapabilityGap, bool, bool]:
    """Create a deduped gap or increment its occurrence count under a row lock."""

    normalized_key = normalize_gap_dedupe_key(dedupe_key, source_class=source_class)
    reservation, existing_idempotent = await _reserve_idempotency(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        scope="gap:create",
        idempotency_key=idempotency_key,
        resource_type="capability_gap",
        request={"gap_type": gap_type, "dedupe_key": normalized_key},
    )
    if existing_idempotent is not None:
        return existing_idempotent, False, False

    now = _now()
    bounded_source_evidence = validate_bounded_json(_jsonable(source_evidence or []), field="source_evidence")
    bounded_evidence = _with_lifecycle_metadata(evidence or {}, idempotency_key=idempotency_key)
    stmt = (
        insert(CapabilityGap)
        .values(
            tenant_id=tenant_id,
            user_id=user_id,
            source_kind=source_kind,
            source_run_id=source_run_id,
            conversation_id=conversation_id,
            dedupe_key=normalized_key,
            title=title,
            description=description,
            gap_type=gap_type,
            severity=severity,
            status="detected",
            source_evidence=bounded_source_evidence,
            evidence=bounded_evidence,
            first_seen_at=now,
            last_seen_at=now,
            occurrence_count=1,
        )
        .on_conflict_do_nothing(
            constraint="uq_capability_gaps_user_gap_dedupe",
        )
        .returning(CapabilityGap.id)
    )
    inserted_id = (await db.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        gap = await get_gap(db, tenant_id=tenant_id, user_id=user_id, gap_id=inserted_id)
        await _complete_idempotency(
            db,
            reservation,
            resource_id=gap.id,
            metadata={"dedupe_key": normalized_key, "created": True},
        )
        return gap, True, True

    gap = (
        await db.execute(
            select(CapabilityGap)
            .where(
                CapabilityGap.tenant_id == tenant_id,
                CapabilityGap.user_id == user_id,
                CapabilityGap.gap_type == gap_type,
                CapabilityGap.dedupe_key == normalized_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if _has_idempotency_key(gap, idempotency_key):
        await _complete_idempotency(
            db,
            reservation,
            resource_id=gap.id,
            metadata={"dedupe_key": normalized_key, "legacy_json_replay": True},
        )
        return gap, False, False
    gap.occurrence_count += 1
    gap.last_seen_at = now
    gap.source_kind = source_kind
    gap.source_run_id = source_run_id
    gap.conversation_id = conversation_id
    gap.source_evidence = _merge_source_evidence(gap.source_evidence, bounded_source_evidence)
    gap.evidence = _with_lifecycle_metadata(
        {
            **(gap.evidence if isinstance(gap.evidence, dict) else {}),
            **(evidence or {}),
        },
        idempotency_key=idempotency_key,
        existing_evidence=gap.evidence if isinstance(gap.evidence, dict) else {},
    )
    await _flush_or_validation_error(db)
    await _complete_idempotency(
        db,
        reservation,
        resource_id=gap.id,
        metadata={"dedupe_key": normalized_key, "created": False},
    )
    return gap, False, True


async def transition_gap(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    status: str,
    idempotency_key: str | None = None,
) -> tuple[CapabilityGap, bool]:
    reservation, existing_idempotent = await _reserve_idempotency(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        scope="gap:transition",
        idempotency_key=idempotency_key,
        resource_type="capability_gap",
        request={"gap_id": str(gap_id), "status": status},
    )
    if existing_idempotent is not None:
        return existing_idempotent, False
    gap = await get_gap(db, tenant_id=tenant_id, user_id=user_id, gap_id=gap_id, for_update=True)
    if gap.status == status or _has_idempotency_key(gap, idempotency_key):
        await _complete_idempotency(
            db,
            reservation,
            resource_id=gap.id,
            metadata={"status": status, "changed": False},
        )
        return gap, False
    _validate_status_transition(
        resource="GAP",
        current_status=gap.status,
        next_status=status,
        allowed=ALLOWED_GAP_STATUS_TRANSITIONS,
    )
    gap.status = status
    _remember_idempotency_key(gap, idempotency_key)
    await _flush_or_validation_error(db)
    await _complete_idempotency(
        db,
        reservation,
        resource_id=gap.id,
        metadata={"status": status, "changed": True},
    )
    return gap, True


async def get_exploration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    exploration_id: uuid.UUID,
    for_update: bool = False,
) -> ExplorationRun:
    query = select(ExplorationRun).where(
        ExplorationRun.id == exploration_id,
        ExplorationRun.tenant_id == tenant_id,
        ExplorationRun.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await _one(
        db,
        query,
        "EXPLORATION_NOT_FOUND",
        "Exploration run not found",
    )


async def create_exploration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    source_run_id: str,
    risk_level: str,
    strategy: str,
    status: str = "queued",
    approval_id: uuid.UUID | None = None,
    tool_events: list[dict[str, Any]] | None = None,
    idempotency_key: str | None = None,
) -> tuple[ExplorationRun, bool]:
    events = list(tool_events or [])
    reservation, existing_idempotent = await _reserve_idempotency(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        scope="exploration:create",
        idempotency_key=idempotency_key,
        resource_type="exploration_run",
        request={
            "gap_id": str(gap_id),
            "risk_level": risk_level,
            "strategy": strategy,
            "status": status,
            "approval_id": str(approval_id) if approval_id else None,
            "tool_events": events,
        },
    )
    if existing_idempotent is not None:
        return existing_idempotent, False
    await get_gap(db, tenant_id=tenant_id, user_id=user_id, gap_id=gap_id, for_update=True)
    if idempotency_key:
        existing_result = await db.execute(
            select(ExplorationRun).where(
                ExplorationRun.tenant_id == tenant_id,
                ExplorationRun.user_id == user_id,
                ExplorationRun.gap_id == gap_id,
            )
        )
        existing_rows = list(existing_result.scalars())
        for existing in existing_rows:
            if _has_tool_event_idempotency_key(existing, idempotency_key):
                await _complete_idempotency(
                    db,
                    reservation,
                    resource_id=existing.id,
                    metadata={"gap_id": str(gap_id), "legacy_json_replay": True},
                )
                return existing, False
    if idempotency_key:
        events.append({"kind": "lifecycle_idempotency", "idempotency_key": idempotency_key})
    exploration = ExplorationRun(
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        source_run_id=source_run_id,
        risk_level=risk_level,
        approval_id=approval_id,
        status=status,
        strategy=strategy,
        tool_events=validate_bounded_json(_jsonable(events), field="tool_events"),
        started_at=_now() if status == "running" else None,
    )
    db.add(exploration)
    await _flush_or_validation_error(db)
    await _complete_idempotency(
        db,
        reservation,
        resource_id=exploration.id,
        metadata={"gap_id": str(gap_id), "status": status},
    )
    return exploration, True


async def transition_exploration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    exploration_id: uuid.UUID,
    status: str,
    result_summary: str | None = None,
    failure_reason: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[ExplorationRun, bool]:
    reservation, existing_idempotent = await _reserve_idempotency(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        scope="exploration:transition",
        idempotency_key=idempotency_key,
        resource_type="exploration_run",
        request={
            "exploration_id": str(exploration_id),
            "status": status,
            "result_summary": result_summary,
            "failure_reason": failure_reason,
        },
    )
    if existing_idempotent is not None:
        return existing_idempotent, False
    exploration = await get_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        exploration_id=exploration_id,
        for_update=True,
    )
    if _has_tool_event_idempotency_key(exploration, idempotency_key) or exploration.status == status:
        await _complete_idempotency(
            db,
            reservation,
            resource_id=exploration.id,
            metadata={"status": status, "changed": False},
        )
        return exploration, False
    _validate_status_transition(
        resource="EXPLORATION",
        current_status=exploration.status,
        next_status=status,
        allowed=ALLOWED_EXPLORATION_STATUS_TRANSITIONS,
    )
    exploration.status = status
    if status == "running" and exploration.started_at is None:
        exploration.started_at = _now()
    if status in {"succeeded", "failed", "blocked_by_policy", "cancelled", "timed_out"}:
        exploration.completed_at = _now()
    exploration.result_summary = result_summary
    exploration.failure_reason = failure_reason
    _remember_tool_event_idempotency_key(exploration, idempotency_key, scope="completion")
    await _flush_or_validation_error(db)
    await _complete_idempotency(
        db,
        reservation,
        resource_id=exploration.id,
        metadata={"status": status, "changed": True},
    )
    return exploration, True


async def get_recommendation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    recommendation_id: uuid.UUID,
) -> CapabilityRecommendation:
    return await _one(
        db,
        select(CapabilityRecommendation).where(
            CapabilityRecommendation.id == recommendation_id,
            CapabilityRecommendation.tenant_id == tenant_id,
            CapabilityRecommendation.user_id == user_id,
        ),
        "RECOMMENDATION_NOT_FOUND",
        "Capability recommendation not found",
    )


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
) -> tuple[CapabilityRecommendation, bool]:
    bounded_expected_value = validate_bounded_json(_jsonable(expected_value or {}), field="expected_value")
    bounded_required_permissions = validate_bounded_json(
        _jsonable(required_permissions or {}),
        field="required_permissions",
    )
    bounded_candidate_targets = validate_bounded_json(_jsonable(candidate_targets or []), field="candidate_targets")
    reservation, existing_idempotent = await _reserve_idempotency(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        scope="recommendation:create",
        idempotency_key=idempotency_key,
        resource_type="capability_recommendation",
        request={
            "gap_id": str(gap_id),
            "exploration_run_id": str(exploration_run_id) if exploration_run_id else None,
            "recommendation_type": recommendation_type,
            "title": title,
            "summary": summary,
            "reason": reason,
            "evidence": evidence,
            "risk_level": risk_level,
            "expected_value": bounded_expected_value,
            "required_permissions": bounded_required_permissions,
            "candidate_targets": bounded_candidate_targets,
        },
    )
    if existing_idempotent is not None:
        return existing_idempotent, False
    await get_gap(db, tenant_id=tenant_id, user_id=user_id, gap_id=gap_id, for_update=True)
    await _validate_exploration_parent_scope(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        exploration_run_id=exploration_run_id,
    )
    if idempotency_key:
        existing_rows = list(
            (
                await db.execute(
                    select(CapabilityRecommendation).where(
                        CapabilityRecommendation.tenant_id == tenant_id,
                        CapabilityRecommendation.user_id == user_id,
                        CapabilityRecommendation.gap_id == gap_id,
                    )
                )
            ).scalars()
        )
        for existing in existing_rows:
            if _has_idempotency_key(existing, idempotency_key):
                await _complete_idempotency(
                    db,
                    reservation,
                    resource_id=existing.id,
                    metadata={"gap_id": str(gap_id), "legacy_json_replay": True},
                )
                return existing, False
    recommendation = CapabilityRecommendation(
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        exploration_run_id=exploration_run_id,
        recommendation_type=recommendation_type,
        title=title,
        summary=summary,
        reason=reason,
        evidence=_with_lifecycle_metadata(evidence, idempotency_key=idempotency_key),
        risk_level=risk_level,
        expected_value=bounded_expected_value,
        required_permissions=bounded_required_permissions,
        candidate_targets=bounded_candidate_targets,
    )
    db.add(recommendation)
    await _flush_or_validation_error(db)
    await _complete_idempotency(
        db,
        reservation,
        resource_id=recommendation.id,
        metadata={"gap_id": str(gap_id), "exploration_run_id": str(exploration_run_id) if exploration_run_id else None},
    )
    return recommendation, True


async def get_proposal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    for_update: bool = False,
) -> AcquisitionProposal:
    query = select(AcquisitionProposal).where(
        AcquisitionProposal.id == proposal_id,
        AcquisitionProposal.tenant_id == tenant_id,
        AcquisitionProposal.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await _one(db, query, "PROPOSAL_NOT_FOUND", "Acquisition proposal not found")


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
) -> tuple[AcquisitionProposal, bool]:
    bounded_permission_bundle = validate_bounded_json(_jsonable(permission_bundle), field="permission_bundle")
    bounded_primary_target = (
        validate_bounded_json(_jsonable(primary_target), field="primary_target")
        if primary_target is not None
        else None
    )
    bounded_secondary_targets = validate_bounded_json(_jsonable(secondary_targets or []), field="secondary_targets")
    bounded_development_handoff = (
        validate_bounded_json(_jsonable(development_handoff), field="development_handoff")
        if development_handoff is not None
        else None
    )
    bounded_verification_plan = validate_bounded_json(_jsonable(verification_plan), field="verification_plan")
    bounded_rollback_plan = validate_bounded_json(_jsonable(rollback_plan), field="rollback_plan")
    reservation, existing_idempotent = await _reserve_idempotency(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        scope="proposal:create",
        idempotency_key=idempotency_key,
        resource_type="acquisition_proposal",
        request={
            "proposal_kind": proposal_kind,
            "gap_id": str(gap_id),
            "recommendation_id": str(recommendation_id),
            "title": title,
            "reason": reason,
            "evidence": evidence,
            "risk_level": risk_level,
            "permission_bundle": bounded_permission_bundle,
            "primary_target": bounded_primary_target,
            "secondary_targets": bounded_secondary_targets,
            "development_handoff": bounded_development_handoff,
            "verification_plan": bounded_verification_plan,
            "rollback_plan": bounded_rollback_plan,
            "user_visible_effect": user_visible_effect,
        },
    )
    if existing_idempotent is not None:
        return existing_idempotent, False
    await get_gap(db, tenant_id=tenant_id, user_id=user_id, gap_id=gap_id, for_update=True)
    await _validate_recommendation_parent_scope(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        recommendation_id=recommendation_id,
    )
    if idempotency_key:
        existing_rows = list(
            (
                await db.execute(
                    select(AcquisitionProposal).where(
                        AcquisitionProposal.tenant_id == tenant_id,
                        AcquisitionProposal.user_id == user_id,
                        AcquisitionProposal.gap_id == gap_id,
                        AcquisitionProposal.recommendation_id == recommendation_id,
                    )
                )
            ).scalars()
        )
        for existing in existing_rows:
            if _has_idempotency_key(existing, idempotency_key):
                await _complete_idempotency(
                    db,
                    reservation,
                    resource_id=existing.id,
                    metadata={"gap_id": str(gap_id), "legacy_json_replay": True},
                )
                return existing, False
    proposal = AcquisitionProposal(
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_kind=proposal_kind,
        gap_id=gap_id,
        recommendation_id=recommendation_id,
        title=title,
        reason=reason,
        evidence=_with_lifecycle_metadata(evidence, idempotency_key=idempotency_key),
        risk_level=risk_level,
        permission_bundle=bounded_permission_bundle,
        primary_target=bounded_primary_target if bounded_primary_target is not None else null(),
        secondary_targets=bounded_secondary_targets,
        development_handoff=bounded_development_handoff,
        verification_plan=bounded_verification_plan,
        rollback_plan=bounded_rollback_plan,
        user_visible_effect=user_visible_effect,
        approval_history=[],
    )
    db.add(proposal)
    await _flush_or_validation_error(db)
    await _complete_idempotency(
        db,
        reservation,
        resource_id=proposal.id,
        metadata={"gap_id": str(gap_id), "recommendation_id": str(recommendation_id), "proposal_kind": proposal_kind},
    )
    return proposal, True


async def transition_proposal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    status: str,
    actor_user_id: uuid.UUID | None = None,
    reason: str | None = None,
    idempotency_key: str | None = None,
    guarded_transition: bool = False,
) -> tuple[AcquisitionProposal, bool]:
    reservation, existing_idempotent = await _reserve_idempotency(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        scope="proposal:transition",
        idempotency_key=idempotency_key,
        resource_type="acquisition_proposal",
        request={
            "proposal_id": str(proposal_id),
            "status": status,
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "reason": reason,
            "guarded_transition": guarded_transition,
        },
    )
    if existing_idempotent is not None:
        return existing_idempotent, False
    proposal = await get_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.status == status:
        await _complete_idempotency(
            db,
            reservation,
            resource_id=proposal.id,
            metadata={"status": status, "changed": False},
        )
        return proposal, False
    history = list(proposal.approval_history or [])
    if idempotency_key and any(item.get("idempotency_key") == idempotency_key for item in history):
        await _complete_idempotency(
            db,
            reservation,
            resource_id=proposal.id,
            metadata={"status": status, "legacy_json_replay": True},
        )
        return proposal, False
    allowed = ALLOWED_PROPOSAL_STATUS_TRANSITIONS
    if proposal.proposal_kind == "development_patch_proposal":
        allowed = ALLOWED_DEVELOPMENT_PATCH_PROPOSAL_STATUS_TRANSITIONS
    elif proposal.proposal_kind != "runtime_activation":
        raise api_error(
            409,
            "UNKNOWN_PROPOSAL_KIND",
            "Unknown acquisition proposal kind",
            {"proposal_kind": proposal.proposal_kind},
        )
    _validate_status_transition(
        resource="PROPOSAL",
        current_status=proposal.status,
        next_status=status,
        allowed=allowed,
    )
    if proposal.proposal_kind == "runtime_activation" and status in GUARDED_RUNTIME_ACTIVATION_STATUSES and not guarded_transition:
        raise api_error(
            409,
            "GUARDED_PROPOSAL_STATUS_TRANSITION_REQUIRED",
            "Runtime activation guarded states must be entered through the activation owner",
            {
                "current_status": proposal.status,
                "next_status": status,
            },
        )
    proposal.status = status
    history.append(
        {
            "status": status,
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "reason": reason,
            "idempotency_key": idempotency_key,
            "recorded_at": _now().isoformat(),
        }
    )
    proposal.approval_history = validate_bounded_json(history[-50:], field="approval_history")
    await _flush_or_validation_error(db)
    await _complete_idempotency(
        db,
        reservation,
        resource_id=proposal.id,
        metadata={"status": status, "changed": True},
    )
    return proposal, True
