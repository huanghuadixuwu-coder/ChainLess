"""Shared Pydantic contracts for V3 capability acquisition."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RiskLevel = Literal["safe", "risky", "high_risk", "blocked"]
Severity = Literal["low", "medium", "high", "critical"]
TargetType = Literal["mcp_tool", "api_tool", "workspace_connector", "browser_automation", "worker", "skill", "memory"]
ActivationTargetStatus = Literal[
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
]
GapType = Literal[
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
]
ExplorationStrategy = Literal[
    "code_as_action",
    "web_search",
    "web_fetch",
    "existing_tool_chain",
    "mcp_probe",
    "workspace_probe",
    "browser_probe",
    "manual_research",
]
RecommendationType = Literal[
    "mcp_recommendation",
    "api_recommendation",
    "browser_automation_recommendation",
    "workspace_connector_recommendation",
    "credential_recommendation",
    "worker_recommendation",
    "skill_recommendation",
    "memory_recommendation",
    "development_patch_recommendation",
]
ProposalStatus = Literal[
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
]
PlanningIssueType = Literal[
    "planner_missed_existing_tool",
    "planner_missed_worker",
    "planner_missed_skill",
    "planner_missed_memory",
    "wrong_risk_classification",
    "wrong_fallback_choice",
]
CredentialConnectionType = Literal[
    "api_key",
    "oauth",
    "bearer_token",
    "basic_auth",
    "browser_cookie",
    "mcp_env_secret",
    "workspace_os_permission",
    "external_vault_ref",
]


class AcquisitionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PermissionBundle(AcquisitionContract):
    target_id: uuid.UUID | None = None
    target_type: TargetType
    target_version_ref: str | None = None
    permission_scope: dict[str, Any]
    risk_level: RiskLevel
    confirmation_policy: Literal[
        "never_for_safe",
        "before_each_external_write",
        "before_each_browser_submit",
        "before_activation_only",
        "always",
    ]
    credential_scope: Literal[
        "none",
        "user_provided_token",
        "oauth_connection",
        "browser_cookie",
        "system_secret",
    ]
    credential_connection_refs: list[uuid.UUID] = Field(default_factory=list)
    data_scope: Literal[
        "uploaded_files",
        "run_workspace",
        "project_workspace",
        "host_directory",
        "external_service",
        "none",
    ]
    network_scope: Literal["none", "public_web", "allowlisted_domains", "configured_api_base", "arbitrary_network"]
    egress_policy: dict[str, Any]
    write_scope: Literal["none", "artifact_only", "run_workspace", "approved_workspace", "external_service"]
    execution_scope: Literal[
        "code_as_action_temp",
        "mcp_tool",
        "api_tool",
        "browser_session",
        "workspace_connector",
        "worker_run",
        "backend_patch",
    ]
    duration: Literal["one_run", "until_revoked", "expires_at", "per_worker_run_confirmation"]
    expires_at: datetime | None = None
    revocation_plan: dict[str, Any]
    audit_events: list[dict[str, Any]] = Field(default_factory=list)
    approved_snapshot_hash: str | None = None

    @model_validator(mode="after")
    def require_expiry_for_expiring_duration(self) -> "PermissionBundle":
        if self.duration == "expires_at" and self.expires_at is None:
            raise ValueError("expires_at is required when duration is expires_at")
        return self


class CapabilityGapSourceEvidence(AcquisitionContract):
    kind: str
    message: str
    artifact_ref: str | None = None


class ActivationSnapshotInput(AcquisitionContract):
    snapshot_schema_version: str
    proposal_id: uuid.UUID
    proposal_kind: Literal["runtime_activation", "development_patch_proposal"]
    proposal_status: ProposalStatus
    proposal_reason: str
    primary_target_payload: dict[str, Any] | None
    secondary_target_payloads: list[dict[str, Any]] = Field(default_factory=list)
    permission_bundles: list[PermissionBundle]
    verification_result: dict[str, Any]
    rollback_plan: dict[str, Any]
    user_visible_effect: str
    runtime_owner_version_refs: list[dict[str, Any]] = Field(default_factory=list)
    credential_generations: list[dict[str, Any]] = Field(default_factory=list)
    egress_policy_snapshots: list[dict[str, Any]] = Field(default_factory=list)


class ActivationStateMachineContract(AcquisitionContract):
    proposal_id: uuid.UUID
    status: ProposalStatus
    verified_snapshot_hash: str | None = None
    approved_snapshot_hash: str | None = None
    activated_snapshot_hash: str | None = None


class ActivationTargetContract(AcquisitionContract):
    target_type: TargetType
    target_name: str
    target_owner: str
    target_payload: dict[str, Any]
    permission_bundle: PermissionBundle
    verification_plan: dict[str, Any]
    rollback_plan: dict[str, Any]
    activation_status: ActivationTargetStatus = "draft"
    activation_result: dict[str, Any] = Field(default_factory=dict)
    activated_resource_ref: dict[str, Any] | None = None


class CapabilityGapRequest(AcquisitionContract):
    source_kind: str
    source_run_id: str
    conversation_id: uuid.UUID | None = None
    dedupe_key: str
    title: str
    description: str
    gap_type: GapType
    severity: Severity
    source_evidence: list[CapabilityGapSourceEvidence]
    evidence: dict[str, Any]


class CapabilityGapResponse(CapabilityGapRequest):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int
    created_at: datetime
    updated_at: datetime


class ExplorationRunRequest(AcquisitionContract):
    gap_id: uuid.UUID
    source_run_id: str
    risk_level: RiskLevel
    approval_id: uuid.UUID | None = None
    strategy: ExplorationStrategy


class ExplorationRunResponse(ExplorationRunRequest):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    tool_events: list[dict[str, Any]] = Field(default_factory=list)
    script_ref: str | None = None
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    stdout_excerpt: str | None = None
    stderr_excerpt: str | None = None
    result_summary: str | None = None
    failure_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CapabilityRecommendationRequest(AcquisitionContract):
    gap_id: uuid.UUID
    exploration_run_id: uuid.UUID | None = None
    recommendation_type: RecommendationType
    title: str
    summary: str
    reason: str
    evidence: dict[str, Any]
    risk_level: RiskLevel
    expected_value: dict[str, Any]
    required_permissions: dict[str, Any]
    candidate_targets: list[dict[str, Any]]


class CapabilityRecommendationResponse(CapabilityRecommendationRequest):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AcquisitionProposalRequest(AcquisitionContract):
    proposal_kind: Literal["runtime_activation", "development_patch_proposal"]
    gap_id: uuid.UUID
    recommendation_id: uuid.UUID
    title: str
    reason: str
    evidence: dict[str, Any]
    risk_level: RiskLevel
    permission_bundle: PermissionBundle
    primary_target: ActivationTargetContract | None = None
    secondary_targets: list[ActivationTargetContract] = Field(default_factory=list)
    development_handoff: dict[str, Any] | None = None
    verification_plan: dict[str, Any]
    rollback_plan: dict[str, Any]
    user_visible_effect: str

    @model_validator(mode="after")
    def validate_target_shape(self) -> "AcquisitionProposalRequest":
        if self.proposal_kind == "runtime_activation" and self.primary_target is None:
            raise ValueError("runtime_activation proposals require primary_target")
        if self.proposal_kind == "development_patch_proposal" and self.primary_target is not None:
            raise ValueError("development_patch_proposal cannot include a runtime primary_target")
        return self


class AcquisitionProposalResponse(AcquisitionProposalRequest):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    status: ProposalStatus
    approval_history: list[dict[str, Any]]
    activation_snapshot_hash: str | None = None
    snapshot_created_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AcquisitionVerificationRequest(AcquisitionContract):
    proposal_id: uuid.UUID
    target_id: uuid.UUID | None = None
    verification_kind: str
    input_fixture: dict[str, Any]
    expected_result: dict[str, Any]


class AcquisitionVerificationResponse(AcquisitionVerificationRequest):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    actual_result: dict[str, Any]
    artifact_refs: list[dict[str, Any]]
    error_code: str | None = None
    error_message: str | None = None
    verified_snapshot_hash: str | None = None
    verified_snapshot_payload: dict[str, Any]
    started_at: datetime | None = None
    completed_at: datetime | None = None


class JournalEntryContract(AcquisitionContract):
    id: uuid.UUID
    entry_kind: str
    subject_ref: dict[str, Any]
    rendered_markdown: str
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AcquisitionJournalView(AcquisitionContract):
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    generated_at: datetime
    entries: list[JournalEntryContract]
    rendered_markdown: str


class RuntimePlanningIssueRequest(AcquisitionContract):
    source_run_id: str
    conversation_id: uuid.UUID | None = None
    issue_type: PlanningIssueType
    available_capability_ref: dict[str, Any]
    missed_signal: str
    planner_decision_summary: str
    expected_decision_summary: str
    severity: Severity
    evidence: dict[str, Any]


class RuntimePlanningIssueResponse(RuntimePlanningIssueRequest):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime


class CredentialConnectionCreateRequest(AcquisitionContract):
    name: str
    provider: str
    connection_type: CredentialConnectionType
    credential_kind: str
    secret_storage_kind: str
    secret_value: str | None = Field(default=None, exclude=True)
    scopes: list[str] = Field(default_factory=list)
    allowed_target_types: list[TargetType] = Field(default_factory=list)
    allowed_target_refs: list[dict[str, Any]] = Field(default_factory=list)
    metadata_redacted: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


class CredentialConnectionResponse(AcquisitionContract):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    provider: str
    connection_type: CredentialConnectionType
    credential_kind: str
    secret_storage_kind: str
    secret_generation: int
    secret_ref_present: bool
    scopes: list[str]
    allowed_target_types: list[TargetType]
    allowed_target_refs: list[dict[str, Any]]
    status: str
    metadata_redacted: dict[str, Any]
    expires_at: datetime | None = None
    last_validated_at: datetime | None = None
    rotation_required_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApprovalRequest(AcquisitionContract):
    proposal_id: uuid.UUID
    approved_snapshot_hash: str
    decision: Literal["approve", "reject"]
    reason: str | None = None


class ActivationRequest(AcquisitionContract):
    proposal_id: uuid.UUID
    approved_snapshot_hash: str
    verification_id: uuid.UUID
    target_ids: list[uuid.UUID]


class StandingPermissionRequest(AcquisitionContract):
    proposal_id: uuid.UUID
    target_id: uuid.UUID
    target_type: TargetType
    permission_scope: dict[str, Any]
    risk_level: RiskLevel
    duration: Literal["one_run", "until_revoked", "expires_at", "per_worker_run_confirmation"]
    approved_snapshot_hash: str
    expires_at: datetime | None = None
    revocation_plan: dict[str, Any]

    @model_validator(mode="after")
    def require_expiry_for_expiring_duration(self) -> "StandingPermissionRequest":
        if self.duration == "expires_at" and self.expires_at is None:
            raise ValueError("expires_at is required when duration is expires_at")
        return self


class StandingPermissionResponse(StandingPermissionRequest):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    revoked_at: datetime | None = None
    renewal_required_at: datetime | None = None
    audit_events: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class MCPServerConfigurationContract(AcquisitionContract):
    name: str
    transport: Literal["stdio", "http", "sse"]
    runtime_kind: Literal["remote_http", "remote_sse", "isolated_stdio"]
    command: str | None = None
    url: str | None = None
    args: list[str] = Field(default_factory=list)
    env_secret_refs: list[dict[str, Any]] = Field(default_factory=list)
    credential_connection_refs: list[uuid.UUID] = Field(default_factory=list)
    egress_policy: dict[str, Any]
    stdio_runtime_image_ref: str | None = None
    stdio_command_provenance: dict[str, Any] = Field(default_factory=dict)
    stdio_package_digest: str | None = None
    stdio_filesystem_policy: dict[str, Any] = Field(default_factory=dict)
    stdio_network_policy: dict[str, Any] = Field(default_factory=dict)
    stdio_resource_limits: dict[str, Any] = Field(default_factory=dict)
    stdio_max_session_seconds: int | None = Field(default=None, ge=1)
    stdio_max_output_bytes: int | None = Field(default=None, ge=1)
    stdio_restart_policy: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False
    risk_level: RiskLevel
    tool_schema_hash: str | None = None
    last_verified_at: datetime | None = None

    @model_validator(mode="after")
    def validate_transport_shape(self) -> "MCPServerConfigurationContract":
        expected_runtime = {
            "stdio": "isolated_stdio",
            "http": "remote_http",
            "sse": "remote_sse",
        }[self.transport]
        if self.runtime_kind != expected_runtime:
            raise ValueError(f"{self.transport} transport requires {expected_runtime} runtime_kind")
        if self.transport == "stdio" and self.command is None:
            raise ValueError("stdio transport requires command")
        if self.transport in {"http", "sse"} and self.url is None:
            raise ValueError(f"{self.transport} transport requires url")
        return self


class APIToolConfigurationContract(AcquisitionContract):
    name: str
    tool_name: str
    base_url: str
    method: Literal["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]
    path_template: str
    headers_schema: dict[str, Any]
    auth_scheme: str
    credential_ref: uuid.UUID | None = None
    credential_generation: int | None = None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    allowed_hosts: list[str]
    deny_private_networks: bool = True
    redirect_policy: dict[str, Any]
    allowed_content_types: list[str]
    max_request_bytes: int = Field(ge=1)
    max_response_bytes: int = Field(ge=1)
    idempotency_policy: dict[str, Any]
    response_redaction_policy: dict[str, Any]
    rate_limit: dict[str, Any]
    timeout_s: int = Field(ge=1)
    retry_policy: dict[str, Any]
    error_contract: dict[str, Any]
    enabled: bool = False
    risk_level: RiskLevel
    last_verified_at: datetime | None = None


class WorkspaceConnectorContract(AcquisitionContract):
    name: str
    connector_id: str
    display_path: str
    container_mount_path: str
    backend_mount_path: str
    sandbox_mount_path: str
    connector_root: str
    mount_generation: int = Field(ge=1)
    mount_health_status: Literal["unknown", "healthy", "unhealthy", "stale"]
    mode: Literal["read_only", "read_write"]
    allowlist_rule: dict[str, Any]
    standing_permission_id: uuid.UUID | None = None
    enabled: bool = False
    expires_at: datetime | None = None
    last_verified_at: datetime | None = None


class BrowserAutomationConfigurationContract(AcquisitionContract):
    name: str
    allowlisted_domains: list[str]
    credential_ref: uuid.UUID | None = None
    credential_generation: int | None = None
    runtime_service_name: str
    runtime_image_ref: str
    runtime_health_check: dict[str, Any]
    network_policy: dict[str, Any]
    cookie_scope: dict[str, Any]
    profile_policy: dict[str, Any]
    profile_storage_ref: str | None = None
    profile_retention_policy: dict[str, Any]
    max_session_seconds: int = Field(ge=1)
    max_actions_per_run: int = Field(ge=1)
    concurrency_limit: int = Field(ge=1)
    cpu_limit: str
    memory_limit_mb: int = Field(ge=1)
    max_trace_bytes: int = Field(ge=1)
    trace_retention_days: int = Field(ge=1)
    action_redaction_policy: dict[str, Any]
    write_confirmation_policy: dict[str, Any]
    enabled: bool = False
    last_verified_at: datetime | None = None


class DevelopmentPatchProposalContract(AcquisitionContract):
    proposal_id: uuid.UUID
    status: Literal[
        "drafted",
        "verifying",
        "verified",
        "verification_failed",
        "handoff_ready",
        "handoff_started",
        "dismissed",
        "superseded",
    ]
    base_git_commit: str
    patch_artifact_ref: str
    patch_digest: str
    test_plan_ref: str
    rollback_plan_ref: str
    review_checklist_ref: str
    apply_check_status: str
    working_tree_mutation_allowed: bool = False
    handoff_requested_at: datetime | None = None
    handoff_requested_by: uuid.UUID | None = None

    @model_validator(mode="after")
    def reject_worktree_mutation(self) -> "DevelopmentPatchProposalContract":
        if self.working_tree_mutation_allowed:
            raise ValueError("development patch handoff cannot mutate the working tree")
        return self
