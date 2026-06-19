"""Durable personal Worker owner models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, gen_uuid

WORKER_STATUSES = ("draft", "active", "disabled", "soft_deleted")
WORKER_VERSION_STATUSES = ("draft", "verified", "active", "archived", "failed_verification")
WORKER_RUN_STATUSES = (
    "succeeded",
    "failed",
    "failed_fallback_succeeded",
    "failed_fallback_failed",
    "blocked_by_policy",
    "cancelled",
    "needs_user_confirmation",
)


def _in_constraint(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Worker(Base, TimestampMixin):
    """User-owned Worker metadata.

    Workers are durable configuration records only in W1. They do not execute
    and are not consulted by Agent planning.
    """

    __tablename__ = "workers"
    __table_args__ = (
        CheckConstraint(_in_constraint("status", WORKER_STATUSES), name="ck_workers_status"),
        CheckConstraint("octet_length(trigger::text) <= 8192", name="ck_workers_trigger_size"),
        CheckConstraint("octet_length(policy::text) <= 8192", name="ck_workers_policy_size"),
        CheckConstraint("octet_length(activation_evidence::text) <= 8192", name="ck_workers_activation_evidence_size"),
        CheckConstraint('octet_length("metadata"::text) <= 8192', name="ck_workers_metadata_size"),
        UniqueConstraint("tenant_id", "user_id", "name", name="uq_workers_user_name"),
        Index("ix_workers_tenant_user_status", "tenant_id", "user_id", "status"),
        Index(
            "ix_workers_tenant_user_enabled_soft_deleted",
            "tenant_id",
            "user_id",
            "enabled",
            "soft_deleted_at",
        ),
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
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    activation_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    activation_requested_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("worker_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    activation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    activation_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    soft_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class WorkerVersion(Base, TimestampMixin):
    """Versioned Worker definition and verification evidence."""

    __tablename__ = "worker_versions"
    __table_args__ = (
        CheckConstraint(
            _in_constraint("status", WORKER_VERSION_STATUSES),
            name="ck_worker_versions_status",
        ),
        CheckConstraint("octet_length(definition::text) <= 8192", name="ck_worker_versions_definition_size"),
        CheckConstraint(
            "octet_length(verification_plan::text) <= 8192",
            name="ck_worker_versions_verification_plan_size",
        ),
        CheckConstraint(
            "octet_length(verification_evidence::text) <= 8192",
            name="ck_worker_versions_verification_evidence_size",
        ),
        UniqueConstraint("worker_id", "version", name="uq_worker_versions_worker_version"),
        Index("ix_worker_versions_tenant_user_status", "tenant_id", "user_id", "status"),
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
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workers.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    verification_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    verification_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    match_embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkerRun(Base, TimestampMixin):
    """Durable Worker run record for future runtime owners."""

    __tablename__ = "worker_runs"
    __table_args__ = (
        CheckConstraint(_in_constraint("status", WORKER_RUN_STATUSES), name="ck_worker_runs_status"),
        CheckConstraint("octet_length(input_payload::text) <= 8192", name="ck_worker_runs_input_payload_size"),
        CheckConstraint("octet_length(output_payload::text) <= 8192", name="ck_worker_runs_output_payload_size"),
        CheckConstraint(
            "octet_length(confirmation_metadata::text) <= 8192",
            name="ck_worker_runs_confirmation_metadata_size",
        ),
        CheckConstraint(
            "error_message IS NULL OR char_length(error_message) <= 1024",
            name="ck_worker_runs_error_message_size",
        ),
        Index("ix_worker_runs_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_worker_runs_tenant_user_source_run", "tenant_id", "user_id", "source_run_id"),
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
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workers.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("worker_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class WorkerMatchFeedback(Base, TimestampMixin):
    """Feedback on Worker matching decisions, not runtime execution."""

    __tablename__ = "worker_match_feedback"
    __table_args__ = (
        CheckConstraint('octet_length("metadata"::text) <= 8192', name="ck_worker_match_feedback_metadata_size"),
        Index("ix_worker_match_feedback_tenant_user_worker", "tenant_id", "user_id", "worker_id"),
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
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workers.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feedback: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
