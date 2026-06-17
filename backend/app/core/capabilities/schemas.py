"""Shared capability-layer constants and serializers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.capability import CANDIDATE_STATUSES, CANDIDATE_TYPES, CapabilityCandidate

ACTIVE_RETRIEVAL_STATUSES = {"accepted", "edited_accepted"}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_candidate(candidate: CapabilityCandidate) -> dict[str, Any]:
    return {
        "id": str(candidate.id),
        "tenant_id": str(candidate.tenant_id),
        "user_id": str(candidate.user_id),
        "candidate_type": candidate.candidate_type,
        "status": candidate.status,
        "title": candidate.title,
        "body": candidate.body,
        "source_run_id": candidate.source_run_id,
        "source_event_id": candidate.source_event_id,
        "source_message_id": candidate.source_message_id,
        "source_uri": candidate.source_uri,
        "source_kind": candidate.source_kind,
        "dedupe_key": candidate.dedupe_key,
        "merge_target_candidate_id": str(candidate.merge_target_candidate_id)
        if candidate.merge_target_candidate_id
        else None,
        "merge_reason": candidate.merge_reason,
        "merged_at": iso(candidate.merged_at),
        "snoozed_until": iso(candidate.snoozed_until),
        "mute_pattern": candidate.mute_pattern,
        "muted_at": iso(candidate.muted_at),
        "worker_id": str(candidate.worker_id) if candidate.worker_id else None,
        "accepted_at": iso(candidate.accepted_at),
        "accepted_by": str(candidate.accepted_by) if candidate.accepted_by else None,
        "dismissed_at": iso(candidate.dismissed_at),
        "archived_at": iso(candidate.archived_at),
        "evidence": candidate.evidence or {},
        "payload": candidate.payload or {},
        "metadata": candidate.metadata_ or {},
        "created_at": candidate.created_at.isoformat(),
        "updated_at": candidate.updated_at.isoformat(),
    }
