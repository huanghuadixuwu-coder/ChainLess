"""add capability acquisition layer

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)

ACQUISITION_TABLES = (
    "acquisition_idempotency_records",
    "capability_gaps",
    "exploration_runs",
    "capability_recommendations",
    "acquisition_proposals",
    "activation_targets",
    "acquisition_verifications",
    "acquisition_journal_entries",
    "runtime_planning_issues",
    "credential_connections",
    "standing_permissions",
    "mcp_server_configurations",
    "api_tool_configurations",
    "workspace_connectors",
    "browser_automation_configurations",
    "development_patch_proposals",
)
USER_STATUS_INDEXES = (
    "ix_capability_gaps_tenant_user_status",
    "ix_exploration_runs_tenant_user_status",
    "ix_acquisition_proposals_tenant_user_status",
    "ix_activation_targets_tenant_user_status",
    "ix_acquisition_verifications_tenant_user_status",
    "ix_runtime_planning_issues_tenant_user_status",
    "ix_credential_connections_tenant_user_status",
    "ix_standing_permissions_tenant_user_status",
    "ix_development_patch_proposals_tenant_user_status",
)
GAP_DEDUPE_UNIQUE_COLUMNS = ("tenant_id", "user_id", "gap_type", "dedupe_key")


def _json_default(value: str = "'{}'::jsonb") -> sa.TextClause:
    return sa.text(value)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def _tenant_user_fk() -> tuple[sa.ForeignKeyConstraint, sa.ForeignKeyConstraint]:
    return (
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )


def upgrade() -> None:
    op.create_table(
        "acquisition_idempotency_records",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", UUID, nullable=False),
        sa.Column("metadata", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "scope", "idempotency_key", name="uq_acq_idem_scope_key"),
    )
    op.create_index(
        "ix_acq_idem_tenant_user_resource",
        "acquisition_idempotency_records",
        ["tenant_id", "user_id", "resource_type", "resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_acq_idem_tenant_user_created",
        "acquisition_idempotency_records",
        ["tenant_id", "user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "capability_gaps",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("source_kind", sa.String(length=80), nullable=False),
        sa.Column("source_run_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", UUID, nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("gap_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="detected", nullable=False),
        sa.Column("source_evidence", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("evidence", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(*GAP_DEDUPE_UNIQUE_COLUMNS, name="uq_capability_gaps_user_gap_dedupe"),
        sa.CheckConstraint(
            "gap_type IN ('missing_tool', 'missing_mcp', 'missing_api', 'missing_credential', 'missing_workspace_access', 'missing_browser_automation', 'unstable_public_source', 'unsupported_external_action', 'requires_product_change', 'requires_code_patch', 'blocked_by_policy')",
            name="ck_capability_gaps_type",
        ),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_capability_gaps_severity"),
        sa.CheckConstraint(
            "status IN ('detected', 'exploration_recommended', 'exploration_approved', 'exploring', 'explored_success', 'explored_failed', 'recommendation_created', 'proposal_drafted', 'dismissed', 'snoozed', 'superseded', 'blocked_by_policy')",
            name="ck_capability_gaps_status",
        ),
        sa.CheckConstraint("occurrence_count >= 1", name="ck_capability_gaps_occurrence_count_positive"),
        sa.CheckConstraint("octet_length(source_evidence::text) <= 16384", name="ck_capability_gaps_source_evidence_size"),
        sa.CheckConstraint("octet_length(evidence::text) <= 16384", name="ck_capability_gaps_evidence_size"),
    )
    op.create_index("ix_capability_gaps_tenant_user_status", "capability_gaps", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index("ix_capability_gaps_tenant_user_dedupe", "capability_gaps", ["tenant_id", "user_id", "dedupe_key"], unique=False)
    op.create_index("ix_capability_gaps_tenant_user_source_run", "capability_gaps", ["tenant_id", "user_id", "source_run_id"], unique=False)

    op.create_table(
        "exploration_runs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("gap_id", UUID, nullable=False),
        sa.Column("source_run_id", sa.String(length=255), nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("approval_id", UUID, nullable=True),
        sa.Column("status", sa.String(length=40), server_default="queued", nullable=False),
        sa.Column("strategy", sa.String(length=80), nullable=False),
        sa.Column("tool_events", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("script_ref", sa.String(length=1000), nullable=True),
        sa.Column("artifact_refs", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("stdout_excerpt", sa.Text(), nullable=True),
        sa.Column("stderr_excerpt", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["approval_id"], ["tool_confirmations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["gap_id"], ["capability_gaps.id"], ondelete="CASCADE"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("risk_level IN ('safe', 'risky', 'high_risk', 'blocked')", name="ck_exploration_runs_risk_level"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'blocked_by_policy', 'cancelled', 'timed_out')", name="ck_exploration_runs_status"),
        sa.CheckConstraint("strategy IN ('code_as_action', 'web_search', 'web_fetch', 'existing_tool_chain', 'mcp_probe', 'workspace_probe', 'browser_probe', 'manual_research')", name="ck_exploration_runs_strategy"),
        sa.CheckConstraint("octet_length(tool_events::text) <= 16384", name="ck_exploration_runs_tool_events_size"),
    )
    op.create_index("ix_exploration_runs_tenant_user_status", "exploration_runs", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index("ix_exploration_runs_tenant_user_gap", "exploration_runs", ["tenant_id", "user_id", "gap_id"], unique=False)

    op.create_table(
        "capability_recommendations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("gap_id", UUID, nullable=False),
        sa.Column("exploration_run_id", UUID, nullable=True),
        sa.Column("recommendation_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("expected_value", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("required_permissions", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("candidate_targets", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["exploration_run_id"], ["exploration_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["gap_id"], ["capability_gaps.id"], ondelete="CASCADE"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "recommendation_type IN ('mcp_recommendation', 'api_recommendation', 'browser_automation_recommendation', 'workspace_connector_recommendation', 'credential_recommendation', 'worker_recommendation', 'skill_recommendation', 'memory_recommendation', 'development_patch_recommendation')",
            name="ck_capability_recommendations_type",
        ),
        sa.CheckConstraint("risk_level IN ('safe', 'risky', 'high_risk', 'blocked')", name="ck_capability_recommendations_risk_level"),
    )
    op.create_index("ix_capability_recommendations_tenant_user_type", "capability_recommendations", ["tenant_id", "user_id", "recommendation_type"], unique=False)
    op.create_index("ix_capability_recommendations_tenant_user_gap", "capability_recommendations", ["tenant_id", "user_id", "gap_id"], unique=False)

    op.create_table(
        "acquisition_proposals",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("proposal_kind", sa.String(length=60), nullable=False),
        sa.Column("gap_id", UUID, nullable=False),
        sa.Column("recommendation_id", UUID, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="drafted", nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("permission_bundle", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("primary_target", JSONB, nullable=True),
        sa.Column("secondary_targets", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("development_handoff", JSONB, nullable=True),
        sa.Column("verification_plan", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("rollback_plan", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("user_visible_effect", sa.Text(), nullable=False),
        sa.Column("approval_history", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("activation_snapshot_hash", sa.String(length=128), nullable=True),
        sa.Column("snapshot_created_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["gap_id"], ["capability_gaps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["capability_recommendations.id"], ondelete="CASCADE"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("proposal_kind IN ('runtime_activation', 'development_patch_proposal')", name="ck_acquisition_proposals_kind"),
        sa.CheckConstraint(
            "status IN ('drafted', 'verification_requested', 'verifying', 'verified', 'activation_requested', 'activation_approved', 'activating', 'activated', 'activation_rejected', 'verification_failed', 'verification_stale', 'partial_activation', 'activation_failed', 'rolled_back', 'handoff_ready', 'handoff_started', 'dismissed', 'superseded')",
            name="ck_acquisition_proposals_status",
        ),
        sa.CheckConstraint("risk_level IN ('safe', 'risky', 'high_risk', 'blocked')", name="ck_acquisition_proposals_risk_level"),
        sa.CheckConstraint("proposal_kind != 'runtime_activation' OR primary_target IS NOT NULL", name="ck_acquisition_proposals_runtime_requires_primary_target"),
        sa.CheckConstraint("proposal_kind != 'development_patch_proposal' OR primary_target IS NULL", name="ck_acquisition_proposals_patch_has_no_primary_target"),
        sa.CheckConstraint(
            "proposal_kind != 'development_patch_proposal' OR status IN ('drafted', 'verifying', 'verified', 'verification_failed', 'handoff_ready', 'handoff_started', 'dismissed', 'superseded')",
            name="ck_acquisition_proposals_patch_no_runtime_status",
        ),
    )
    op.create_index("ix_acquisition_proposals_tenant_user_status", "acquisition_proposals", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index("ix_acquisition_proposals_tenant_user_gap", "acquisition_proposals", ["tenant_id", "user_id", "gap_id"], unique=False)

    op.create_table(
        "activation_targets",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("proposal_id", UUID, nullable=False),
        sa.Column("target_type", sa.String(length=60), nullable=False),
        sa.Column("target_name", sa.String(length=160), nullable=False),
        sa.Column("target_owner", sa.String(length=120), nullable=False),
        sa.Column("target_payload", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("permission_bundle", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("verification_plan", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("rollback_plan", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("activation_status", sa.String(length=40), server_default="draft", nullable=False),
        sa.Column("activation_result", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("activated_resource_ref", JSONB, nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["proposal_id"], ["acquisition_proposals.id"], ondelete="CASCADE"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("target_type IN ('mcp_tool', 'api_tool', 'workspace_connector', 'browser_automation', 'worker', 'skill', 'memory')", name="ck_activation_targets_type"),
        sa.CheckConstraint(
            "activation_status IN ('draft', 'verification_pending', 'verifying', 'verified', 'verification_failed', 'activation_pending', 'active', 'activation_failed', 'rolled_back', 'disabled')",
            name="ck_activation_targets_status",
        ),
        sa.CheckConstraint("target_type != 'development_patch_proposal'", name="ck_activation_targets_no_development_patch_type"),
    )
    op.create_index("ix_activation_targets_tenant_user_status", "activation_targets", ["tenant_id", "user_id", "activation_status"], unique=False)
    op.create_index("ix_activation_targets_tenant_user_proposal", "activation_targets", ["tenant_id", "user_id", "proposal_id"], unique=False)

    op.create_table(
        "acquisition_verifications",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("proposal_id", UUID, nullable=False),
        sa.Column("target_id", UUID, nullable=True),
        sa.Column("status", sa.String(length=40), server_default="pending", nullable=False),
        sa.Column("verification_kind", sa.String(length=80), nullable=False),
        sa.Column("input_fixture", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("expected_result", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("actual_result", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("artifact_refs", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("verified_snapshot_hash", sa.String(length=128), nullable=True),
        sa.Column("verified_snapshot_payload", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["proposal_id"], ["acquisition_proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["activation_targets.id"], ondelete="CASCADE"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('pending', 'running', 'passed', 'failed', 'blocked_by_policy', 'cancelled', 'timed_out')", name="ck_acquisition_verifications_status"),
        sa.CheckConstraint("error_message IS NULL OR char_length(error_message) <= 1024", name="ck_acquisition_verifications_error_message_size"),
    )
    op.create_index("ix_acquisition_verifications_tenant_user_status", "acquisition_verifications", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index("ix_acquisition_verifications_tenant_user_proposal", "acquisition_verifications", ["tenant_id", "user_id", "proposal_id"], unique=False)

    op.create_table(
        "acquisition_journal_entries",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("entry_kind", sa.String(length=80), nullable=False),
        sa.Column("subject_ref", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("rendered_markdown", sa.Text(), nullable=False),
        sa.Column("source_refs", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        *_timestamps(),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("octet_length(rendered_markdown) <= 32768", name="ck_acquisition_journal_entries_markdown_size"),
    )
    op.create_index("ix_acquisition_journal_entries_tenant_user_kind", "acquisition_journal_entries", ["tenant_id", "user_id", "entry_kind"], unique=False)
    op.create_index(
        "uq_acq_journal_snapshot_user",
        "acquisition_journal_entries",
        ["tenant_id", "user_id", "entry_kind"],
        unique=True,
        postgresql_where=sa.text("entry_kind = 'acquisition_journal_snapshot'"),
    )

    op.create_table(
        "runtime_planning_issues",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("source_run_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", UUID, nullable=True),
        sa.Column("issue_type", sa.String(length=80), nullable=False),
        sa.Column("available_capability_ref", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("missed_signal", sa.Text(), nullable=False),
        sa.Column("planner_decision_summary", sa.Text(), nullable=False),
        sa.Column("expected_decision_summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="open", nullable=False),
        sa.Column("evidence", JSONB, server_default=_json_default(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("issue_type IN ('planner_missed_existing_tool', 'planner_missed_worker', 'planner_missed_skill', 'planner_missed_memory', 'wrong_risk_classification', 'wrong_fallback_choice')", name="ck_runtime_planning_issues_type"),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_runtime_planning_issues_severity"),
        sa.CheckConstraint("status IN ('open', 'dismissed', 'candidate_created', 'resolved')", name="ck_runtime_planning_issues_status"),
    )
    op.create_index("ix_runtime_planning_issues_tenant_user_status", "runtime_planning_issues", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index("ix_runtime_planning_issues_tenant_user_source_run", "runtime_planning_issues", ["tenant_id", "user_id", "source_run_id"], unique=False)

    op.create_table(
        "credential_connections",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("connection_type", sa.String(length=60), nullable=False),
        sa.Column("credential_kind", sa.String(length=80), nullable=False),
        sa.Column("secret_storage_kind", sa.String(length=80), nullable=False),
        sa.Column("secret_ref", sa.String(length=500), nullable=False),
        sa.Column("secret_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("scopes", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("allowed_target_types", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("allowed_target_refs", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="draft", nullable=False),
        sa.Column("metadata_redacted", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotation_required_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("connection_type IN ('api_key', 'oauth', 'bearer_token', 'basic_auth', 'browser_cookie', 'mcp_env_secret', 'workspace_os_permission', 'external_vault_ref')", name="ck_credential_connections_type"),
        sa.CheckConstraint("status IN ('draft', 'active', 'validation_failed', 'rotation_required', 'revoked', 'expired')", name="ck_credential_connections_status"),
        sa.CheckConstraint("secret_generation >= 1", name="ck_credential_connections_secret_generation_positive"),
    )
    op.create_index("ix_credential_connections_tenant_user_status", "credential_connections", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index("ix_credential_connections_tenant_user_provider", "credential_connections", ["tenant_id", "user_id", "provider"], unique=False)

    op.create_table(
        "standing_permissions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("proposal_id", UUID, nullable=False),
        sa.Column("target_id", UUID, nullable=False),
        sa.Column("target_type", sa.String(length=60), nullable=False),
        sa.Column("permission_scope", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("duration", sa.String(length=40), nullable=False),
        sa.Column("approved_snapshot_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="active", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("renewal_required_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_plan", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("audit_events", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["proposal_id"], ["acquisition_proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["activation_targets.id"], ondelete="CASCADE"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("duration IN ('one_run', 'until_revoked', 'expires_at', 'per_worker_run_confirmation')", name="ck_standing_permissions_duration"),
        sa.CheckConstraint("risk_level IN ('safe', 'risky', 'high_risk', 'blocked')", name="ck_standing_permissions_risk_level"),
        sa.CheckConstraint("status IN ('active', 'revoked', 'expired', 'renewal_required')", name="ck_standing_permissions_status"),
        sa.CheckConstraint("duration != 'expires_at' OR expires_at IS NOT NULL", name="ck_standing_permissions_expires_at_required"),
    )
    op.create_index("ix_standing_permissions_tenant_user_status", "standing_permissions", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index("ix_standing_permissions_tenant_user_target", "standing_permissions", ["tenant_id", "user_id", "target_type", "target_id"], unique=False)

    op.create_table(
        "mcp_server_configurations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("activation_target_id", UUID, nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("transport", sa.String(length=40), nullable=False),
        sa.Column("runtime_kind", sa.String(length=40), nullable=False),
        sa.Column("command", sa.String(length=500), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("args", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("env_secret_refs", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("credential_connection_refs", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("egress_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("stdio_runtime_image_ref", sa.String(length=500), nullable=True),
        sa.Column("stdio_command_provenance", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("stdio_package_digest", sa.String(length=255), nullable=True),
        sa.Column("stdio_filesystem_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("stdio_network_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("stdio_resource_limits", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("stdio_max_session_seconds", sa.Integer(), nullable=True),
        sa.Column("stdio_max_output_bytes", sa.Integer(), nullable=True),
        sa.Column("stdio_restart_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("tool_schema_hash", sa.String(length=128), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["activation_target_id"], ["activation_targets.id"], ondelete="SET NULL"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("transport IN ('stdio', 'http', 'sse')", name="ck_mcp_server_configurations_transport"),
        sa.CheckConstraint("runtime_kind IN ('remote_http', 'remote_sse', 'isolated_stdio')", name="ck_mcp_server_configurations_runtime_kind"),
        sa.CheckConstraint("risk_level IN ('safe', 'risky', 'high_risk', 'blocked')", name="ck_mcp_server_configurations_risk_level"),
        sa.CheckConstraint("transport != 'stdio' OR runtime_kind = 'isolated_stdio'", name="ck_mcp_server_configurations_stdio_isolated"),
        sa.CheckConstraint("transport != 'http' OR runtime_kind = 'remote_http'", name="ck_mcp_server_configurations_http_remote"),
        sa.CheckConstraint("transport != 'sse' OR runtime_kind = 'remote_sse'", name="ck_mcp_server_configurations_sse_remote"),
        sa.CheckConstraint("transport != 'stdio' OR command IS NOT NULL", name="ck_mcp_server_configurations_stdio_command"),
        sa.CheckConstraint("transport = 'stdio' OR url IS NOT NULL", name="ck_mcp_server_configurations_remote_url"),
        sa.CheckConstraint("stdio_max_session_seconds IS NULL OR stdio_max_session_seconds >= 1", name="ck_mcp_server_configurations_stdio_max_session_seconds_positive"),
        sa.CheckConstraint("stdio_max_output_bytes IS NULL OR stdio_max_output_bytes >= 1", name="ck_mcp_server_configurations_stdio_max_output_bytes_positive"),
    )
    op.create_index("ix_mcp_server_configurations_tenant_user_enabled", "mcp_server_configurations", ["tenant_id", "user_id", "enabled"], unique=False)
    op.create_index("ix_mcp_server_configurations_tenant_user_risk", "mcp_server_configurations", ["tenant_id", "user_id", "risk_level"], unique=False)

    op.create_table(
        "api_tool_configurations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("activation_target_id", UUID, nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("base_url", sa.String(length=1000), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path_template", sa.String(length=500), nullable=False),
        sa.Column("headers_schema", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("auth_scheme", sa.String(length=80), nullable=False),
        sa.Column("credential_ref", UUID, nullable=True),
        sa.Column("credential_generation", sa.Integer(), nullable=True),
        sa.Column("input_schema", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("output_schema", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("allowed_hosts", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("deny_private_networks", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("redirect_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("allowed_content_types", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("max_request_bytes", sa.Integer(), nullable=False),
        sa.Column("max_response_bytes", sa.Integer(), nullable=False),
        sa.Column("idempotency_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("response_redaction_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("rate_limit", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("timeout_s", sa.Integer(), nullable=False),
        sa.Column("retry_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("error_contract", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["activation_target_id"], ["activation_targets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["credential_ref"], ["credential_connections.id"], ondelete="SET NULL"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')", name="ck_api_tool_configurations_method"),
        sa.CheckConstraint("risk_level IN ('safe', 'risky', 'high_risk', 'blocked')", name="ck_api_tool_configurations_risk_level"),
        sa.CheckConstraint("max_request_bytes >= 1", name="ck_api_tool_configurations_max_request_bytes_positive"),
        sa.CheckConstraint("max_response_bytes >= 1", name="ck_api_tool_configurations_max_response_bytes_positive"),
        sa.CheckConstraint("timeout_s >= 1", name="ck_api_tool_configurations_timeout_s_positive"),
    )
    op.create_index("ix_api_tool_configurations_tenant_user_enabled", "api_tool_configurations", ["tenant_id", "user_id", "enabled"], unique=False)
    op.create_index("ix_api_tool_configurations_tenant_user_risk", "api_tool_configurations", ["tenant_id", "user_id", "risk_level"], unique=False)

    op.create_table(
        "workspace_connectors",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("activation_target_id", UUID, nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("connector_id", sa.String(length=160), nullable=False),
        sa.Column("display_path", sa.String(length=1000), nullable=False),
        sa.Column("host_realpath_hash", sa.String(length=128), nullable=False),
        sa.Column("container_mount_path", sa.String(length=1000), nullable=False),
        sa.Column("backend_mount_path", sa.String(length=1000), nullable=False),
        sa.Column("sandbox_mount_path", sa.String(length=1000), nullable=False),
        sa.Column("connector_root", sa.String(length=1000), nullable=False),
        sa.Column("mount_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("mount_health_status", sa.String(length=40), server_default="unknown", nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("allowlist_rule", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("standing_permission_id", UUID, nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["activation_target_id"], ["activation_targets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["standing_permission_id"], ["standing_permissions.id"], ondelete="SET NULL"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("mode IN ('read_only', 'read_write')", name="ck_workspace_connectors_mode"),
        sa.CheckConstraint("mount_health_status IN ('unknown', 'healthy', 'unhealthy', 'stale')", name="ck_workspace_connectors_mount_health_status"),
        sa.CheckConstraint("mount_generation >= 1", name="ck_workspace_connectors_mount_generation_positive"),
    )
    op.create_index("ix_workspace_connectors_tenant_user_enabled", "workspace_connectors", ["tenant_id", "user_id", "enabled"], unique=False)
    op.create_index("ix_workspace_connectors_tenant_user_connector_id", "workspace_connectors", ["tenant_id", "user_id", "connector_id"], unique=False)

    op.create_table(
        "browser_automation_configurations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("activation_target_id", UUID, nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("allowlisted_domains", JSONB, server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("credential_ref", UUID, nullable=True),
        sa.Column("credential_generation", sa.Integer(), nullable=True),
        sa.Column("runtime_service_name", sa.String(length=160), nullable=False),
        sa.Column("runtime_image_ref", sa.String(length=500), nullable=False),
        sa.Column("runtime_health_check", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("network_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("cookie_scope", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("profile_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("profile_storage_ref", sa.String(length=500), nullable=True),
        sa.Column("profile_retention_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("max_session_seconds", sa.Integer(), nullable=False),
        sa.Column("max_actions_per_run", sa.Integer(), nullable=False),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False),
        sa.Column("cpu_limit", sa.String(length=40), nullable=False),
        sa.Column("memory_limit_mb", sa.Integer(), nullable=False),
        sa.Column("max_trace_bytes", sa.Integer(), nullable=False),
        sa.Column("trace_retention_days", sa.Integer(), nullable=False),
        sa.Column("action_redaction_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("write_confirmation_policy", JSONB, server_default=_json_default(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["activation_target_id"], ["activation_targets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["credential_ref"], ["credential_connections.id"], ondelete="SET NULL"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("max_session_seconds >= 1", name="ck_browser_auto_cfg_max_session_seconds_positive"),
        sa.CheckConstraint("max_actions_per_run >= 1", name="ck_browser_auto_cfg_max_actions_per_run_positive"),
        sa.CheckConstraint("concurrency_limit >= 1", name="ck_browser_automation_configurations_concurrency_limit_positive"),
        sa.CheckConstraint("memory_limit_mb >= 1", name="ck_browser_automation_configurations_memory_limit_mb_positive"),
        sa.CheckConstraint("max_trace_bytes >= 1", name="ck_browser_automation_configurations_max_trace_bytes_positive"),
        sa.CheckConstraint("trace_retention_days >= 1", name="ck_browser_auto_cfg_trace_retention_days_positive"),
    )
    op.create_index("ix_browser_automation_configurations_tenant_user_enabled", "browser_automation_configurations", ["tenant_id", "user_id", "enabled"], unique=False)
    op.create_index("ix_browser_automation_configurations_tenant_user_runtime", "browser_automation_configurations", ["tenant_id", "user_id", "runtime_service_name"], unique=False)

    op.create_table(
        "development_patch_proposals",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("proposal_id", UUID, nullable=False),
        sa.Column("status", sa.String(length=40), server_default="drafted", nullable=False),
        sa.Column("base_git_commit", sa.String(length=80), nullable=False),
        sa.Column("patch_artifact_ref", sa.String(length=500), nullable=False),
        sa.Column("patch_digest", sa.String(length=128), nullable=False),
        sa.Column("test_plan_ref", sa.String(length=500), nullable=False),
        sa.Column("rollback_plan_ref", sa.String(length=500), nullable=False),
        sa.Column("review_checklist_ref", sa.String(length=500), nullable=False),
        sa.Column("apply_check_status", sa.String(length=80), nullable=False),
        sa.Column("working_tree_mutation_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("handoff_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handoff_requested_by", UUID, nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["handoff_requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposal_id"], ["acquisition_proposals.id"], ondelete="CASCADE"),
        *_tenant_user_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", name="uq_development_patch_proposals_proposal"),
        sa.CheckConstraint("status IN ('drafted', 'verifying', 'verified', 'verification_failed', 'handoff_ready', 'handoff_started', 'dismissed', 'superseded')", name="ck_development_patch_proposals_status"),
        sa.CheckConstraint("working_tree_mutation_allowed = false", name="ck_development_patch_proposals_no_worktree_mutation"),
    )
    op.create_index("ix_development_patch_proposals_tenant_user_status", "development_patch_proposals", ["tenant_id", "user_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_development_patch_proposals_tenant_user_status", table_name="development_patch_proposals")
    op.drop_table("development_patch_proposals")
    op.drop_index("ix_browser_automation_configurations_tenant_user_runtime", table_name="browser_automation_configurations")
    op.drop_index("ix_browser_automation_configurations_tenant_user_enabled", table_name="browser_automation_configurations")
    op.drop_table("browser_automation_configurations")
    op.drop_index("ix_workspace_connectors_tenant_user_connector_id", table_name="workspace_connectors")
    op.drop_index("ix_workspace_connectors_tenant_user_enabled", table_name="workspace_connectors")
    op.drop_table("workspace_connectors")
    op.drop_index("ix_api_tool_configurations_tenant_user_risk", table_name="api_tool_configurations")
    op.drop_index("ix_api_tool_configurations_tenant_user_enabled", table_name="api_tool_configurations")
    op.drop_table("api_tool_configurations")
    op.drop_index("ix_mcp_server_configurations_tenant_user_risk", table_name="mcp_server_configurations")
    op.drop_index("ix_mcp_server_configurations_tenant_user_enabled", table_name="mcp_server_configurations")
    op.drop_table("mcp_server_configurations")
    op.drop_index("ix_standing_permissions_tenant_user_target", table_name="standing_permissions")
    op.drop_index("ix_standing_permissions_tenant_user_status", table_name="standing_permissions")
    op.drop_table("standing_permissions")
    op.drop_index("ix_credential_connections_tenant_user_provider", table_name="credential_connections")
    op.drop_index("ix_credential_connections_tenant_user_status", table_name="credential_connections")
    op.drop_table("credential_connections")
    op.drop_index("ix_runtime_planning_issues_tenant_user_source_run", table_name="runtime_planning_issues")
    op.drop_index("ix_runtime_planning_issues_tenant_user_status", table_name="runtime_planning_issues")
    op.drop_table("runtime_planning_issues")
    op.execute("DROP INDEX IF EXISTS uq_acq_journal_snapshot_user")
    op.drop_index("ix_acquisition_journal_entries_tenant_user_kind", table_name="acquisition_journal_entries")
    op.drop_table("acquisition_journal_entries")
    op.drop_index("ix_acquisition_verifications_tenant_user_proposal", table_name="acquisition_verifications")
    op.drop_index("ix_acquisition_verifications_tenant_user_status", table_name="acquisition_verifications")
    op.drop_table("acquisition_verifications")
    op.drop_index("ix_activation_targets_tenant_user_proposal", table_name="activation_targets")
    op.drop_index("ix_activation_targets_tenant_user_status", table_name="activation_targets")
    op.drop_table("activation_targets")
    op.drop_index("ix_acquisition_proposals_tenant_user_gap", table_name="acquisition_proposals")
    op.drop_index("ix_acquisition_proposals_tenant_user_status", table_name="acquisition_proposals")
    op.drop_table("acquisition_proposals")
    op.drop_index("ix_capability_recommendations_tenant_user_gap", table_name="capability_recommendations")
    op.drop_index("ix_capability_recommendations_tenant_user_type", table_name="capability_recommendations")
    op.drop_table("capability_recommendations")
    op.drop_index("ix_exploration_runs_tenant_user_gap", table_name="exploration_runs")
    op.drop_index("ix_exploration_runs_tenant_user_status", table_name="exploration_runs")
    op.drop_table("exploration_runs")
    op.drop_index("ix_capability_gaps_tenant_user_source_run", table_name="capability_gaps")
    op.drop_index("ix_capability_gaps_tenant_user_dedupe", table_name="capability_gaps")
    op.drop_index("ix_capability_gaps_tenant_user_status", table_name="capability_gaps")
    op.drop_table("capability_gaps")
    op.execute("DROP INDEX IF EXISTS ix_acq_idem_tenant_user_created")
    op.execute("DROP INDEX IF EXISTS ix_acq_idem_tenant_user_resource")
    op.execute("DROP TABLE IF EXISTS acquisition_idempotency_records")
