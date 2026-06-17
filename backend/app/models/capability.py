"""Durable Capability Candidate and analysis job models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, gen_uuid

CANDIDATE_STATUSES = (
    "new",
    "seen",
    "accepted",
    "edited_accepted",
    "dismissed",
    "snoozed",
    "muted_pattern",
    "merged",
    "archived",
)
CANDIDATE_TYPES = ("memory", "skill", "worker")
ANALYSIS_JOB_STATUSES = ("pending", "running", "succeeded", "failed", "skipped_duplicate")


def _in_constraint(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class CapabilityCandidate(Base, TimestampMixin):
    """Personal candidate suggested by analysis, never consumed by Agent planning."""

    __tablename__ = "capability_candidates"
    __table_args__ = (
        CheckConstraint(
            _in_constraint("candidate_type", CANDIDATE_TYPES),
            name="ck_capability_candidates_type",
        ),
        CheckConstraint(
            _in_constraint("status", CANDIDATE_STATUSES),
            name="ck_capability_candidates_status",
        ),
        CheckConstraint("octet_length(evidence::text) <= 8192", name="ck_capability_candidates_evidence_size"),
        CheckConstraint("octet_length(payload::text) <= 8192", name="ck_capability_candidates_payload_size"),
        CheckConstraint('octet_length("metadata"::text) <= 8192', name="ck_capability_candidates_metadata_size"),
        Index("ix_capability_candidates_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_capability_candidates_tenant_user_dedupe", "tenant_id", "user_id", "dedupe_key"),
        Index("ix_capability_candidates_tenant_user_source_run", "tenant_id", "user_id", "source_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="new", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(80), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    merge_target_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("capability_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    merge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mute_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True)
    muted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workers.id", ondelete="SET NULL"),
        nullable=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class CapabilityAnalysisJob(Base, TimestampMixin):
    """Durable outbox job for future candidate analyzers."""

    __tablename__ = "capability_analysis_jobs"
    __table_args__ = (
        CheckConstraint(
            _in_constraint("status", ANALYSIS_JOB_STATUSES),
            name="ck_capability_analysis_jobs_status",
        ),
        CheckConstraint("octet_length(payload::text) <= 8192", name="ck_capability_analysis_jobs_payload_size"),
        CheckConstraint(
            "octet_length(result_metadata::text) <= 8192",
            name="ck_capability_analysis_jobs_result_metadata_size",
        ),
        CheckConstraint(
            "error_message IS NULL OR char_length(error_message) <= 1024",
            name="ck_capability_analysis_jobs_error_message_size",
        ),
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "source_run_id",
            name="uq_capability_analysis_jobs_run",
        ),
        Index("ix_capability_analysis_jobs_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_capability_analysis_jobs_tenant_user_source_run", "tenant_id", "user_id", "source_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_kind: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    result_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
