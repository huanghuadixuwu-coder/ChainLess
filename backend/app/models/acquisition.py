"""Durable V3 capability acquisition models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, gen_uuid

GAP_TYPES = (
    "missing_tool",
    "missing_mcp",
    "missing_api",
    "missing_credential",
    "missing_workspace_access",
    "missing_browser_automation",
    "unstable_public_source",
    "unsupported_external_action",
    "requires_product_change",
    "requires_code_patch",
    "blocked_by_policy",
)
GAP_STATUSES = (
    "detected",
    "exploration_recommended",
    "exploration_approved",
    "exploring",
    "explored_success",
    "explored_failed",
    "recommendation_created",
    "proposal_drafted",
    "dismissed",
    "snoozed",
    "superseded",
    "blocked_by_policy",
)
EXPLORATION_STRATEGIES = (
    "code_as_action",
    "web_search",
    "web_fetch",
    "existing_tool_chain",
    "mcp_probe",
    "workspace_probe",
    "browser_probe",
    "manual_research",
)
EXPLORATION_STATUSES = ("queued", "running", "succeeded", "failed", "blocked_by_policy", "cancelled", "timed_out")
RECOMMENDATION_TYPES = (
    "mcp_recommendation",
    "api_recommendation",
    "browser_automation_recommendation",
    "workspace_connector_recommendation",
    "credential_recommendation",
    "worker_recommendation",
    "skill_recommendation",
    "memory_recommendation",
    "development_patch_recommendation",
)
PROPOSAL_KINDS = ("runtime_activation", "development_patch_proposal")
PROPOSAL_STATUSES = (
    "drafted",
    "verification_requested",
    "verifying",
    "verified",
    "activation_requested",
    "activation_approved",
    "activating",
    "activated",
    "activation_rejected",
    "verification_failed",
    "verification_stale",
    "partial_activation",
    "activation_failed",
    "rolled_back",
    "handoff_ready",
    "handoff_started",
    "dismissed",
    "superseded",
)
DEVELOPMENT_PATCH_PROPOSAL_STATUSES = (
    "drafted",
    "verifying",
    "verified",
    "verification_failed",
    "handoff_ready",
    "handoff_started",
    "dismissed",
    "superseded",
)
TARGET_TYPES = ("mcp_tool", "api_tool", "workspace_connector", "browser_automation", "worker", "skill", "memory")
TARGET_STATUSES = (
    "draft",
    "verification_pending",
    "verifying",
    "verified",
    "verification_failed",
    "activation_pending",
    "active",
    "activation_failed",
    "rolled_back",
    "disabled",
)
VERIFICATION_STATUSES = ("pending", "running", "passed", "failed", "blocked_by_policy", "cancelled", "timed_out")
PLANNING_ISSUE_TYPES = (
    "planner_missed_existing_tool",
    "planner_missed_worker",
    "planner_missed_skill",
    "planner_missed_memory",
    "wrong_risk_classification",
    "wrong_fallback_choice",
)
CREDENTIAL_CONNECTION_TYPES = (
    "api_key",
    "oauth",
    "bearer_token",
    "basic_auth",
    "browser_cookie",
    "mcp_env_secret",
    "workspace_os_permission",
    "external_vault_ref",
)
CREDENTIAL_STATUSES = ("draft", "active", "validation_failed", "rotation_required", "revoked", "expired")
PERMISSION_DURATIONS = ("one_run", "until_revoked", "expires_at", "per_worker_run_confirmation")
PERMISSION_STATUSES = ("active", "revoked", "expired", "renewal_required")
RISK_LEVELS = ("safe", "risky", "high_risk", "blocked")
SEVERITIES = ("low", "medium", "high", "critical")
MCP_TRANSPORTS = ("stdio", "http", "sse")
MCP_RUNTIME_KINDS = ("remote_http", "remote_sse", "isolated_stdio")
API_METHODS = ("GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE")
WORKSPACE_CONNECTOR_MODES = ("read_only", "read_write")
MOUNT_HEALTH_STATUSES = ("unknown", "healthy", "unhealthy", "stale")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _in_constraint(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class CapabilityGap(Base, TimestampMixin):
    """Private record of a missing or insufficient capability."""

    __tablename__ = "capability_gaps"
    __table_args__ = (
        CheckConstraint(_in_constraint("gap_type", GAP_TYPES), name="ck_capability_gaps_type"),
        CheckConstraint(_in_constraint("severity", SEVERITIES), name="ck_capability_gaps_severity"),
        CheckConstraint(_in_constraint("status", GAP_STATUSES), name="ck_capability_gaps_status"),
        CheckConstraint("occurrence_count >= 1", name="ck_capability_gaps_occurrence_count_positive"),
        CheckConstraint("octet_length(source_evidence::text) <= 16384", name="ck_capability_gaps_source_evidence_size"),
        CheckConstraint("octet_length(evidence::text) <= 16384", name="ck_capability_gaps_evidence_size"),
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "gap_type",
            "dedupe_key",
            name="uq_capability_gaps_user_gap_dedupe",
        ),
        Index("ix_capability_gaps_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_capability_gaps_tenant_user_dedupe", "tenant_id", "user_id", "dedupe_key"),
        Index("ix_capability_gaps_tenant_user_source_run", "tenant_id", "user_id", "source_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    source_run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    gap_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="detected", nullable=False)
    source_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class AcquisitionIdempotencyRecord(Base):
    """Durable idempotency authority for acquisition mutations."""

    __tablename__ = "acquisition_idempotency_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "scope", "idempotency_key", name="uq_acq_idem_scope_key"),
        Index("ix_acq_idem_tenant_user_resource", "tenant_id", "user_id", "resource_type", "resource_id"),
        Index("ix_acq_idem_tenant_user_created", "tenant_id", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ExplorationRun(Base):
    """Attempt to explore a bounded acquisition path for a gap."""

    __tablename__ = "exploration_runs"
    __table_args__ = (
        CheckConstraint(_in_constraint("risk_level", RISK_LEVELS), name="ck_exploration_runs_risk_level"),
        CheckConstraint(_in_constraint("status", EXPLORATION_STATUSES), name="ck_exploration_runs_status"),
        CheckConstraint(_in_constraint("strategy", EXPLORATION_STRATEGIES), name="ck_exploration_runs_strategy"),
        CheckConstraint("octet_length(tool_events::text) <= 16384", name="ck_exploration_runs_tool_events_size"),
        Index("ix_exploration_runs_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_exploration_runs_tenant_user_gap", "tenant_id", "user_id", "gap_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gap_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("capability_gaps.id", ondelete="CASCADE"), nullable=False)
    source_run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tool_confirmations.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False)
    strategy: Mapped[str] = mapped_column(String(80), nullable=False)
    tool_events: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    script_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    artifact_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    stdout_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CapabilityRecommendation(Base, TimestampMixin):
    """Reviewable acquisition path suggested from exploration or evidence."""

    __tablename__ = "capability_recommendations"
    __table_args__ = (
        CheckConstraint(_in_constraint("recommendation_type", RECOMMENDATION_TYPES), name="ck_capability_recommendations_type"),
        CheckConstraint(_in_constraint("risk_level", RISK_LEVELS), name="ck_capability_recommendations_risk_level"),
        Index("ix_capability_recommendations_tenant_user_type", "tenant_id", "user_id", "recommendation_type"),
        Index("ix_capability_recommendations_tenant_user_gap", "tenant_id", "user_id", "gap_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gap_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("capability_gaps.id", ondelete="CASCADE"), nullable=False)
    exploration_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("exploration_runs.id", ondelete="SET NULL"), nullable=True)
    recommendation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    required_permissions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    candidate_targets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)


class AcquisitionProposal(Base, TimestampMixin):
    """Formal activation or development handoff proposal."""

    __tablename__ = "acquisition_proposals"
    __table_args__ = (
        CheckConstraint(_in_constraint("proposal_kind", PROPOSAL_KINDS), name="ck_acquisition_proposals_kind"),
        CheckConstraint(_in_constraint("status", PROPOSAL_STATUSES), name="ck_acquisition_proposals_status"),
        CheckConstraint(_in_constraint("risk_level", RISK_LEVELS), name="ck_acquisition_proposals_risk_level"),
        CheckConstraint("proposal_kind != 'runtime_activation' OR primary_target IS NOT NULL", name="ck_acquisition_proposals_runtime_requires_primary_target"),
        CheckConstraint("proposal_kind != 'development_patch_proposal' OR primary_target IS NULL", name="ck_acquisition_proposals_patch_has_no_primary_target"),
        CheckConstraint(
            "proposal_kind != 'development_patch_proposal' OR status IN ('drafted', 'verifying', 'verified', 'verification_failed', 'handoff_ready', 'handoff_started', 'dismissed', 'superseded')",
            name="ck_acquisition_proposals_patch_no_runtime_status",
        ),
        Index("ix_acquisition_proposals_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_acquisition_proposals_tenant_user_gap", "tenant_id", "user_id", "gap_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    proposal_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    gap_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("capability_gaps.id", ondelete="CASCADE"), nullable=False)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("capability_recommendations.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="drafted", nullable=False)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False)
    permission_bundle: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    primary_target: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    secondary_targets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    development_handoff: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    verification_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    rollback_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    user_visible_effect: Mapped[str] = mapped_column(Text, nullable=False)
    approval_history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    activation_snapshot_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActivationTarget(Base, TimestampMixin):
    """Typed handoff from Acquisition to a runtime owner."""

    __tablename__ = "activation_targets"
    __table_args__ = (
        CheckConstraint(_in_constraint("target_type", TARGET_TYPES), name="ck_activation_targets_type"),
        CheckConstraint(_in_constraint("activation_status", TARGET_STATUSES), name="ck_activation_targets_status"),
        CheckConstraint("target_type != 'development_patch_proposal'", name="ck_activation_targets_no_development_patch_type"),
        Index("ix_activation_targets_tenant_user_status", "tenant_id", "user_id", "activation_status"),
        Index("ix_activation_targets_tenant_user_proposal", "tenant_id", "user_id", "proposal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("acquisition_proposals.id", ondelete="CASCADE"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_name: Mapped[str] = mapped_column(String(160), nullable=False)
    target_owner: Mapped[str] = mapped_column(String(120), nullable=False)
    target_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    permission_bundle: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    verification_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    rollback_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    activation_status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    activation_result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    activated_resource_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class AcquisitionVerification(Base):
    """Verification execution and snapshot evidence for a proposal target."""

    __tablename__ = "acquisition_verifications"
    __table_args__ = (
        CheckConstraint(_in_constraint("status", VERIFICATION_STATUSES), name="ck_acquisition_verifications_status"),
        CheckConstraint("error_message IS NULL OR char_length(error_message) <= 1024", name="ck_acquisition_verifications_error_message_size"),
        Index("ix_acquisition_verifications_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_acquisition_verifications_tenant_user_proposal", "tenant_id", "user_id", "proposal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("acquisition_proposals.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("activation_targets.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    verification_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    input_fixture: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    expected_result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    actual_result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    artifact_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_snapshot_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AcquisitionJournalEntry(Base, TimestampMixin):
    """Generated private journal entry; DB remains authoritative."""

    __tablename__ = "acquisition_journal_entries"
    __table_args__ = (
        CheckConstraint("octet_length(rendered_markdown) <= 32768", name="ck_acquisition_journal_entries_markdown_size"),
        Index("ix_acquisition_journal_entries_tenant_user_kind", "tenant_id", "user_id", "entry_kind"),
        Index(
            "uq_acq_journal_snapshot_user",
            "tenant_id",
            "user_id",
            "entry_kind",
            unique=True,
            postgresql_where=text("entry_kind = 'acquisition_journal_snapshot'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    rendered_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)


class RuntimePlanningIssue(Base, TimestampMixin):
    """Planner miss for an existing capability, separate from acquisition gaps."""

    __tablename__ = "runtime_planning_issues"
    __table_args__ = (
        CheckConstraint(_in_constraint("issue_type", PLANNING_ISSUE_TYPES), name="ck_runtime_planning_issues_type"),
        CheckConstraint(_in_constraint("severity", SEVERITIES), name="ck_runtime_planning_issues_severity"),
        CheckConstraint("status IN ('open', 'dismissed', 'candidate_created', 'resolved')", name="ck_runtime_planning_issues_status"),
        Index("ix_runtime_planning_issues_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_runtime_planning_issues_tenant_user_source_run", "tenant_id", "user_id", "source_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    issue_type: Mapped[str] = mapped_column(String(80), nullable=False)
    available_capability_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    missed_signal: Mapped[str] = mapped_column(Text, nullable=False)
    planner_decision_summary: Mapped[str] = mapped_column(Text, nullable=False)
    expected_decision_summary: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class CredentialConnection(Base, TimestampMixin):
    """User-private credential reference without raw secret material."""

    __tablename__ = "credential_connections"
    __table_args__ = (
        CheckConstraint(_in_constraint("connection_type", CREDENTIAL_CONNECTION_TYPES), name="ck_credential_connections_type"),
        CheckConstraint(_in_constraint("status", CREDENTIAL_STATUSES), name="ck_credential_connections_status"),
        CheckConstraint("secret_generation >= 1", name="ck_credential_connections_secret_generation_positive"),
        Index("ix_credential_connections_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_credential_connections_tenant_user_provider", "tenant_id", "user_id", "provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    connection_type: Mapped[str] = mapped_column(String(60), nullable=False)
    credential_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    secret_storage_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    secret_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    secret_generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    allowed_target_types: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    allowed_target_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    metadata_redacted: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotation_required_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StandingPermission(Base, TimestampMixin):
    """Bounded activation-time approval for future automatic execution."""

    __tablename__ = "standing_permissions"
    __table_args__ = (
        CheckConstraint(_in_constraint("duration", PERMISSION_DURATIONS), name="ck_standing_permissions_duration"),
        CheckConstraint(_in_constraint("risk_level", RISK_LEVELS), name="ck_standing_permissions_risk_level"),
        CheckConstraint(_in_constraint("status", PERMISSION_STATUSES), name="ck_standing_permissions_status"),
        CheckConstraint("duration != 'expires_at' OR expires_at IS NOT NULL", name="ck_standing_permissions_expires_at_required"),
        Index("ix_standing_permissions_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_standing_permissions_tenant_user_target", "tenant_id", "user_id", "target_type", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("acquisition_proposals.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("activation_targets.id", ondelete="CASCADE"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    permission_scope: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False)
    duration: Mapped[str] = mapped_column(String(40), nullable=False)
    approved_snapshot_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    renewal_required_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    audit_events: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)


class MCPServerConfiguration(Base, TimestampMixin):
    """Durable MCP server configuration handed to the MCP runtime owner."""

    __tablename__ = "mcp_server_configurations"
    __table_args__ = (
        CheckConstraint(_in_constraint("transport", MCP_TRANSPORTS), name="ck_mcp_server_configurations_transport"),
        CheckConstraint(_in_constraint("runtime_kind", MCP_RUNTIME_KINDS), name="ck_mcp_server_configurations_runtime_kind"),
        CheckConstraint(_in_constraint("risk_level", RISK_LEVELS), name="ck_mcp_server_configurations_risk_level"),
        CheckConstraint("transport != 'stdio' OR runtime_kind = 'isolated_stdio'", name="ck_mcp_server_configurations_stdio_isolated"),
        CheckConstraint("transport != 'http' OR runtime_kind = 'remote_http'", name="ck_mcp_server_configurations_http_remote"),
        CheckConstraint("transport != 'sse' OR runtime_kind = 'remote_sse'", name="ck_mcp_server_configurations_sse_remote"),
        CheckConstraint("transport != 'stdio' OR command IS NOT NULL", name="ck_mcp_server_configurations_stdio_command"),
        CheckConstraint("transport = 'stdio' OR url IS NOT NULL", name="ck_mcp_server_configurations_remote_url"),
        CheckConstraint("stdio_max_session_seconds IS NULL OR stdio_max_session_seconds >= 1", name="ck_mcp_server_configurations_stdio_max_session_seconds_positive"),
        CheckConstraint("stdio_max_output_bytes IS NULL OR stdio_max_output_bytes >= 1", name="ck_mcp_server_configurations_stdio_max_output_bytes_positive"),
        Index("uq_mcp_server_configurations_tenant_name_enabled", "tenant_id", "name", unique=True, postgresql_where=text("enabled")),
        Index("ix_mcp_server_configurations_tenant_user_enabled", "tenant_id", "user_id", "enabled"),
        Index("ix_mcp_server_configurations_tenant_user_risk", "tenant_id", "user_id", "risk_level"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activation_target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("activation_targets.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    transport: Mapped[str] = mapped_column(String(40), nullable=False)
    runtime_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    args: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    env_secret_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    credential_connection_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    egress_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    stdio_runtime_image_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stdio_command_provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    stdio_package_digest: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stdio_filesystem_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    stdio_network_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    stdio_resource_limits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    stdio_max_session_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdio_max_output_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdio_restart_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False)
    tool_schema_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class APIToolConfiguration(Base, TimestampMixin):
    """Durable API tool configuration handed to the API tool runtime owner."""

    __tablename__ = "api_tool_configurations"
    __table_args__ = (
        CheckConstraint(_in_constraint("method", API_METHODS), name="ck_api_tool_configurations_method"),
        CheckConstraint(_in_constraint("risk_level", RISK_LEVELS), name="ck_api_tool_configurations_risk_level"),
        CheckConstraint("max_request_bytes >= 1", name="ck_api_tool_configurations_max_request_bytes_positive"),
        CheckConstraint("max_response_bytes >= 1", name="ck_api_tool_configurations_max_response_bytes_positive"),
        CheckConstraint("timeout_s >= 1", name="ck_api_tool_configurations_timeout_s_positive"),
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "tool_name",
            name="uq_api_tool_configurations_tenant_user_tool_name",
        ),
        Index("ix_api_tool_configurations_tenant_user_enabled", "tenant_id", "user_id", "enabled"),
        Index("ix_api_tool_configurations_tenant_user_risk", "tenant_id", "user_id", "risk_level"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activation_target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("activation_targets.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path_template: Mapped[str] = mapped_column(String(500), nullable=False)
    headers_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    auth_scheme: Mapped[str] = mapped_column(String(80), nullable=False)
    credential_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("credential_connections.id", ondelete="SET NULL"), nullable=True)
    credential_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    allowed_hosts: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    deny_private_networks: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    redirect_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    allowed_content_types: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    max_request_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    max_response_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    response_redaction_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    rate_limit: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    timeout_s: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error_contract: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkspaceConnector(Base, TimestampMixin):
    """Durable approved workspace path mapping."""

    __tablename__ = "workspace_connectors"
    __table_args__ = (
        CheckConstraint(_in_constraint("mode", WORKSPACE_CONNECTOR_MODES), name="ck_workspace_connectors_mode"),
        CheckConstraint(_in_constraint("mount_health_status", MOUNT_HEALTH_STATUSES), name="ck_workspace_connectors_mount_health_status"),
        CheckConstraint("mount_generation >= 1", name="ck_workspace_connectors_mount_generation_positive"),
        Index("ix_workspace_connectors_tenant_user_enabled", "tenant_id", "user_id", "enabled"),
        Index("ix_workspace_connectors_tenant_user_connector_id", "tenant_id", "user_id", "connector_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activation_target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("activation_targets.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False)
    display_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    host_realpath_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    container_mount_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    backend_mount_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    sandbox_mount_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    connector_root: Mapped[str] = mapped_column(String(1000), nullable=False)
    mount_generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    mount_health_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    allowlist_rule: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    standing_permission_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("standing_permissions.id", ondelete="SET NULL"), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BrowserAutomationConfiguration(Base, TimestampMixin):
    """Durable browser automation runtime configuration."""

    __tablename__ = "browser_automation_configurations"
    __table_args__ = (
        CheckConstraint("max_session_seconds >= 1", name="ck_browser_auto_cfg_max_session_seconds_positive"),
        CheckConstraint("max_actions_per_run >= 1", name="ck_browser_auto_cfg_max_actions_per_run_positive"),
        CheckConstraint("concurrency_limit >= 1", name="ck_browser_automation_configurations_concurrency_limit_positive"),
        CheckConstraint("memory_limit_mb >= 1", name="ck_browser_automation_configurations_memory_limit_mb_positive"),
        CheckConstraint("max_trace_bytes >= 1", name="ck_browser_automation_configurations_max_trace_bytes_positive"),
        CheckConstraint("trace_retention_days >= 1", name="ck_browser_auto_cfg_trace_retention_days_positive"),
        Index("ix_browser_automation_configurations_tenant_user_enabled", "tenant_id", "user_id", "enabled"),
        Index("ix_browser_automation_configurations_tenant_user_runtime", "tenant_id", "user_id", "runtime_service_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activation_target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("activation_targets.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    allowlisted_domains: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    credential_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("credential_connections.id", ondelete="SET NULL"), nullable=True)
    credential_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runtime_service_name: Mapped[str] = mapped_column(String(160), nullable=False)
    runtime_image_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    runtime_health_check: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    network_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    cookie_scope: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    profile_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    profile_storage_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    profile_retention_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    max_session_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_actions_per_run: Mapped[int] = mapped_column(Integer, nullable=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    cpu_limit: Mapped[str] = mapped_column(String(40), nullable=False)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    max_trace_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    trace_retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    action_redaction_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    write_confirmation_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DevelopmentPatchProposal(Base, TimestampMixin):
    """Development workflow handoff evidence; never runtime-active."""

    __tablename__ = "development_patch_proposals"
    __table_args__ = (
        CheckConstraint(_in_constraint("status", DEVELOPMENT_PATCH_PROPOSAL_STATUSES), name="ck_development_patch_proposals_status"),
        CheckConstraint("working_tree_mutation_allowed = false", name="ck_development_patch_proposals_no_worktree_mutation"),
        UniqueConstraint("proposal_id", name="uq_development_patch_proposals_proposal"),
        Index("ix_development_patch_proposals_tenant_user_status", "tenant_id", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("acquisition_proposals.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="drafted", nullable=False)
    base_git_commit: Mapped[str] = mapped_column(String(80), nullable=False)
    patch_artifact_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    patch_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    test_plan_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    rollback_plan_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    review_checklist_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    apply_check_status: Mapped[str] = mapped_column(String(80), nullable=False)
    working_tree_mutation_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    handoff_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handoff_requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
