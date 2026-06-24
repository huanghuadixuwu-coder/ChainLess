"""V3 acquisition Pydantic serialization contract tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import null

from app.api.deps import _async_session_factory
from app.core.acquisition import lifecycle
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
from app.models.acquisition import (
    AcquisitionProposal,
    ActivationTarget,
    BrowserAutomationConfiguration,
    CapabilityGap,
    CapabilityRecommendation,
    CredentialConnection,
    ExplorationRun,
    RuntimePlanningIssue,
    StandingPermission,
    WorkspaceConnector,
)
from app.services.auth_service import decode_token


RAW_ROUTE_SECRET = "sk-live-route-secret"
RAW_ROUTE_PATH = r"C:\Users\Owner\secret.txt"
RAW_ROUTE_TRACE = "trace-secret-1234"


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


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


def _execution_scope(target_type: str) -> str:
    return {
        "api_tool": "api_tool",
        "browser_automation": "browser_session",
        "mcp_tool": "mcp_tool",
        "workspace_connector": "workspace_connector",
        "worker": "worker_run",
    }.get(target_type, "mcp_tool")


def _permission_bundle_payload(target_type: str = "mcp_tool", *, duration: str = "one_run") -> dict[str, Any]:
    return {
        "target_type": target_type,
        "permission_scope": {"hosts": ["api.example.com"]},
        "risk_level": "safe",
        "confirmation_policy": "never_for_safe",
        "credential_scope": "none",
        "credential_connection_refs": [],
        "data_scope": "external_service",
        "network_scope": "allowlisted_domains",
        "egress_policy": {"allowed_hosts": ["api.example.com"], "allow_hosts": ["api.example.com"]},
        "write_scope": "none",
        "execution_scope": _execution_scope(target_type),
        "duration": duration,
        "revocation_plan": {"action": "disable target"},
        "audit_events": [{"event": "seeded", "secret": RAW_ROUTE_SECRET}],
    }


def _target_payload(target_type: str = "mcp_tool", *, name: str = "api-contract-target") -> dict[str, Any]:
    target_payload: dict[str, Any]
    if target_type == "browser_automation":
        target_payload = {
            "name": name,
            "allowlisted_domains": ["api.example.com"],
            "network_policy": {
                "mode": "allowlist",
                "allowed_hosts": ["api.example.com"],
                "deny_private_networks": True,
                "allow_docker_socket": False,
                "allow_host_fs": False,
                "mounts": [],
            },
        }
    elif target_type == "api_tool":
        target_payload = {
            "name": name,
            "base_url": "https://api.example.com",
            "allowed_hosts": ["api.example.com"],
            "method": "GET",
        }
    else:
        target_payload = {"name": name, "server": name, "transport": "stdio"}
    return {
        "target_type": target_type,
        "target_name": name,
        "target_owner": "core/acquisition/api-contract",
        "target_payload": target_payload,
        "permission_bundle": _permission_bundle_payload(target_type),
        "verification_plan": {"kind": "contract"},
        "rollback_plan": {"action": "disable"},
        "activation_status": "draft",
        "activation_result": {},
    }


def _gap_model(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    label: str,
    status: str = "detected",
) -> CapabilityGap:
    return CapabilityGap(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        source_kind="api_contract",
        source_run_id=f"run-{label}",
        dedupe_key=f"api-contract-{label}",
        title=f"API contract gap {label}",
        description=f"Gap seeded for {label}.",
        gap_type="missing_mcp",
        severity="medium",
        status=status,
        source_evidence=[
            {
                "kind": "tool_error",
                "message": f"Missing route evidence {RAW_ROUTE_SECRET}",
                "artifact_ref": RAW_ROUTE_TRACE,
            }
        ],
        evidence={"secret": RAW_ROUTE_SECRET, "path": RAW_ROUTE_PATH, "trace_id": RAW_ROUTE_TRACE},
    )


def _recommendation_model(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    *,
    label: str,
) -> CapabilityRecommendation:
    return CapabilityRecommendation(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        recommendation_type="mcp_recommendation",
        title=f"API contract recommendation {label}",
        summary="Use a bounded MCP tool.",
        reason="A reusable route contract needs stable acquisition evidence.",
        evidence={"secret": RAW_ROUTE_SECRET, "path": RAW_ROUTE_PATH},
        risk_level="safe",
        expected_value={"reusable": True},
        required_permissions={"network": "allowlisted_domains"},
        candidate_targets=[_target_payload("mcp_tool", name=f"mcp-{label}")],
    )


def _proposal_model(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    *,
    label: str,
    proposal_kind: str = "runtime_activation",
    target_type: str = "mcp_tool",
    status: str = "drafted",
) -> AcquisitionProposal:
    return AcquisitionProposal(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_kind=proposal_kind,
        gap_id=gap_id,
        recommendation_id=recommendation_id,
        title=f"API contract proposal {label}",
        reason="A stable acquisition route should expose this proposal.",
        evidence={"secret": RAW_ROUTE_SECRET, "path": RAW_ROUTE_PATH},
        status=status,
        risk_level="safe",
        permission_bundle=_permission_bundle_payload(target_type),
        primary_target=_target_payload(target_type, name=f"target-{label}") if proposal_kind == "runtime_activation" else null(),
        secondary_targets=[],
        development_handoff={"patch_artifact_ref": f"artifact://{uuid.uuid4()}"} if proposal_kind == "development_patch_proposal" else None,
        verification_plan={"kind": "contract"},
        rollback_plan={"action": "disable"},
        user_visible_effect="The seeded capability becomes available after approval.",
        approval_history=[],
    )


def _activation_target_model(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    *,
    label: str,
    target_type: str = "browser_automation",
    status: str = "active",
    trace_id: str | None = None,
) -> ActivationTarget:
    resource_ref = {
        "kind": f"{target_type}_configuration",
        "configuration_id": str(uuid.uuid4()),
        "manifest_ref": f"{target_type}:{label}",
        "tool_name": f"{target_type}:{label}",
        "runtime_session_ref": {"session_id": f"session-{label}"},
        "exposed_to_runtime": True,
    }
    return ActivationTarget(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        target_type=target_type,
        target_name=f"target-{label}",
        target_owner="core/acquisition/api-contract",
        target_payload={"name": f"target-{label}", "path": RAW_ROUTE_PATH},
        permission_bundle=_permission_bundle_payload(target_type),
        verification_plan={"kind": "contract"},
        rollback_plan={"action": "disable"},
        activation_status=status,
        activation_result={
            "phase": status,
            "trace_artifact": {
                "run_id": trace_id or f"trace-{label}",
                "events": [{"type": "fill", "payload": {"value": RAW_ROUTE_SECRET}}],
            },
        },
        activated_resource_ref=resource_ref,
    )


def _browser_config_model(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    target_id: uuid.UUID,
    *,
    label: str,
) -> BrowserAutomationConfiguration:
    return BrowserAutomationConfiguration(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        activation_target_id=target_id,
        name=f"browser-{label}",
        allowlisted_domains=["api.example.com"],
        runtime_service_name="browser-runtime",
        runtime_image_ref="chainless-browser-runtime:w6-1",
        runtime_health_check={"path": "/health"},
        network_policy={
            "mode": "allowlist",
            "allowed_hosts": ["api.example.com"],
            "deny_private_networks": True,
            "allow_docker_socket": False,
            "allow_host_fs": False,
            "mounts": [],
        },
        cookie_scope={"mode": "runtime_only", "cookie": RAW_ROUTE_SECRET},
        profile_policy={"isolation": "per_run", "allow_host_fs": False},
        profile_storage_ref=RAW_ROUTE_PATH,
        profile_retention_policy={"mode": "discard_after_run"},
        max_session_seconds=30,
        max_actions_per_run=5,
        concurrency_limit=1,
        cpu_limit="1.0",
        memory_limit_mb=512,
        max_trace_bytes=65536,
        trace_retention_days=7,
        action_redaction_policy={"sensitive_keys": ["value", "token"]},
        write_confirmation_policy={"mode": "before_each_external_write"},
        enabled=True,
        last_verified_at=datetime.now(timezone.utc),
    )


async def _seed_graph(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    label: str,
    target_type: str = "mcp_tool",
    proposal_kind: str = "runtime_activation",
    proposal_status: str = "drafted",
    with_target: bool = False,
    with_browser_config: bool = False,
    trace_id: str | None = None,
) -> dict[str, uuid.UUID]:
    async with _async_session_factory() as db:
        gap = _gap_model(tenant_id, user_id, label=label, status="recommendation_created")
        db.add(gap)
        await db.flush()
        recommendation = _recommendation_model(tenant_id, user_id, gap.id, label=label)
        db.add(recommendation)
        await db.flush()
        proposal = _proposal_model(
            tenant_id,
            user_id,
            gap.id,
            recommendation.id,
            label=label,
            proposal_kind=proposal_kind,
            target_type=target_type,
            status=proposal_status,
        )
        db.add(proposal)
        await db.flush()
        rows: list[Any] = []
        target_id: uuid.UUID | None = None
        browser_config_id: uuid.UUID | None = None
        if with_target or with_browser_config:
            target = _activation_target_model(
                tenant_id,
                user_id,
                proposal.id,
                label=label,
                target_type=target_type,
                trace_id=trace_id,
            )
            target_id = target.id
            db.add(target)
            await db.flush()
            if with_browser_config:
                browser_config = _browser_config_model(tenant_id, user_id, target.id, label=label)
                browser_config_id = browser_config.id
                rows.append(browser_config)
        if rows:
            db.add_all(rows)
        await db.commit()
        return {
            "gap_id": gap.id,
            "recommendation_id": recommendation.id,
            "proposal_id": proposal.id,
            "target_id": target_id,
            "browser_config_id": browser_config_id,
        }


async def _seed_gap_only(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    label: str,
    status: str = "detected",
) -> uuid.UUID:
    async with _async_session_factory() as db:
        gap = _gap_model(tenant_id, user_id, label=label, status=status)
        db.add(gap)
        await db.commit()
        return gap.id


async def _seed_exploration(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    label: str,
) -> uuid.UUID:
    async with _async_session_factory() as db:
        gap = _gap_model(tenant_id, user_id, label=f"exploration-{label}", status="exploration_approved")
        db.add(gap)
        await db.flush()
        exploration = ExplorationRun(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap.id,
            source_run_id=f"exploration-run-{label}",
            risk_level="safe",
            status="queued",
            strategy="manual_research",
            tool_events=[{"secret": RAW_ROUTE_SECRET, "path": RAW_ROUTE_PATH}],
            script_ref=RAW_ROUTE_PATH,
            artifact_refs=[{"trace_id": RAW_ROUTE_TRACE}],
            stdout_excerpt=RAW_ROUTE_SECRET,
            stderr_excerpt=RAW_ROUTE_TRACE,
        )
        db.add(exploration)
        await db.commit()
        return exploration.id


async def _seed_runtime_issue(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    label: str,
) -> uuid.UUID:
    async with _async_session_factory() as db:
        issue = RuntimePlanningIssue(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=f"planning-{label}",
            issue_type="planner_missed_existing_tool",
            available_capability_ref={"tool": "weather"},
            missed_signal="Existing weather tool was available.",
            planner_decision_summary="Planner tried to acquire a new tool.",
            expected_decision_summary="Planner should use the existing tool.",
            severity="medium",
            status="open",
            evidence={"secret": RAW_ROUTE_SECRET, "path": RAW_ROUTE_PATH},
        )
        db.add(issue)
        await db.commit()
        return issue.id


async def _seed_credential(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    label: str,
) -> uuid.UUID:
    async with _async_session_factory() as db:
        credential = CredentialConnection(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"credential-{label}",
            provider="api.example.com",
            connection_type="api_key",
            credential_kind="api_key",
            secret_storage_kind="encrypted_db",
            secret_ref=f"encrypted:{RAW_ROUTE_SECRET}",
            secret_generation=1,
            scopes=["read"],
            allowed_target_types=["api_tool"],
            allowed_target_refs=[],
            status="active",
            metadata_redacted={"secret_note": RAW_ROUTE_SECRET, "label": label},
        )
        db.add(credential)
        await db.commit()
        return credential.id


async def _seed_permission(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    label: str,
) -> uuid.UUID:
    graph = await _seed_graph(
        tenant_id,
        user_id,
        label=f"permission-{label}",
        target_type="mcp_tool",
        proposal_status="activated",
        with_target=True,
    )
    async with _async_session_factory() as db:
        permission = StandingPermission(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=graph["proposal_id"],
            target_id=graph["target_id"],
            target_type="mcp_tool",
            permission_scope={"hosts": ["api.example.com"], "secret": RAW_ROUTE_SECRET},
            risk_level="safe",
            duration="until_revoked",
            approved_snapshot_hash="sha256:approved",
            status="active",
            renewal_required_at=datetime.now(timezone.utc) + timedelta(days=1),
            revocation_plan={"action": "disable"},
            audit_events=[{"event": "seeded", "path": RAW_ROUTE_PATH}],
        )
        db.add(permission)
        await db.commit()
        return permission.id


async def _seed_workspace_connector(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    label: str,
) -> uuid.UUID:
    async with _async_session_factory() as db:
        connector = WorkspaceConnector(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"workspace-{label}",
            connector_id=f"wsc_{label.replace('-', '_')}_{uuid.uuid4().hex[:8]}",
            display_path="approved://workspace",
            host_realpath_hash="hmac-sha256:redacted",
            host_path_secret_ref="encrypted://redacted",
            container_mount_path=f"/workspace/connectors/{label}",
            backend_mount_path=f"/workspace/connectors/{label}",
            sandbox_mount_path=f"/workspace/connectors/{label}",
            connector_root=f"/workspace/connectors/{label}",
            mount_generation=1,
            mount_health_status="healthy",
            mode="read_only",
            allowlist_rule={
                "purpose": "api-contract",
                "secret": RAW_ROUTE_SECRET,
                "host_path": RAW_ROUTE_PATH,
            },
            enabled=True,
            last_verified_at=datetime.now(timezone.utc),
        )
        db.add(connector)
        await db.commit()
        return connector.id


def _proposal_request_json(
    gap_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    *,
    label: str = "drafted-from-api",
) -> dict[str, Any]:
    target = _target_payload("mcp_tool", name=label)
    return {
        "proposal_kind": "runtime_activation",
        "gap_id": str(gap_id),
        "recommendation_id": str(recommendation_id),
        "title": f"Draft {label}",
        "reason": "Drafted through the acquisition API.",
        "evidence": {"source": "api-contract"},
        "risk_level": "safe",
        "permission_bundle": _permission_bundle_payload("mcp_tool"),
        "primary_target": target,
        "secondary_targets": [],
        "verification_plan": {"kind": "contract"},
        "rollback_plan": {"action": "disable"},
        "user_visible_effect": "A stable MCP capability can be activated.",
    }


@pytest.mark.asyncio
async def test_acquisition_route_matrix_contracts(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    dismiss_gap_id = await _seed_gap_only(tenant_id, user_id, label="dismiss")
    snooze_gap_id = await _seed_gap_only(tenant_id, user_id, label="snooze")
    exploration_gap_id = await _seed_gap_only(tenant_id, user_id, label="approve-exploration")
    exploration_id = await _seed_exploration(tenant_id, user_id, label="detail")
    draft_graph = await _seed_graph(tenant_id, user_id, label="draft-proposal")
    activation_graph = await _seed_graph(tenant_id, user_id, label="activation", target_type="mcp_tool")
    reject_graph = await _seed_graph(tenant_id, user_id, label="reject", target_type="mcp_tool")
    patch_graph = await _seed_graph(
        tenant_id,
        user_id,
        label="patch",
        proposal_kind="development_patch_proposal",
        proposal_status="verified",
    )
    issue_id = await _seed_runtime_issue(tenant_id, user_id, label="dismiss")
    browser_graph = await _seed_graph(
        tenant_id,
        user_id,
        label="browser",
        target_type="browser_automation",
        proposal_status="activated",
        with_target=True,
        with_browser_config=True,
        trace_id="trace-api-contract",
    )
    permission_id = await _seed_permission(tenant_id, user_id, label="route")
    workspace_connector_id = await _seed_workspace_connector(tenant_id, user_id, label="route")

    list_response = await client.get("/api/v1/acquisition/gaps", headers=tenant_a_headers)
    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["items"]

    detail_response = await client.get(f"/api/v1/acquisition/gaps/{dismiss_gap_id}", headers=tenant_a_headers)
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["id"] == str(dismiss_gap_id)

    dismiss_response = await client.post(
        f"/api/v1/acquisition/gaps/{dismiss_gap_id}/dismiss",
        json={"reason": "not needed"},
        headers=tenant_a_headers,
    )
    assert dismiss_response.status_code == 200, dismiss_response.text
    assert dismiss_response.json()["status"] == "dismissed"

    snooze_response = await client.post(
        f"/api/v1/acquisition/gaps/{snooze_gap_id}/snooze",
        json={"snoozed_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
        headers=tenant_a_headers,
    )
    assert snooze_response.status_code == 200, snooze_response.text
    assert snooze_response.json()["status"] == "snoozed"

    approve_exploration = await client.post(
        f"/api/v1/acquisition/gaps/{exploration_gap_id}/approve-exploration",
        json={
            "source_run_id": "route-approved-exploration",
            "strategy": "manual_research",
            "risk_level": "safe",
            "bounds": {"read_only": True, "cleanup_supported": True},
        },
        headers=tenant_a_headers,
    )
    assert approve_exploration.status_code == 200, approve_exploration.text
    assert approve_exploration.json()["gap_id"] == str(exploration_gap_id)

    explorations_response = await client.get("/api/v1/acquisition/explorations", headers=tenant_a_headers)
    assert explorations_response.status_code == 200, explorations_response.text
    exploration_detail = await client.get(
        f"/api/v1/acquisition/explorations/{exploration_id}",
        headers=tenant_a_headers,
    )
    assert exploration_detail.status_code == 200, exploration_detail.text

    recommendations_response = await client.get("/api/v1/acquisition/recommendations", headers=tenant_a_headers)
    assert recommendations_response.status_code == 200, recommendations_response.text
    recommendation_detail = await client.get(
        f"/api/v1/acquisition/recommendations/{draft_graph['recommendation_id']}",
        headers=tenant_a_headers,
    )
    assert recommendation_detail.status_code == 200, recommendation_detail.text

    draft_response = await client.post(
        f"/api/v1/acquisition/recommendations/{draft_graph['recommendation_id']}/draft-proposal",
        json=_proposal_request_json(draft_graph["gap_id"], draft_graph["recommendation_id"]),
        headers=tenant_a_headers,
    )
    assert draft_response.status_code == 201, draft_response.text
    assert draft_response.json()["recommendation_id"] == str(draft_graph["recommendation_id"])

    proposals_response = await client.get("/api/v1/acquisition/proposals", headers=tenant_a_headers)
    assert proposals_response.status_code == 200, proposals_response.text
    proposal_detail = await client.get(
        f"/api/v1/acquisition/proposals/{activation_graph['proposal_id']}",
        headers=tenant_a_headers,
    )
    assert proposal_detail.status_code == 200, proposal_detail.text

    verify_response = await client.post(
        f"/api/v1/acquisition/proposals/{activation_graph['proposal_id']}/verify",
        json={
            "verification_kind": "contract",
            "input_fixture": {"ok": True},
            "expected_result": {"ok": True},
            "actual_result": {"ok": True},
            "artifact_refs": [{"artifact_id": "route-verification"}],
        },
        headers=tenant_a_headers,
    )
    assert verify_response.status_code == 200, verify_response.text
    verified_hash = verify_response.json()["verified_snapshot_hash"]

    approve_response = await client.post(
        f"/api/v1/acquisition/proposals/{activation_graph['proposal_id']}/approve-activation",
        json={"approved_snapshot_hash": verified_hash, "reason": "route contract approval"},
        headers=tenant_a_headers,
    )
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["status"] == "activation_approved"

    activate_response = await client.post(
        f"/api/v1/acquisition/proposals/{activation_graph['proposal_id']}/activate",
        json={"approved_snapshot_hash": verified_hash, "verification_id": verify_response.json()["id"]},
        headers=tenant_a_headers,
    )
    assert activate_response.status_code == 200, activate_response.text
    assert activate_response.json()["status"] == "activated"

    rollback_response = await client.post(
        f"/api/v1/acquisition/proposals/{activation_graph['proposal_id']}/rollback",
        json={"reason": "route contract rollback"},
        headers=tenant_a_headers,
    )
    assert rollback_response.status_code == 200, rollback_response.text
    assert rollback_response.json()["status"] == "rolled_back"

    reject_response = await client.post(
        f"/api/v1/acquisition/proposals/{reject_graph['proposal_id']}/reject-activation",
        json={"reason": "route contract rejection"},
        headers=tenant_a_headers,
    )
    assert reject_response.status_code == 200, reject_response.text
    assert reject_response.json()["status"] == "activation_rejected"

    patch_handoff_response = await client.post(
        f"/api/v1/acquisition/proposals/{patch_graph['proposal_id']}/handoff-development-patch",
        json={},
        headers=tenant_a_headers,
    )
    assert patch_handoff_response.status_code == 409, patch_handoff_response.text
    assert patch_handoff_response.json()["error"]["code"] == "DEVELOPMENT_PATCH_PROPOSAL_MISSING"

    issues_response = await client.get("/api/v1/acquisition/runtime-planning-issues", headers=tenant_a_headers)
    assert issues_response.status_code == 200, issues_response.text
    issue_detail = await client.get(
        f"/api/v1/acquisition/runtime-planning-issues/{issue_id}",
        headers=tenant_a_headers,
    )
    assert issue_detail.status_code == 200, issue_detail.text
    issue_dismiss = await client.post(
        f"/api/v1/acquisition/runtime-planning-issues/{issue_id}/dismiss",
        json={"reason": "route contract"},
        headers=tenant_a_headers,
    )
    assert issue_dismiss.status_code == 200, issue_dismiss.text
    assert issue_dismiss.json()["status"] == "dismissed"

    credential_create = await client.post(
        "/api/v1/acquisition/credential-connections",
        json={
            "name": "route-key",
            "provider": "api.example.com",
            "connection_type": "api_key",
            "credential_kind": "api_key",
            "secret_storage_kind": "encrypted_db",
            "secret_value": RAW_ROUTE_SECRET,
            "scopes": ["read"],
            "allowed_target_types": ["api_tool"],
            "metadata_redacted": {"label": "route key", "secret_note": RAW_ROUTE_SECRET},
        },
        headers=tenant_a_headers,
    )
    assert credential_create.status_code == 201, credential_create.text
    assert RAW_ROUTE_SECRET not in credential_create.text
    credential_id = credential_create.json()["id"]

    credentials_response = await client.get("/api/v1/acquisition/credential-connections", headers=tenant_a_headers)
    assert credentials_response.status_code == 200, credentials_response.text
    credential_detail = await client.get(
        f"/api/v1/acquisition/credential-connections/{credential_id}",
        headers=tenant_a_headers,
    )
    assert credential_detail.status_code == 200, credential_detail.text
    validate_response = await client.post(
        f"/api/v1/acquisition/credential-connections/{credential_id}/validate",
        json={},
        headers=tenant_a_headers,
    )
    assert validate_response.status_code == 200, validate_response.text
    rotate_response = await client.post(
        f"/api/v1/acquisition/credential-connections/{credential_id}/rotate",
        json={"secret_value": "sk-live-rotated-route-secret", "metadata_redacted": {"label": "rotated"}},
        headers=tenant_a_headers,
    )
    assert rotate_response.status_code == 200, rotate_response.text
    revoke_response = await client.post(
        f"/api/v1/acquisition/credential-connections/{credential_id}/revoke",
        json={"reason": "route contract"},
        headers=tenant_a_headers,
    )
    assert revoke_response.status_code == 200, revoke_response.text
    assert revoke_response.json()["status"] == "revoked"

    sessions_response = await client.get("/api/v1/acquisition/browser-sessions", headers=tenant_a_headers)
    assert sessions_response.status_code == 200, sessions_response.text
    session_detail = await client.get(
        f"/api/v1/acquisition/browser-sessions/{browser_graph['browser_config_id']}",
        headers=tenant_a_headers,
    )
    assert session_detail.status_code == 200, session_detail.text
    trace_detail = await client.get(
        "/api/v1/acquisition/browser-traces/trace-api-contract",
        headers=tenant_a_headers,
    )
    assert trace_detail.status_code == 200, trace_detail.text
    assert RAW_ROUTE_SECRET not in trace_detail.text
    terminate_response = await client.post(
        f"/api/v1/acquisition/browser-sessions/{browser_graph['browser_config_id']}/terminate",
        json={"reason": "route contract"},
        headers=tenant_a_headers,
    )
    assert terminate_response.status_code == 200, terminate_response.text
    assert terminate_response.json()["status"] == "terminated"

    workspace_connectors_response = await client.get(
        "/api/v1/acquisition/workspace-connectors",
        headers=tenant_a_headers,
    )
    assert workspace_connectors_response.status_code == 200, workspace_connectors_response.text
    assert RAW_ROUTE_SECRET not in workspace_connectors_response.text
    assert RAW_ROUTE_PATH not in workspace_connectors_response.text
    workspace_connector_detail = await client.get(
        f"/api/v1/acquisition/workspace-connectors/{workspace_connector_id}",
        headers=tenant_a_headers,
    )
    assert workspace_connector_detail.status_code == 200, workspace_connector_detail.text
    assert workspace_connector_detail.json()["id"] == str(workspace_connector_id)
    revoke_workspace_connector = await client.post(
        f"/api/v1/acquisition/workspace-connectors/{workspace_connector_id}/revoke",
        json={"reason": "route contract"},
        headers=tenant_a_headers,
    )
    assert revoke_workspace_connector.status_code == 200, revoke_workspace_connector.text
    assert revoke_workspace_connector.json()["enabled"] is False
    assert revoke_workspace_connector.json()["mount_health_status"] == "stale"

    permissions_response = await client.get("/api/v1/acquisition/permissions", headers=tenant_a_headers)
    assert permissions_response.status_code == 200, permissions_response.text
    revoke_permission = await client.post(
        f"/api/v1/acquisition/permissions/{permission_id}/revoke",
        json={"reason": "route contract"},
        headers=tenant_a_headers,
    )
    assert revoke_permission.status_code == 200, revoke_permission.text
    assert revoke_permission.json()["status"] == "revoked"
    renew_permission = await client.post(
        f"/api/v1/acquisition/permissions/{permission_id}/renew",
        json={},
        headers=tenant_a_headers,
    )
    assert renew_permission.status_code == 200, renew_permission.text
    assert renew_permission.json()["status"] == "active"

    journal_response = await client.get("/api/v1/acquisition/journal", headers=tenant_a_headers)
    assert journal_response.status_code == 200, journal_response.text
    assert journal_response.json()["rendered_markdown"].startswith("# ACQUISITION.md")


@pytest.mark.asyncio
async def test_acquisition_list_routes_enforce_pagination_isolation_ordering_and_redaction(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    other_tenant_id, other_user_id = _identity(tenant_b_headers)

    for index in range(3):
        graph = await _seed_graph(
            tenant_id,
            user_id,
            label=f"page-{index}",
            target_type="browser_automation",
            proposal_status="activated",
            with_target=True,
            with_browser_config=True,
            trace_id=f"trace-page-{index}",
        )
        await _seed_exploration(tenant_id, user_id, label=f"page-{index}")
        await _seed_runtime_issue(tenant_id, user_id, label=f"page-{index}")
        await _seed_credential(tenant_id, user_id, label=f"page-{index}")
        await _seed_workspace_connector(tenant_id, user_id, label=f"page-{index}")
        async with _async_session_factory() as db:
            permission = StandingPermission(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=graph["proposal_id"],
                target_id=graph["target_id"],
                target_type="browser_automation",
                permission_scope={"hosts": ["api.example.com"], "secret": RAW_ROUTE_SECRET},
                risk_level="safe",
                duration="until_revoked",
                approved_snapshot_hash="sha256:approved",
                status="active",
                revocation_plan={"action": "disable"},
                audit_events=[{"event": "seeded", "path": RAW_ROUTE_PATH}],
            )
            db.add(permission)
            await db.commit()

    await _seed_graph(
        other_tenant_id,
        other_user_id,
        label="other-tenant",
        target_type="browser_automation",
        proposal_status="activated",
        with_target=True,
        with_browser_config=True,
        trace_id="trace-other-tenant",
    )
    await _seed_exploration(other_tenant_id, other_user_id, label="other-tenant")
    await _seed_runtime_issue(other_tenant_id, other_user_id, label="other-tenant")
    await _seed_credential(other_tenant_id, other_user_id, label="other-tenant")
    await _seed_permission(other_tenant_id, other_user_id, label="other-tenant")
    await _seed_workspace_connector(other_tenant_id, other_user_id, label="other-tenant")

    list_routes = (
        "/api/v1/acquisition/gaps",
        "/api/v1/acquisition/explorations",
        "/api/v1/acquisition/recommendations",
        "/api/v1/acquisition/proposals",
        "/api/v1/acquisition/runtime-planning-issues",
        "/api/v1/acquisition/credential-connections",
        "/api/v1/acquisition/browser-sessions",
        "/api/v1/acquisition/workspace-connectors",
        "/api/v1/acquisition/permissions",
    )

    for route in list_routes:
        default_response = await client.get(route, headers=tenant_a_headers)
        assert default_response.status_code == 200, default_response.text
        payload = default_response.json()
        assert payload["limit"] == 20
        assert payload["offset"] == 0
        assert payload["items"]
        assert all(item["tenant_id"] == str(tenant_id) for item in payload["items"])
        assert all(item["user_id"] == str(user_id) for item in payload["items"])
        assert str(other_tenant_id) not in default_response.text
        assert str(other_user_id) not in default_response.text
        assert RAW_ROUTE_SECRET not in default_response.text
        assert RAW_ROUTE_PATH not in default_response.text
        assert RAW_ROUTE_TRACE not in default_response.text

        max_response = await client.get(f"{route}?limit=101", headers=tenant_a_headers)
        assert max_response.status_code == 422, max_response.text

        first_page = await client.get(f"{route}?limit=3&offset=0", headers=tenant_a_headers)
        second_read = await client.get(f"{route}?limit=3&offset=0", headers=tenant_a_headers)
        offset_page = await client.get(f"{route}?limit=2&offset=1", headers=tenant_a_headers)
        assert first_page.status_code == 200, first_page.text
        assert second_read.status_code == 200, second_read.text
        assert offset_page.status_code == 200, offset_page.text

        first_ids = [item["id"] for item in first_page.json()["items"]]
        second_ids = [item["id"] for item in second_read.json()["items"]]
        offset_ids = [item["id"] for item in offset_page.json()["items"]]
        assert first_ids == second_ids
        assert offset_page.json()["offset"] == 1
        if len(first_ids) >= 3:
            assert offset_ids == first_ids[1:3]


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
        WorkspaceConnectorContract(
            name="workspace",
            connector_id="workspace-1",
            display_path="approved://workspace",
            host_realpath_hash="hash",
            container_mount_path="/workspace",
            backend_mount_path="/repo",
            sandbox_mount_path="/sandbox",
            connector_root="/repo",
            mount_generation=1,
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
