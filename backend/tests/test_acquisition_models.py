"""V3 acquisition model and migration contract tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models import __all__ as model_exports
from app.models.base import Base
from app.models.acquisition import (
    APIToolConfiguration,
    AcquisitionIdempotencyRecord,
    AcquisitionJournalEntry,
    AcquisitionProposal,
    AcquisitionVerification,
    ActivationTarget,
    BrowserAutomationConfiguration,
    CapabilityGap,
    CapabilityRecommendation,
    CredentialConnection,
    DevelopmentPatchProposal,
    ExplorationRun,
    MCPServerConfiguration,
    PROPOSAL_STATUSES,
    RuntimePlanningIssue,
    StandingPermission,
    WorkspaceConnector,
)


ACQUISITION_MODELS = (
    AcquisitionIdempotencyRecord,
    CapabilityGap,
    ExplorationRun,
    CapabilityRecommendation,
    AcquisitionProposal,
    ActivationTarget,
    AcquisitionVerification,
    AcquisitionJournalEntry,
    RuntimePlanningIssue,
    CredentialConnection,
    StandingPermission,
    MCPServerConfiguration,
    APIToolConfiguration,
    WorkspaceConnector,
    BrowserAutomationConfiguration,
    DevelopmentPatchProposal,
)

ACQUISITION_TABLES = {
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
}


def _constraint_sql(model: type) -> str:
    return "\n".join(
        str(constraint.sqltext)
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    )


def _load_migration_module():
    migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "0012_add_capability_acquisition_layer.py"
    spec = importlib.util.spec_from_file_location("migration_0012", migration_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_acquisition_models_have_required_columns() -> None:
    expected_columns = {
        AcquisitionIdempotencyRecord: {
            "tenant_id",
            "user_id",
            "scope",
            "idempotency_key",
            "resource_type",
            "resource_id",
            "metadata",
            "created_at",
        },
        CapabilityGap: {
            "tenant_id",
            "user_id",
            "source_kind",
            "source_run_id",
            "conversation_id",
            "dedupe_key",
            "title",
            "description",
            "gap_type",
            "severity",
            "status",
            "source_evidence",
            "evidence",
            "first_seen_at",
            "last_seen_at",
            "occurrence_count",
        },
        ExplorationRun: {
            "tenant_id",
            "user_id",
            "gap_id",
            "source_run_id",
            "risk_level",
            "approval_id",
            "status",
            "strategy",
            "tool_events",
            "script_ref",
            "artifact_refs",
            "stdout_excerpt",
            "stderr_excerpt",
            "result_summary",
            "failure_reason",
            "started_at",
            "completed_at",
        },
        CapabilityRecommendation: {
            "tenant_id",
            "user_id",
            "gap_id",
            "exploration_run_id",
            "recommendation_type",
            "title",
            "summary",
            "reason",
            "evidence",
            "risk_level",
            "expected_value",
            "required_permissions",
            "candidate_targets",
        },
        AcquisitionProposal: {
            "tenant_id",
            "user_id",
            "proposal_kind",
            "gap_id",
            "recommendation_id",
            "title",
            "reason",
            "evidence",
            "status",
            "risk_level",
            "permission_bundle",
            "primary_target",
            "secondary_targets",
            "development_handoff",
            "verification_plan",
            "rollback_plan",
            "user_visible_effect",
            "approval_history",
            "activation_snapshot_hash",
            "snapshot_created_at",
        },
        ActivationTarget: {
            "tenant_id",
            "user_id",
            "proposal_id",
            "target_type",
            "target_name",
            "target_owner",
            "target_payload",
            "permission_bundle",
            "verification_plan",
            "rollback_plan",
            "activation_status",
            "activation_result",
            "activated_resource_ref",
        },
        AcquisitionVerification: {
            "tenant_id",
            "user_id",
            "proposal_id",
            "target_id",
            "status",
            "verification_kind",
            "input_fixture",
            "expected_result",
            "actual_result",
            "artifact_refs",
            "error_code",
            "error_message",
            "verified_snapshot_hash",
            "verified_snapshot_payload",
            "started_at",
            "completed_at",
        },
        AcquisitionJournalEntry: {
            "tenant_id",
            "user_id",
            "entry_kind",
            "subject_ref",
            "rendered_markdown",
            "source_refs",
        },
        RuntimePlanningIssue: {
            "tenant_id",
            "user_id",
            "source_run_id",
            "conversation_id",
            "issue_type",
            "available_capability_ref",
            "missed_signal",
            "planner_decision_summary",
            "expected_decision_summary",
            "severity",
            "status",
            "evidence",
        },
        CredentialConnection: {
            "tenant_id",
            "user_id",
            "name",
            "provider",
            "connection_type",
            "credential_kind",
            "secret_storage_kind",
            "secret_ref",
            "secret_generation",
            "scopes",
            "allowed_target_types",
            "allowed_target_refs",
            "status",
            "metadata_redacted",
            "expires_at",
            "last_validated_at",
            "rotation_required_at",
            "revoked_at",
        },
        StandingPermission: {
            "tenant_id",
            "user_id",
            "proposal_id",
            "target_id",
            "target_type",
            "permission_scope",
            "risk_level",
            "duration",
            "approved_snapshot_hash",
            "status",
            "expires_at",
            "revoked_at",
            "renewal_required_at",
            "revocation_plan",
            "audit_events",
        },
        MCPServerConfiguration: {
            "tenant_id",
            "user_id",
            "activation_target_id",
            "name",
            "transport",
            "runtime_kind",
            "command",
            "url",
            "args",
            "env_secret_refs",
            "credential_connection_refs",
            "egress_policy",
            "stdio_runtime_image_ref",
            "stdio_command_provenance",
            "stdio_package_digest",
            "stdio_filesystem_policy",
            "stdio_network_policy",
            "stdio_resource_limits",
            "stdio_max_session_seconds",
            "stdio_max_output_bytes",
            "stdio_restart_policy",
            "enabled",
            "risk_level",
            "tool_schema_hash",
            "last_verified_at",
            "last_connected_at",
            "disabled_at",
        },
        APIToolConfiguration: {
            "tenant_id",
            "user_id",
            "activation_target_id",
            "name",
            "base_url",
            "method",
            "path_template",
            "headers_schema",
            "auth_scheme",
            "credential_ref",
            "credential_generation",
            "input_schema",
            "output_schema",
            "allowed_hosts",
            "deny_private_networks",
            "redirect_policy",
            "allowed_content_types",
            "max_request_bytes",
            "max_response_bytes",
            "idempotency_policy",
            "response_redaction_policy",
            "rate_limit",
            "timeout_s",
            "retry_policy",
            "error_contract",
            "enabled",
            "risk_level",
            "last_verified_at",
        },
        WorkspaceConnector: {
            "tenant_id",
            "user_id",
            "activation_target_id",
            "name",
            "connector_id",
            "display_path",
            "host_realpath_hash",
            "container_mount_path",
            "backend_mount_path",
            "sandbox_mount_path",
            "connector_root",
            "mount_generation",
            "mount_health_status",
            "mode",
            "allowlist_rule",
            "standing_permission_id",
            "enabled",
            "expires_at",
            "last_verified_at",
        },
        BrowserAutomationConfiguration: {
            "tenant_id",
            "user_id",
            "activation_target_id",
            "name",
            "allowlisted_domains",
            "credential_ref",
            "credential_generation",
            "runtime_service_name",
            "runtime_image_ref",
            "runtime_health_check",
            "network_policy",
            "cookie_scope",
            "profile_policy",
            "profile_storage_ref",
            "profile_retention_policy",
            "max_session_seconds",
            "max_actions_per_run",
            "concurrency_limit",
            "cpu_limit",
            "memory_limit_mb",
            "max_trace_bytes",
            "trace_retention_days",
            "action_redaction_policy",
            "write_confirmation_policy",
            "enabled",
            "last_verified_at",
        },
        DevelopmentPatchProposal: {
            "tenant_id",
            "user_id",
            "proposal_id",
            "status",
            "base_git_commit",
            "patch_artifact_ref",
            "patch_digest",
            "test_plan_ref",
            "rollback_plan_ref",
            "review_checklist_ref",
            "apply_check_status",
            "working_tree_mutation_allowed",
            "handoff_requested_at",
            "handoff_requested_by",
        },
    }

    assert set(expected_columns) == set(ACQUISITION_MODELS)
    for model, columns in expected_columns.items():
        assert columns.issubset(set(model.__table__.c.keys())), model.__name__


def test_acquisition_user_scope_is_required_for_private_records() -> None:
    for model in ACQUISITION_MODELS:
        table = model.__table__
        assert table.c.tenant_id.nullable is False, model.__name__
        assert table.c.user_id.nullable is False, model.__name__
        assert any(fk.column.table.name == "tenants" for fk in table.c.tenant_id.foreign_keys), model.__name__
        assert any(fk.column.table.name == "users" for fk in table.c.user_id.foreign_keys), model.__name__


def test_activation_target_rejects_missing_primary_target_fields() -> None:
    table = ActivationTarget.__table__
    for column_name in (
        "target_type",
        "target_name",
        "target_owner",
        "target_payload",
        "permission_bundle",
        "verification_plan",
        "rollback_plan",
    ):
        assert table.c[column_name].nullable is False

    constraint_sql = _constraint_sql(ActivationTarget)
    assert "target_type IN" in constraint_sql
    assert "development_patch_proposal" in constraint_sql


def test_development_patch_proposal_cannot_be_runtime_active() -> None:
    patch_constraint_sql = _constraint_sql(DevelopmentPatchProposal)
    proposal_constraint_sql = _constraint_sql(AcquisitionProposal)

    assert "activated" not in patch_constraint_sql
    assert "partial_activation" not in patch_constraint_sql
    assert "working_tree_mutation_allowed = false" in patch_constraint_sql
    assert "proposal_kind != 'development_patch_proposal' OR primary_target IS NULL" in proposal_constraint_sql
    assert "proposal_kind != 'development_patch_proposal' OR status IN" in proposal_constraint_sql


def test_runtime_proposal_statuses_include_plan_mandated_activation_flow() -> None:
    plan_order = (
        "drafted",
        "verification_requested",
        "verifying",
        "verified",
        "activation_requested",
        "activation_approved",
        "activating",
        "activated",
    )
    assert all(status in PROPOSAL_STATUSES for status in plan_order)
    assert [PROPOSAL_STATUSES.index(status) for status in plan_order] == sorted(
        PROPOSAL_STATUSES.index(status) for status in plan_order
    )

    proposal_constraint_sql = _constraint_sql(AcquisitionProposal)
    assert "verification_requested" in proposal_constraint_sql
    assert "activating" in proposal_constraint_sql

    migration_source = Path(__file__).parents[1].joinpath(
        "alembic",
        "versions",
        "0012_add_capability_acquisition_layer.py",
    ).read_text()
    assert "verification_requested" in migration_source
    assert "activating" in migration_source


def test_runtime_configuration_constraints_cover_transport_pairs_and_positive_limits() -> None:
    mcp_constraint_sql = _constraint_sql(MCPServerConfiguration)
    api_constraint_sql = _constraint_sql(APIToolConfiguration)
    workspace_constraint_sql = _constraint_sql(WorkspaceConnector)
    browser_constraint_sql = _constraint_sql(BrowserAutomationConfiguration)

    assert "transport != 'http' OR runtime_kind = 'remote_http'" in mcp_constraint_sql
    assert "transport != 'sse' OR runtime_kind = 'remote_sse'" in mcp_constraint_sql
    assert "stdio_max_session_seconds IS NULL OR stdio_max_session_seconds >= 1" in mcp_constraint_sql
    assert "stdio_max_output_bytes IS NULL OR stdio_max_output_bytes >= 1" in mcp_constraint_sql

    assert "max_request_bytes >= 1" in api_constraint_sql
    assert "max_response_bytes >= 1" in api_constraint_sql
    assert "timeout_s >= 1" in api_constraint_sql
    assert "mount_generation >= 1" in workspace_constraint_sql

    for column_name in (
        "max_session_seconds",
        "max_actions_per_run",
        "concurrency_limit",
        "memory_limit_mb",
        "max_trace_bytes",
        "trace_retention_days",
    ):
        assert f"{column_name} >= 1" in browser_constraint_sql


def test_acquisition_tables_are_registered_in_base_metadata() -> None:
    assert ACQUISITION_TABLES.issubset(set(Base.metadata.tables))


def test_acquisition_constraint_and_index_names_fit_postgres_identifier_limit() -> None:
    overlong_names = []
    for model in ACQUISITION_MODELS:
        table = model.__table__
        explicit_names = [
            *(constraint.name for constraint in table.constraints),
            *(index.name for index in table.indexes),
        ]
        overlong_names.extend(name for name in explicit_names if name is not None and len(name) > 63)

    assert overlong_names == []


def test_migration_created_indexes_include_user_status_lookup_paths() -> None:
    migration = _load_migration_module()
    assert migration.down_revision == "0011"
    assert set(migration.ACQUISITION_TABLES) == ACQUISITION_TABLES

    metadata_index_names = {
        index.name
        for table_name in ACQUISITION_TABLES
        for index in Base.metadata.tables[table_name].indexes
    }
    assert set(migration.USER_STATUS_INDEXES).issubset(metadata_index_names)


def test_gap_dedupe_unique_upsert_columns_exist() -> None:
    unique = next(
        constraint
        for constraint in CapabilityGap.__table__.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name == "uq_capability_gaps_user_gap_dedupe"
    )
    assert tuple(column.name for column in unique.columns) == ("tenant_id", "user_id", "gap_type", "dedupe_key")

    migration = _load_migration_module()
    assert tuple(migration.GAP_DEDUPE_UNIQUE_COLUMNS) == ("tenant_id", "user_id", "gap_type", "dedupe_key")


def test_acquisition_idempotency_records_have_durable_authority_constraints() -> None:
    table = AcquisitionIdempotencyRecord.__table__
    unique = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name == "uq_acq_idem_scope_key"
    )
    assert tuple(column.name for column in unique.columns) == ("tenant_id", "user_id", "scope", "idempotency_key")
    assert table.c.resource_type.nullable is False
    assert table.c.resource_id.nullable is False
    assert table.c.metadata.nullable is False

    migration_source = Path(__file__).parents[1].joinpath(
        "alembic",
        "versions",
        "0012_add_capability_acquisition_layer.py",
    ).read_text()
    assert "acquisition_idempotency_records" in migration_source
    assert "uq_acq_idem_scope_key" in migration_source
    assert "ix_acq_idem_tenant_user_resource" in migration_source


def test_capability_gap_persists_first_class_source_evidence() -> None:
    table = CapabilityGap.__table__
    constraint_sql = _constraint_sql(CapabilityGap)
    migration_source = Path(__file__).parents[1].joinpath(
        "alembic",
        "versions",
        "0012_add_capability_acquisition_layer.py",
    ).read_text()

    assert table.c.source_evidence.nullable is False
    assert "source_evidence" in table.c
    assert "octet_length(source_evidence::text) <= 16384" in constraint_sql
    assert 'sa.Column("source_evidence", JSONB' in migration_source
    assert "_json_default(\"'[]'::jsonb\")" in migration_source
    assert "ck_capability_gaps_source_evidence_size" in migration_source


def test_models_all_exports_acquisition_models() -> None:
    expected_exports = {model.__name__ for model in ACQUISITION_MODELS}
    assert expected_exports.issubset(set(model_exports))
