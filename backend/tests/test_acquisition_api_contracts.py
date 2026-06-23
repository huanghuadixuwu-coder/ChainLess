"""V3 acquisition Pydantic serialization contract tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.acquisition.schemas import (
    APIToolConfigurationContract,
    AcquisitionJournalView,
    AcquisitionProposalRequest,
    AcquisitionProposalResponse,
    ActivationSnapshotInput,
    ActivationStateMachineContract,
    ActivationTargetContract,
    BrowserAutomationConfigurationContract,
    CapabilityGapRequest,
    CapabilityGapSourceEvidence,
    CapabilityGapResponse,
    CapabilityRecommendationRequest,
    CredentialConnectionCreateRequest,
    CredentialConnectionResponse,
    ExplorationRunRequest,
    JournalEntryContract,
    MCPServerConfigurationContract,
    PermissionBundle,
    RuntimePlanningIssueRequest,
    StandingPermissionRequest,
    WorkspaceConnectorContract,
)


def _permission_bundle(target_type: str = "mcp_tool") -> PermissionBundle:
    return PermissionBundle(
        target_type=target_type,
        permission_scope={"domains": ["api.example.com"]},
        risk_level="risky",
        confirmation_policy="before_activation_only",
        credential_scope="oauth_connection",
        credential_connection_refs=[uuid.uuid4()],
        data_scope="external_service",
        network_scope="allowlisted_domains",
        egress_policy={"allowed_hosts": ["api.example.com"]},
        write_scope="none",
        execution_scope="mcp_tool",
        duration="one_run",
        revocation_plan={"action": "disable target"},
        audit_events=[{"event": "approved"}],
    )


def _target(target_type: str = "mcp_tool", name: str = "train-query") -> ActivationTargetContract:
    return ActivationTargetContract(
        target_type=target_type,
        target_name=name,
        target_owner="core/tools/mcp",
        target_payload={"server": name, "transport": "stdio"},
        permission_bundle=_permission_bundle(target_type),
        verification_plan={"fixture": "minimal call"},
        rollback_plan={"action": "disable"},
    )


def test_capability_gap_contract_serializes_source_evidence() -> None:
    gap = CapabilityGapResponse(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        source_kind="tool_failure",
        source_run_id="run-123",
        conversation_id=uuid.uuid4(),
        dedupe_key="missing_mcp:train:tool_failure",
        title="Missing train query capability",
        description="No durable train query tool is available.",
        gap_type="missing_mcp",
        severity="high",
        status="detected",
        source_evidence=[
            CapabilityGapSourceEvidence(
                kind="tool_error",
                message="public source unstable",
                artifact_ref="artifact://trace-1",
            )
        ],
        evidence={"exploration_run_id": str(uuid.uuid4())},
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        occurrence_count=2,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    payload = gap.model_dump(mode="json")

    assert payload["source_run_id"] == "run-123"
    assert payload["source_evidence"][0]["artifact_ref"] == "artifact://trace-1"
    assert "source_evidence" not in payload["evidence"]
    assert payload["occurrence_count"] == 2


def test_capability_gap_source_evidence_rejects_malformed_entries() -> None:
    with pytest.raises(ValidationError):
        CapabilityGapSourceEvidence(kind="tool_error")


def test_acquisition_proposal_contract_serializes_composite_target() -> None:
    proposal = AcquisitionProposalResponse(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        proposal_kind="runtime_activation",
        gap_id=uuid.uuid4(),
        recommendation_id=uuid.uuid4(),
        title="Activate train query MCP",
        reason="Public sources were unstable.",
        evidence={"exploration_run_id": str(uuid.uuid4())},
        status="activation_requested",
        risk_level="risky",
        permission_bundle=_permission_bundle(),
        primary_target=_target(),
        secondary_targets=[_target("worker", "train-query-worker"), _target("skill", "ticket-risk-skill")],
        development_handoff=None,
        verification_plan={"docker": "pytest fixture"},
        rollback_plan={"primary": "disable mcp"},
        user_visible_effect="Train queries become available after approval.",
        approval_history=[{"decision": "requested"}],
        activation_snapshot_hash="sha256:proposal",
        snapshot_created_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    payload = proposal.model_dump(mode="json")

    assert payload["primary_target"]["target_type"] == "mcp_tool"
    assert [target["target_type"] for target in payload["secondary_targets"]] == ["worker", "skill"]
    assert payload["permission_bundle"]["duration"] == "one_run"


def test_acquisition_proposal_contract_rejects_malformed_permission_bundle() -> None:
    with pytest.raises(ValidationError):
        AcquisitionProposalRequest(
            proposal_kind="runtime_activation",
            gap_id=uuid.uuid4(),
            recommendation_id=uuid.uuid4(),
            title="Activate train query MCP",
            reason="Public sources were unstable.",
            evidence={"exploration_run_id": str(uuid.uuid4())},
            risk_level="risky",
            permission_bundle={"target_type": "mcp_tool"},
            primary_target=_target(),
            verification_plan={"docker": "pytest fixture"},
            rollback_plan={"primary": "disable mcp"},
            user_visible_effect="Train queries become available after approval.",
        )


def test_acquisition_proposal_contract_rejects_malformed_target_dicts() -> None:
    with pytest.raises(ValidationError):
        AcquisitionProposalRequest(
            proposal_kind="runtime_activation",
            gap_id=uuid.uuid4(),
            recommendation_id=uuid.uuid4(),
            title="Activate train query MCP",
            reason="Public sources were unstable.",
            evidence={"exploration_run_id": str(uuid.uuid4())},
            risk_level="risky",
            permission_bundle=_permission_bundle(),
            primary_target={"target_type": "mcp_tool"},
            verification_plan={"docker": "pytest fixture"},
            rollback_plan={"primary": "disable mcp"},
            user_visible_effect="Train queries become available after approval.",
        )

    with pytest.raises(ValidationError):
        AcquisitionProposalRequest(
            proposal_kind="runtime_activation",
            gap_id=uuid.uuid4(),
            recommendation_id=uuid.uuid4(),
            title="Activate train query MCP",
            reason="Public sources were unstable.",
            evidence={"exploration_run_id": str(uuid.uuid4())},
            risk_level="risky",
            permission_bundle=_permission_bundle(),
            primary_target=_target(),
            secondary_targets=[{"target_type": "worker"}],
            verification_plan={"docker": "pytest fixture"},
            rollback_plan={"primary": "disable mcp"},
            user_visible_effect="Train queries become available after approval.",
        )


def test_activation_state_machine_contract_serializes_verified_hash_and_approval_hash() -> None:
    proposal_id = uuid.uuid4()
    state = ActivationStateMachineContract(
        proposal_id=proposal_id,
        status="activation_approved",
        verified_snapshot_hash="sha256:verified",
        approved_snapshot_hash="sha256:approved",
        activated_snapshot_hash=None,
    )

    payload = state.model_dump(mode="json")

    assert payload["proposal_id"] == str(proposal_id)
    assert payload["verified_snapshot_hash"] == "sha256:verified"
    assert payload["approved_snapshot_hash"] == "sha256:approved"


def test_activation_state_machine_contract_accepts_plan_mandated_runtime_states() -> None:
    proposal_id = uuid.uuid4()

    for status in (
        "drafted",
        "verification_requested",
        "verifying",
        "verified",
        "activation_requested",
        "activation_approved",
        "activating",
        "activated",
    ):
        state = ActivationStateMachineContract(proposal_id=proposal_id, status=status)
        assert state.status == status

    with pytest.raises(ValidationError):
        ActivationStateMachineContract(proposal_id=proposal_id, status="pending_activation")


def test_activation_target_contract_rejects_invalid_activation_status() -> None:
    target = _target()
    assert target.activation_status == "draft"

    with pytest.raises(ValidationError):
        ActivationTargetContract(
            target_type="mcp_tool",
            target_name="train-query",
            target_owner="core/tools/mcp",
            target_payload={"server": "train-query", "transport": "stdio"},
            permission_bundle=_permission_bundle(),
            verification_plan={"fixture": "minimal call"},
            rollback_plan={"action": "disable"},
            activation_status="pending_activation",
        )


def test_activation_snapshot_contract_has_required_hash_inputs() -> None:
    credential_id = uuid.uuid4()
    snapshot = ActivationSnapshotInput(
        snapshot_schema_version="v3.activation_snapshot.v1",
        proposal_id=uuid.uuid4(),
        proposal_kind="runtime_activation",
        proposal_status="verified",
        proposal_reason="Weather scraping is unstable.",
        primary_target_payload={"target_type": "api_tool", "name": "weather-api"},
        secondary_target_payloads=[{"target_type": "worker", "name": "weather-worker"}],
        permission_bundles=[_permission_bundle("api_tool")],
        verification_result={"status": "passed", "artifact_ref": "artifact://verification"},
        rollback_plan={"action": "disable api tool"},
        user_visible_effect="Weather API calls become available.",
        runtime_owner_version_refs=[{"owner": "core/tools/api", "version": "v1"}],
        credential_generations=[{"credential_connection_id": str(credential_id), "secret_generation": 3}],
        egress_policy_snapshots=[{"allowed_hosts": ["weather.example.com"]}],
    )

    payload = snapshot.model_dump(mode="json")

    assert payload["snapshot_schema_version"] == "v3.activation_snapshot.v1"
    assert payload["credential_generations"][0]["secret_generation"] == 3
    assert payload["egress_policy_snapshots"][0]["allowed_hosts"] == ["weather.example.com"]


def test_acquisition_journal_view_uses_typed_entries() -> None:
    entry_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    updated_at = datetime.now(timezone.utc)
    view = AcquisitionJournalView(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        generated_at=datetime.now(timezone.utc),
        entries=[
            {
                "id": entry_id,
                "entry_kind": "proposal_created",
                "subject_ref": {"proposal_id": str(uuid.uuid4())},
                "rendered_markdown": "### Proposal created\nTrain query MCP was proposed.",
                "source_refs": [{"kind": "proposal", "id": str(uuid.uuid4())}],
                "created_at": created_at,
                "updated_at": updated_at,
            }
        ],
        rendered_markdown="### Proposal created\nTrain query MCP was proposed.",
    )

    assert isinstance(view.entries[0], JournalEntryContract)
    payload = view.model_dump(mode="json")
    assert payload["entries"][0]["id"] == str(entry_id)
    assert payload["entries"][0]["entry_kind"] == "proposal_created"
    assert payload["entries"][0]["rendered_markdown"].startswith("### Proposal created")


def test_acquisition_journal_view_rejects_malformed_entries() -> None:
    with pytest.raises(ValidationError):
        AcquisitionJournalView(
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            generated_at=datetime.now(timezone.utc),
            entries=[
                {
                    "entry_kind": "proposal_created",
                    "subject_ref": {"proposal_id": str(uuid.uuid4())},
                    "source_refs": [],
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            ],
            rendered_markdown="### Proposal created",
        )


def test_credential_connection_contract_redacts_secret_values() -> None:
    secret = "sk-live-secret-value"
    request = CredentialConnectionCreateRequest(
        name="weather-api-key",
        provider="weather.example",
        connection_type="api_key",
        credential_kind="api_key",
        secret_storage_kind="encrypted_db",
        secret_value=secret,
        scopes=["weather:read"],
        allowed_target_types=["api_tool"],
        metadata_redacted={"last_four": "1234"},
    )
    response = CredentialConnectionResponse(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name=request.name,
        provider=request.provider,
        connection_type=request.connection_type,
        credential_kind=request.credential_kind,
        secret_storage_kind=request.secret_storage_kind,
        secret_generation=1,
        secret_ref_present=True,
        scopes=request.scopes,
        allowed_target_types=request.allowed_target_types,
        allowed_target_refs=[],
        status="active",
        metadata_redacted={"last_four": "1234", "label": "weather key"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    request_payload = request.model_dump(mode="json")
    response_payload = response.model_dump(mode="json")

    assert "secret_value" not in request_payload
    assert "secret_ref" not in response_payload
    assert secret not in str(request_payload)
    assert secret not in str(response_payload)
    assert response_payload["metadata_redacted"] == {"last_four": "1234", "label": "weather key"}


def test_request_contracts_reject_db_constrained_enum_values_before_persistence() -> None:
    with pytest.raises(ValidationError):
        CapabilityGapRequest(
            source_kind="tool_failure",
            source_run_id="run-123",
            dedupe_key="unsupported",
            title="Unsupported gap",
            description="Invalid gap type should be rejected.",
            gap_type="not_a_gap",
            severity="high",
            source_evidence=[CapabilityGapSourceEvidence(kind="tool_error", message="failed")],
            evidence={},
        )

    with pytest.raises(ValidationError):
        ExplorationRunRequest(
            gap_id=uuid.uuid4(),
            source_run_id="run-123",
            risk_level="safe",
            strategy="invent_new_runtime",
        )

    with pytest.raises(ValidationError):
        CapabilityRecommendationRequest(
            gap_id=uuid.uuid4(),
            recommendation_type="random_recommendation",
            title="Recommendation",
            summary="Summary",
            reason="Reason",
            evidence={},
            risk_level="safe",
            expected_value={},
            required_permissions={},
            candidate_targets=[],
        )

    with pytest.raises(ValidationError):
        RuntimePlanningIssueRequest(
            source_run_id="run-123",
            issue_type="planner_was_tired",
            available_capability_ref={},
            missed_signal="MCP existed.",
            planner_decision_summary="Suggested a patch.",
            expected_decision_summary="Use the MCP.",
            severity="medium",
            evidence={},
        )

    with pytest.raises(ValidationError):
        CredentialConnectionCreateRequest(
            name="weather-token",
            provider="weather.example",
            connection_type="session_magic",
            credential_kind="token",
            secret_storage_kind="encrypted_db",
        )


def test_mcp_contract_enforces_transport_shape_before_persistence() -> None:
    valid = MCPServerConfigurationContract(
        name="weather-stream",
        transport="sse",
        runtime_kind="remote_sse",
        url="https://mcp.example/sse",
        egress_policy={"allowed_hosts": ["mcp.example"]},
        risk_level="risky",
        stdio_max_session_seconds=60,
        stdio_max_output_bytes=1024,
    )
    assert valid.runtime_kind == "remote_sse"

    with pytest.raises(ValidationError):
        MCPServerConfigurationContract(
            name="bad-http",
            transport="http",
            runtime_kind="remote_sse",
            url="https://mcp.example/http",
            egress_policy={"allowed_hosts": ["mcp.example"]},
            risk_level="risky",
        )

    with pytest.raises(ValidationError):
        MCPServerConfigurationContract(
            name="bad-limit",
            transport="stdio",
            runtime_kind="isolated_stdio",
            command="node",
            egress_policy={},
            risk_level="safe",
            stdio_max_output_bytes=0,
        )

    with pytest.raises(ValidationError):
        MCPServerConfigurationContract(
            name="missing-command",
            transport="stdio",
            runtime_kind="isolated_stdio",
            egress_policy={},
            risk_level="safe",
        )

    with pytest.raises(ValidationError):
        MCPServerConfigurationContract(
            name="missing-http-url",
            transport="http",
            runtime_kind="remote_http",
            egress_policy={"allowed_hosts": ["mcp.example"]},
            risk_level="risky",
        )

    with pytest.raises(ValidationError):
        MCPServerConfigurationContract(
            name="missing-sse-url",
            transport="sse",
            runtime_kind="remote_sse",
            egress_policy={"allowed_hosts": ["mcp.example"]},
            risk_level="risky",
        )


def test_standing_permission_request_requires_expires_at_for_expiring_duration() -> None:
    with pytest.raises(ValidationError):
        StandingPermissionRequest(
            proposal_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            target_type="mcp_tool",
            permission_scope={"domains": ["api.example.com"]},
            risk_level="risky",
            duration="expires_at",
            approved_snapshot_hash="sha256:approved",
            revocation_plan={"action": "disable target"},
        )


def test_runtime_configuration_contracts_reject_non_positive_limits() -> None:
    with pytest.raises(ValidationError):
        APIToolConfigurationContract(
            name="weather-api",
            tool_name="api__weather-api",
            base_url="https://weather.example",
            method="GET",
            path_template="/forecast",
            headers_schema={},
            auth_scheme="none",
            input_schema={},
            output_schema={},
            allowed_hosts=["weather.example"],
            redirect_policy={},
            allowed_content_types=["application/json"],
            max_request_bytes=0,
            max_response_bytes=1024,
            idempotency_policy={},
            response_redaction_policy={},
            rate_limit={},
            timeout_s=10,
            retry_policy={},
            error_contract={},
            risk_level="safe",
        )

    with pytest.raises(ValidationError):
        WorkspaceConnectorContract(
            name="workspace",
            connector_id="workspace-1",
            display_path="E:/Chainless",
            host_realpath_hash="hash",
            container_mount_path="/workspace",
            backend_mount_path="/repo",
            sandbox_mount_path="/sandbox",
            connector_root="/repo",
            mount_generation=0,
            mount_health_status="healthy",
            mode="read_only",
            allowlist_rule={},
        )

    with pytest.raises(ValidationError):
        BrowserAutomationConfigurationContract(
            name="browser",
            allowlisted_domains=["example.com"],
            runtime_service_name="browser-runtime",
            runtime_image_ref="browser:latest",
            runtime_health_check={},
            network_policy={},
            cookie_scope={},
            profile_policy={},
            profile_retention_policy={},
            max_session_seconds=60,
            max_actions_per_run=20,
            concurrency_limit=1,
            cpu_limit="500m",
            memory_limit_mb=256,
            max_trace_bytes=0,
            trace_retention_days=7,
            action_redaction_policy={},
            write_confirmation_policy={},
        )
