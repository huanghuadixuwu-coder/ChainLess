"""Focused acquisition policy invariants for W2.3 activation rollback."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.acquisition import lifecycle, repository
from app.core.acquisition.activation import approve_activation, run_activation_saga, start_activation
from app.core.acquisition.policy import (
    PermissionDecision,
    RuntimePermissionRequest,
    TargetPolicyDecision,
    apply_target_policy_narrowing,
    build_standing_permission_scope,
    build_runtime_confirmation_context,
    evaluate_runtime_permission,
)
from app.core.acquisition.verification import verify_proposal
from app.core.security.egress_policy import (
    EgressPolicy,
    prepare_egress_runtime_guard,
    validate_egress_request,
    validate_egress_response_chunk,
    validate_runtime_egress,
)
from app.core.tools.api_runtime import (
    APIToolConfirmationRequired,
    api_tool_name,
    execute_api_tool,
    get_api_tool_definitions,
)
from app.core.tools.api_runtime import registry as api_runtime_registry
from app.core.credentials.service import (
    create_credential_connection,
    credential_connection_response,
    revoke_credential_connection,
)
from app.core.secrets import decrypt_secret
from app.models.acquisition import (
    APIToolConfiguration,
    ActivationTarget,
    AcquisitionProposal,
    StandingPermission,
)
from app.models.channel_configuration import ChannelConfiguration
from app.models.llm_provider import LLMProvider
from app.services.auth_service import decode_token


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


def _permission_bundle(credential_id: uuid.UUID) -> dict:
    return {
        "target_type": "api_tool",
        "permission_scope": {"hosts": ["api.weather.example"], "methods": ["GET"]},
        "risk_level": "safe",
        "confirmation_policy": "never_for_safe",
        "credential_scope": "user_provided_token",
        "credential_connection_refs": [str(credential_id)],
        "data_scope": "none",
        "network_scope": "public_web",
        "egress_policy": {"allow_hosts": ["api.weather.example"]},
        "write_scope": "none",
        "execution_scope": "api_tool",
        "duration": "one_run",
        "revocation_plan": {"disable": True},
        "audit_events": [],
    }


def _primary_target(credential_id: uuid.UUID) -> dict:
    return {
        "target_type": "api_tool",
        "target_name": "weather",
        "target_owner": "core.api_tools",
        "target_payload": {"base_url": "https://api.weather.example", "path_template": "/v1/weather"},
        "permission_bundle": _permission_bundle(credential_id),
        "verification_plan": {"kind": "contract"},
        "rollback_plan": {"disable": True},
        "activation_status": "draft",
        "activation_result": {},
    }


async def _runtime_permission_request(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    bundle_overrides: dict | None = None,
    request_bundle_overrides: dict | None = None,
    permission_overrides: dict | None = None,
    runtime_scope: dict | None = None,
    action_category: str = "read",
    tool_context: dict | None = None,
    confirmation_context: dict | None = None,
) -> RuntimePermissionRequest:
    approved_hash = f"snapshot-{uuid.uuid4().hex}"
    async with _async_session_factory() as db:
        credential = await create_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"Policy runtime key {uuid.uuid4().hex}",
            provider="weather.example",
            connection_type="api_key",
            credential_kind="api_key",
            secret_storage_kind="encrypted_db",
            secret_value=f"sk-policy-{uuid.uuid4().hex}",
            allowed_target_types=["api_tool"],
        )
        await db.commit()

    proposal = await _runtime_proposal(tenant_id, user_id, credential.id)
    bundle = _permission_bundle(credential.id)
    bundle.update({"duration": "until_revoked"})
    if bundle_overrides:
        bundle.update(bundle_overrides)
    request_bundle = {**bundle}
    if request_bundle_overrides:
        request_bundle.update(request_bundle_overrides)

    async with _async_session_factory() as db:
        persisted_proposal = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id).with_for_update())
        ).scalar_one()
        target = ActivationTarget(
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            target_type="api_tool",
            target_name="weather",
            target_owner="core.api_tools",
            target_payload={"base_url": "https://api.weather.example"},
            permission_bundle=bundle,
            verification_plan={"kind": "contract"},
            rollback_plan={"disable": True},
            activation_status="active",
            activation_result={"phase": "active"},
        )
        db.add(target)
        await db.flush()
        persisted_proposal.activation_snapshot_hash = approved_hash
        persisted_proposal.approval_history = [
            *(persisted_proposal.approval_history or []),
            {"status": "activation_approved", "approved_snapshot_hash": approved_hash},
        ]
        permission_payload = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "proposal_id": proposal.id,
            "target_id": target.id,
            "target_type": target.target_type,
            "permission_scope": build_standing_permission_scope(bundle),
            "risk_level": bundle["risk_level"],
            "duration": "until_revoked",
            "approved_snapshot_hash": approved_hash,
            "revocation_plan": bundle["revocation_plan"],
            "audit_events": [],
        }
        if permission_overrides:
            permission_payload.update(permission_overrides)
        permission = StandingPermission(**permission_payload)
        db.add(permission)
        await db.flush()
        request = RuntimePermissionRequest(
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            target_id=target.id,
            target_type=target.target_type,
            permission_bundle=request_bundle,
            approved_snapshot_hash=approved_hash,
            current_snapshot_hash=approved_hash,
            permission_scope=runtime_scope or request_bundle["permission_scope"],
            risk_level=request_bundle["risk_level"],
            action_category=action_category,
            tool_context=tool_context or {"tool_name": "weather", "method": "GET"},
            confirmation_context=confirmation_context,
        )
        await db.commit()
        return request


def _api_config_from_request(request: RuntimePermissionRequest, *, name: str = "weather") -> APIToolConfiguration:
    return APIToolConfiguration(
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        activation_target_id=request.target_id,
        name=name,
        tool_name=api_tool_name(name),
        base_url="https://api.weather.example",
        method="GET",
        path_template="/weather/{city}",
        headers_schema={},
        auth_scheme="none",
        input_schema={
            "type": "object",
            "required": ["city"],
            "properties": {"city": {"type": "string"}},
        },
        output_schema={"type": "object"},
        allowed_hosts=["api.weather.example"],
        deny_private_networks=True,
        redirect_policy={"follow": False},
        allowed_content_types=["application/json"],
        max_request_bytes=1024,
        max_response_bytes=4096,
        idempotency_policy={"idempotent": True},
        response_redaction_policy={},
        rate_limit={},
        timeout_s=5,
        retry_policy={},
        error_contract={"code_field": "errorCode", "message_field": "errorMessage", "status_field": "httpStatus"},
        enabled=True,
        risk_level="safe",
        last_verified_at=datetime.now(timezone.utc),
    )


async def _runtime_proposal(tenant_id: uuid.UUID, user_id: uuid.UUID, credential_id: uuid.UUID) -> AcquisitionProposal:
    async with _async_session_factory() as db:
        gap = await lifecycle.record_gap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_kind="agent_runtime",
            source_run_id=f"policy-test-{uuid.uuid4().hex}",
            dedupe_key=f"Tool: Weather API {uuid.uuid4().hex}",
            title="Missing weather API",
            description="The task needs a reusable weather API capability.",
            gap_type="missing_api",
            severity="medium",
            evidence={"target": "weather"},
            source_evidence=[{"kind": "tool_error", "message": "TOOL_NOT_FOUND"}],
            idempotency_key=f"gap-{uuid.uuid4().hex}",
        )
        recommendation = await lifecycle.create_recommendation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap.id,
            recommendation_type="api_recommendation",
            title="Configure weather API",
            summary="Use a bounded weather API tool.",
            reason="The gap needs stable public weather data.",
            evidence={"source": "policy-test"},
            risk_level="safe",
            expected_value={"reusable": True},
            required_permissions={"network": "public_web"},
            candidate_targets=[{"target_type": "api_tool", "name": "weather"}],
            idempotency_key=f"recommendation-{uuid.uuid4().hex}",
        )
        proposal = await lifecycle.create_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_kind="runtime_activation",
            gap_id=gap.id,
            recommendation_id=recommendation.id,
            title="Activate weather API",
            reason="Stable weather lookup should be reusable.",
            evidence={"source": "policy-test"},
            risk_level="safe",
            permission_bundle=_permission_bundle(credential_id),
            primary_target=_primary_target(credential_id),
            verification_plan={"kind": "contract"},
            rollback_plan={"disable": True},
            user_visible_effect="Weather lookups can use a configured API tool.",
            idempotency_key=f"proposal-{uuid.uuid4().hex}",
        )
        await db.commit()
        return proposal


def test_partial_activation_policy_allows_user_chosen_rollback() -> None:
    assert "rolled_back" in repository.ALLOWED_PROPOSAL_STATUS_TRANSITIONS["partial_activation"]


def test_runtime_activation_guarded_states_remain_activation_owner_only() -> None:
    assert repository.GUARDED_RUNTIME_ACTIVATION_STATUSES == {
        "activation_approved",
        "activating",
        "activated",
    }


def test_egress_policy_allows_declared_public_host() -> None:
    decision = validate_egress_request(
        EgressPolicy(allow_hosts=["API.Weather.Example:443"], max_response_bytes=4096),
        "https://api.weather.example/v1/weather",
        network_scope="allowlisted_domains",
        resolved_ips=["93.184.216.34"],
        response_content_length=2048,
    )

    assert decision.allowed is True
    assert decision.normalized_host == "api.weather.example"


def test_egress_policy_rejects_private_ip() -> None:
    decision = validate_egress_request(
        EgressPolicy(allow_hosts=["10.0.0.8"], max_response_bytes=4096),
        "http://10.0.0.8/admin",
        network_scope="allowlisted_domains",
        resolved_ips=["10.0.0.8"],
    )

    assert decision.allowed is False
    assert decision.code == "PRIVATE_NETWORK_DENIED"


def test_egress_policy_rejects_dns_rebinding() -> None:
    decision = validate_egress_request(
        EgressPolicy(allow_hosts=["api.example.com"], max_response_bytes=4096),
        "https://api.example.com/data",
        network_scope="allowlisted_domains",
        validated_resolved_ips=["93.184.216.34"],
        resolved_ips=["10.0.0.8"],
    )

    assert decision.allowed is False
    assert decision.code == "DNS_REBINDING_DENIED"


def test_egress_policy_rejects_malformed_validated_dns_evidence() -> None:
    decision = validate_egress_request(
        EgressPolicy(allow_hosts=["api.example.com"], max_response_bytes=4096),
        "https://api.example.com/data",
        network_scope="allowlisted_domains",
        validated_resolved_ips=["not-an-ip"],
        resolved_ips=["93.184.216.34"],
    )

    assert decision.allowed is False
    assert decision.code == "INVALID_DNS_RESOLUTION"


def test_egress_policy_rejects_forbidden_redirect() -> None:
    decision = validate_egress_request(
        EgressPolicy(
            allow_hosts=["api.example.com"],
            redirect_policy={"follow": True},
            max_response_bytes=4096,
        ),
        "https://api.example.com/data",
        network_scope="allowlisted_domains",
        resolved_ips=["93.184.216.34"],
        redirect_url="https://evil.example.net/steal",
        redirect_resolved_ips=["93.184.216.35"],
    )

    assert decision.allowed is False
    assert decision.code == "HOST_NOT_ALLOWLISTED"


def test_egress_policy_rejects_metadata_endpoint() -> None:
    decision = validate_egress_request(
        EgressPolicy(allow_hosts=["169.254.169.254"], max_response_bytes=4096),
        "http://169.254.169.254/latest/meta-data/",
        network_scope="allowlisted_domains",
        resolved_ips=["169.254.169.254"],
    )

    assert decision.allowed is False
    assert decision.code == "METADATA_ENDPOINT_DENIED"


def test_egress_policy_rejects_oversized_response_contract() -> None:
    decision = validate_egress_request(
        EgressPolicy(allow_hosts=["api.example.com"], max_response_bytes=4096),
        "https://api.example.com/data",
        network_scope="allowlisted_domains",
        resolved_ips=["93.184.216.34"],
        response_content_length=4097,
    )

    assert decision.allowed is False
    assert decision.code == "RESPONSE_TOO_LARGE"


def test_activated_runtime_requires_response_byte_cap() -> None:
    decision = validate_egress_request(
        EgressPolicy(allow_hosts=["api.example.com"]),
        "https://api.example.com/data",
        network_scope="allowlisted_domains",
        target_type="api_tool",
        activated_target=True,
        resolved_ips=["93.184.216.34"],
    )

    assert decision.allowed is False
    assert decision.code == "RESPONSE_SIZE_CAP_REQUIRED"


def test_streaming_response_chunks_enforce_unknown_content_length_cap() -> None:
    policy = EgressPolicy(allow_hosts=["api.example.com"], max_response_bytes=4)

    first = validate_egress_response_chunk(
        policy,
        bytes_received=0,
        chunk_size=3,
        normalized_host="api.example.com",
        normalized_url="https://api.example.com/data",
        resolved_ips=["93.184.216.34"],
    )
    second = validate_egress_response_chunk(
        policy,
        bytes_received=3,
        chunk_size=2,
        normalized_host="api.example.com",
        normalized_url="https://api.example.com/data",
        resolved_ips=["93.184.216.34"],
    )

    assert first.allowed is True
    assert second.allowed is False
    assert second.code == "RESPONSE_TOO_LARGE"


def test_runtime_guard_rejects_missing_dns_evidence() -> None:
    decision = prepare_egress_runtime_guard(
        EgressPolicy(allow_hosts=["api.example.com"], max_response_bytes=4096),
        "https://api.example.com/data",
        network_scope="allowlisted_domains",
        target_type="api_tool",
        activated_target=True,
    )

    assert decision.allowed is False
    assert decision.code == "DNS_RESOLUTION_REQUIRED"


def test_runtime_guard_rejects_post_connect_ip_drift() -> None:
    guard = prepare_egress_runtime_guard(
        EgressPolicy(allow_hosts=["api.example.com"], max_response_bytes=4096),
        "https://api.example.com/data",
        network_scope="allowlisted_domains",
        target_type="api_tool",
        activated_target=True,
        resolved_ips=["93.184.216.34"],
    )

    assert guard.allowed is True
    decision = validate_runtime_egress(guard, connected_ips=["93.184.216.35"])

    assert decision.allowed is False
    assert decision.code == "DNS_REBINDING_DENIED"


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/",
        "http://127.1/",
        "http://127.0.1/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://0177.1/",
        "http://0x7f.0.0.1/",
    ],
)
def test_egress_policy_rejects_non_canonical_numeric_ip_hosts(url: str) -> None:
    decision = validate_egress_request(
        EgressPolicy(
            allow_hosts=[
                "2130706433",
                "127.1",
                "127.0.1",
                "0x7f000001",
                "0177.0.0.1",
                "0177.1",
                "0x7f.0.0.1",
            ],
            max_response_bytes=4096,
        ),
        url,
        network_scope="allowlisted_domains",
        resolved_ips=["93.184.216.34"],
    )

    assert decision.allowed is False
    assert decision.code == "INVALID_EGRESS_URL"


def test_egress_policy_rejects_invalid_port_without_exception() -> None:
    decision = validate_egress_request(
        EgressPolicy(allow_hosts=["api.example.com"], max_response_bytes=4096),
        "http://api.example.com:99999/",
        network_scope="allowlisted_domains",
        resolved_ips=["93.184.216.34"],
    )

    assert decision.allowed is False
    assert decision.code == "INVALID_EGRESS_URL"


def test_arbitrary_network_is_forbidden_for_activated_targets() -> None:
    decision = validate_egress_request(
        EgressPolicy(allow_hosts=["api.example.com"], max_response_bytes=4096),
        "https://api.example.com/data",
        network_scope="arbitrary_network",
        target_type="api_tool",
        activated_target=True,
        resolved_ips=["93.184.216.34"],
    )

    assert decision.allowed is False
    assert decision.code == "ARBITRARY_NETWORK_FORBIDDEN"


@pytest.mark.asyncio
async def test_standing_permission_expires(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        permission_overrides={
            "duration": "expires_at",
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, request)

    assert decision.allowed is False
    assert decision.confirmation_required is False
    assert decision.code == "STANDING_PERMISSION_EXPIRED"


@pytest.mark.asyncio
async def test_standing_permission_revocation_blocks_runtime(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        permission_overrides={
            "status": "revoked",
            "revoked_at": datetime.now(timezone.utc),
        },
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, request)

    assert decision.allowed is False
    assert decision.confirmation_required is False
    assert decision.code == "STANDING_PERMISSION_REVOKED"


@pytest.mark.asyncio
async def test_permission_boundary_change_requires_reapproval(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        runtime_scope={"hosts": ["api.weather.example", "api.billing.example"], "methods": ["GET"]},
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, request)

    assert decision.allowed is False
    assert decision.confirmation_required is False
    assert decision.code == "REAPPROVAL_REQUIRED"


@pytest.mark.parametrize(
    ("approved_risk", "runtime_risk"),
    [
        ("risky", "high_risk"),
        ("high_risk", "blocked"),
    ],
)
@pytest.mark.asyncio
async def test_runtime_risk_escalation_requires_reapproval(
    tenant_a_headers: dict[str, str],
    approved_risk: str,
    runtime_risk: str,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        bundle_overrides={"risk_level": runtime_risk},
        permission_overrides={"risk_level": approved_risk},
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, request)

    assert decision.allowed is False
    assert decision.confirmation_required is False
    assert decision.code == "REAPPROVAL_REQUIRED"


@pytest.mark.parametrize(
    ("source", "action_category"),
    [
        ("request", "email_send"),
        ("bundle", "wire_transfer"),
    ],
)
@pytest.mark.asyncio
async def test_unknown_action_category_requires_runtime_confirmation(
    tenant_a_headers: dict[str, str],
    source: str,
    action_category: str,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        action_category=action_category if source == "request" else "read",
        bundle_overrides={"action_category": action_category} if source == "bundle" else None,
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, request)

    assert decision.allowed is False
    assert decision.confirmation_required is True
    assert decision.code == "RUNTIME_CONFIRMATION_REQUIRED"
    assert decision.context["action_category"] == action_category


@pytest.mark.asyncio
async def test_permission_scope_subset_handles_list_of_dicts(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        bundle_overrides={
            "permission_scope": {
                "hosts": ["api.weather.example"],
                "filters": [{"field": "city", "op": "eq"}, {"field": "units", "op": "eq"}],
            },
        },
        runtime_scope={
            "hosts": ["api.weather.example"],
            "filters": [{"field": "city", "op": "eq"}],
        },
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, request)

    assert decision.allowed is True
    assert decision.code == "ALLOWED"


@pytest.mark.parametrize(
    "request_bundle_overrides",
    [
        {"network_scope": "arbitrary_network"},
        {"write_scope": "external_service"},
        {"credential_connection_refs": [str(uuid.uuid4()), str(uuid.uuid4())]},
        {"egress_policy": {"allow_hosts": ["api.weather.example", "api.billing.example"]}},
        {"credential_scope": "delegated_oauth"},
        {"tool_config": {"method": "POST"}},
        {"allowed_host_paths": ["/var/run/docker.sock"]},
        {"side_effect_category": "form_submit"},
    ],
)
@pytest.mark.asyncio
async def test_standing_permission_boundary_snapshot_expansion_requires_reapproval(
    tenant_a_headers: dict[str, str],
    request_bundle_overrides: dict,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        request_bundle_overrides=request_bundle_overrides,
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, request)

    assert decision.allowed is False
    assert decision.confirmation_required is False
    assert decision.code == "REAPPROVAL_REQUIRED"


@pytest.mark.asyncio
async def test_current_snapshot_hash_mismatch_requires_reapproval(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(tenant_id, user_id)
    changed_snapshot_request = RuntimePermissionRequest(
        **{
            **request.__dict__,
            "current_snapshot_hash": f"changed-{uuid.uuid4().hex}",
        }
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, changed_snapshot_request)

    assert decision.allowed is False
    assert decision.confirmation_required is False
    assert decision.code == "REAPPROVAL_REQUIRED"


def test_target_specific_policy_can_only_narrow_acquisition_decision() -> None:
    confirmation_decision = apply_target_policy_narrowing(
        PermissionDecision(
            allowed=False,
            confirmation_required=True,
            code="BASE_CONFIRM",
            message="base requires confirmation",
        ),
        TargetPolicyDecision(allowed=True, code="TARGET_ALLOWED", message="target allowed"),
    )

    allowed_decision = apply_target_policy_narrowing(
        PermissionDecision(allowed=True, confirmation_required=False, code="BASE_ALLOWED", message="base allowed"),
        TargetPolicyDecision(
            allowed=True,
            confirmation_required=True,
            code="TARGET_CONFIRMATION_REQUIRED",
            message="target requires confirmation",
        ),
    )

    assert confirmation_decision.allowed is False
    assert confirmation_decision.confirmation_required is True
    assert confirmation_decision.code == "BASE_CONFIRM"
    assert allowed_decision.allowed is False
    assert allowed_decision.confirmation_required is True
    assert allowed_decision.code == "TARGET_CONFIRMATION_REQUIRED"


@pytest.mark.asyncio
async def test_acquisition_policy_is_final_permission_gate(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        runtime_scope={"hosts": ["api.weather.example"], "methods": ["GET", "POST"]},
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(
            db,
            request,
            target_policy=TargetPolicyDecision(allowed=True, code="TARGET_POLICY_ALLOWED"),
        )

    assert decision.allowed is False
    assert decision.confirmation_required is False
    assert decision.code == "REAPPROVAL_REQUIRED"


@pytest.mark.asyncio
async def test_api_tool_definitions_are_user_scoped_within_tenant(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, owner_user_id = _identity(tenant_a_headers)
    other_user_id = uuid.uuid4()
    request = await _runtime_permission_request(tenant_id, owner_user_id)

    async with _async_session_factory() as db:
        db.add(_api_config_from_request(request, name="owner-weather"))
        await db.commit()

    async with _async_session_factory() as db:
        owner_tools = await get_api_tool_definitions(db, tenant_id, user_id=owner_user_id)
        other_tools = await get_api_tool_definitions(db, tenant_id, user_id=other_user_id)

    assert any(tool["function"]["name"] == api_tool_name("owner-weather") for tool in owner_tools)
    assert all(tool["function"]["name"] != api_tool_name("owner-weather") for tool in other_tools)


@pytest.mark.asyncio
async def test_api_tool_execution_always_applies_acquisition_permission_gate(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        permission_overrides={
            "status": "revoked",
            "revoked_at": datetime.now(timezone.utc),
        },
    )

    async with _async_session_factory() as db:
        db.add(_api_config_from_request(request, name="revoked-weather"))
        await db.commit()

    result = await execute_api_tool(
        api_tool_name("revoked-weather"),
        {"city": "Paris"},
        context={"tenant_id": tenant_id, "user_id": user_id},
    )
    payload = json.loads(result)

    assert payload["ok"] is False
    assert payload["error"]["errorCode"] == "STANDING_PERMISSION_REVOKED"
    assert "Paris" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_api_tool_runtime_credential_resolution_uses_target_descriptor(
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(tenant_id, user_id)
    async with _async_session_factory() as db:
        credential = await create_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Descriptor API key",
            provider="weather.example",
            connection_type="api_key",
            credential_kind="api_key",
            secret_storage_kind="encrypted_db",
            secret_value=f"sk-descriptor-{uuid.uuid4().hex}",
            allowed_target_types=["api_tool"],
            allowed_target_refs=[{"tool_name": api_tool_name("descriptor-weather")}],
        )
        config = _api_config_from_request(request, name="descriptor-weather")
        config.auth_scheme = "bearer"
        config.credential_ref = credential.id
        config.credential_generation = credential.secret_generation
        db.add(config)
        await db.commit()

    captured: dict[str, Any] = {}

    async def fake_resolve_credential_secret(
        db,
        *,
        tenant_id,
        user_id,
        credential_connection_id,
        target_type,
        target_ref,
    ) -> str:
        captured["target_type"] = target_type
        captured["target_ref"] = target_ref
        return "secret"

    class FakeAPIToolRuntimeClient:
        def __init__(self, policy, *, credential_resolver=None, **kwargs):
            self.policy = policy
            self.credential_resolver = credential_resolver

        async def execute(self, args, *, context=None):
            assert self.credential_resolver is not None
            await self.credential_resolver(self.policy.credential_ref)
            return {"ok": True}

    monkeypatch.setattr(api_runtime_registry, "resolve_credential_secret", fake_resolve_credential_secret)
    monkeypatch.setattr(api_runtime_registry, "APIToolRuntimeClient", FakeAPIToolRuntimeClient)

    result = json.loads(
        await execute_api_tool(
            api_tool_name("descriptor-weather"),
            {"city": "Paris"},
            context={"tenant_id": tenant_id, "user_id": user_id},
        )
    )

    assert result == {"ok": True}
    assert captured["target_type"] == "api_tool"
    assert captured["target_ref"]["tool_name"] == api_tool_name("descriptor-weather")
    assert captured["target_ref"]["activation_target_id"] == str(request.target_id)


@pytest.mark.asyncio
async def test_model_supplied_confirmed_does_not_bypass_api_tool_confirmation(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        action_category="external_write",
    )
    config = _api_config_from_request(request, name="write-weather")
    config.method = "POST"
    config.path_template = "/weather"
    config.idempotency_policy = {"idempotent": False, "action_category": "external_write"}

    async with _async_session_factory() as db:
        db.add(config)
        await db.commit()

    with pytest.raises(APIToolConfirmationRequired) as exc:
        await execute_api_tool(
            api_tool_name("write-weather"),
            {"city": "Paris", "__confirmed": True, "api_key": "model-secret"},
            context={"tenant_id": tenant_id, "user_id": user_id},
        )

    expected_request = RuntimePermissionRequest(
        **{
            **request.__dict__,
            "risk_level": "safe",
            "action_category": "external_write",
            "tool_context": {
                "tool_name": api_tool_name("write-weather"),
                "method": "POST",
                "base_url": "https://api.weather.example",
                "path_template": "/weather",
            },
        }
    )
    exact_context = build_runtime_confirmation_context(expected_request)
    assert exc.value.code == "RUNTIME_CONFIRMATION_REQUIRED"
    assert exc.value.confirmation_context == exact_context
    assert exc.value.sanitized_args == {"city": "Paris", "api_key": "[REDACTED]"}
    assert "__confirmed" not in exc.value.sanitized_args
    assert "model-secret" not in json.dumps(exc.value.sanitized_args)


@pytest.mark.asyncio
async def test_runtime_confirmation_context_uses_same_policy_gate(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    generic_request = await _runtime_permission_request(
        tenant_id,
        user_id,
        action_category="send",
        confirmation_context={"confirmed": True, "reason": "user clicked OK"},
    )

    async with _async_session_factory() as db:
        generic_decision = await evaluate_runtime_permission(db, generic_request)

    exact_context = build_runtime_confirmation_context(generic_request)
    exact_request = RuntimePermissionRequest(
        **{
            **generic_request.__dict__,
            "confirmation_context": {**exact_context, "confirmed": True},
        }
    )
    async with _async_session_factory() as db:
        exact_decision = await evaluate_runtime_permission(db, exact_request)

    assert generic_decision.allowed is False
    assert generic_decision.confirmation_required is True
    assert generic_decision.code == "RUNTIME_CONFIRMATION_REQUIRED"
    assert exact_decision.allowed is True
    assert exact_decision.confirmation_required is False
    assert exact_decision.code == "ALLOWED"


@pytest.mark.parametrize(
    ("bundle_field", "action_category"),
    [
        ("action_category", "message_send"),
        ("side_effect_category", "form_submit"),
        ("action_category", "payment"),
    ],
)
@pytest.mark.asyncio
async def test_bundle_dangerous_action_requires_runtime_confirmation_when_request_says_read(
    tenant_a_headers: dict[str, str],
    bundle_field: str,
    action_category: str,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        bundle_overrides={bundle_field: action_category},
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, request)

    assert request.action_category == "read"
    assert decision.allowed is False
    assert decision.confirmation_required is True
    assert decision.code == "RUNTIME_CONFIRMATION_REQUIRED"
    assert decision.context["action_category"] == action_category


@pytest.mark.asyncio
async def test_exact_confirmation_with_bundle_effective_action_category_passes(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        bundle_overrides={"action_category": "payment"},
    )
    exact_context = build_runtime_confirmation_context(request)
    exact_request = RuntimePermissionRequest(
        **{
            **request.__dict__,
            "confirmation_context": {**exact_context, "confirmed": True},
        }
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, exact_request)

    assert request.action_category == "read"
    assert exact_context["action_category"] == "payment"
    assert decision.allowed is True
    assert decision.confirmation_required is False
    assert decision.code == "ALLOWED"


@pytest.mark.parametrize(
    "action_category",
    [
        "message_send",
        "form_submit",
        "non_idempotent_side_effect",
        "sends",
        "submits",
        "bookings",
        "payments",
        "ordering",
        "order",
        "deleting",
        "deletion",
        "overwriting",
        "deployment",
        "browser external write",
    ],
)
@pytest.mark.asyncio
async def test_action_category_aliases_require_runtime_confirmation(
    tenant_a_headers: dict[str, str],
    action_category: str,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    request = await _runtime_permission_request(
        tenant_id,
        user_id,
        action_category=action_category,
    )

    async with _async_session_factory() as db:
        decision = await evaluate_runtime_permission(db, request)

    assert decision.allowed is False
    assert decision.confirmation_required is True
    assert decision.code == "RUNTIME_CONFIRMATION_REQUIRED"


@pytest.mark.asyncio
async def test_credential_connection_encrypts_secret_material(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    raw_secret = f"sk-weather-{uuid.uuid4().hex}"

    async with _async_session_factory() as db:
        credential = await create_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Weather API key",
            provider="weather.example",
            connection_type="api_key",
            credential_kind="api_key",
            secret_storage_kind="encrypted_db",
            secret_value=raw_secret,
            allowed_target_types=["api_tool"],
        )
        await db.commit()

    assert credential.secret_ref != raw_secret
    assert raw_secret not in credential.secret_ref
    assert decrypt_secret(credential.secret_ref) == raw_secret
    assert credential.secret_generation == 1
    assert credential.status == "active"
    assert credential.metadata_redacted["configured"] is True


@pytest.mark.asyncio
async def test_credential_connection_response_redacts_secret_material(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    raw_secret = f"sk-redacted-{uuid.uuid4().hex}"

    async with _async_session_factory() as db:
        credential = await create_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Redacted API key",
            provider="weather.example",
            connection_type="api_key",
            credential_kind="api_key",
            secret_storage_kind="encrypted_db",
            secret_value=raw_secret,
            scopes=["weather:read"],
            allowed_target_types=["api_tool"],
            metadata_redacted={"label": "weather key"},
        )
        response = credential_connection_response(credential)
        await db.commit()

    payload = response.model_dump(mode="json")
    payload_text = str(payload)

    assert payload["secret_ref_present"] is True
    assert "secret_ref" not in payload
    assert raw_secret not in payload_text
    assert credential.secret_ref not in payload_text
    assert response.metadata_redacted["configured"] is True
    assert response.metadata_redacted["label"] == "weather key"


@pytest.mark.asyncio
async def test_revoked_credential_blocks_dependent_target_execution(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    raw_secret = f"sk-runtime-{uuid.uuid4().hex}"

    async with _async_session_factory() as db:
        credential = await create_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Runtime API key",
            provider="weather.example",
            connection_type="api_key",
            credential_kind="api_key",
            secret_storage_kind="encrypted_db",
            secret_value=raw_secret,
            allowed_target_types=["api_tool"],
            allowed_target_refs=[{"target_name": "weather"}],
        )
        await db.commit()

    proposal = await _runtime_proposal(tenant_id, user_id, credential.id)
    async with _async_session_factory() as db:
        verification = await verify_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            verification_kind="contract",
            input_fixture={"city": "London"},
            expected_result={"ok": True},
            actual_result={"ok": True},
            artifact_refs=[{"artifact_id": "verify-weather", "digest": "sha256:evidence"}],
            idempotency_key=f"verify-{uuid.uuid4().hex}",
        )
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
        )
        await start_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            verification_id=verification.id,
        )
        target = ActivationTarget(
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            target_type="api_tool",
            target_name="weather",
            target_owner="core.api_tools",
            target_payload={"base_url": "https://api.weather.example"},
            permission_bundle=_permission_bundle(credential.id),
            verification_plan={"kind": "contract"},
            rollback_plan={"disable": True},
            activation_status="activation_pending",
            activation_result={"phase": "activation_pending"},
        )
        db.add(target)
        await db.flush()
        db.add(
            APIToolConfiguration(
                tenant_id=tenant_id,
                user_id=user_id,
                activation_target_id=target.id,
                name="weather",
                tool_name=api_tool_name("weather"),
                base_url="https://api.weather.example",
                method="GET",
                path_template="/weather",
                headers_schema={},
                auth_scheme="api_key",
                credential_ref=credential.id,
                credential_generation=credential.secret_generation,
                input_schema={},
                output_schema={},
                allowed_hosts=["api.weather.example"],
                deny_private_networks=True,
                redirect_policy={"follow": False},
                allowed_content_types=["application/json"],
                max_request_bytes=1024,
                max_response_bytes=4096,
                idempotency_policy={"safe": True},
                response_redaction_policy={},
                rate_limit={"rpm": 60},
                timeout_s=5,
                retry_policy={"retries": 0},
                error_contract={},
                enabled=True,
                risk_level="safe",
            )
        )
        await revoke_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            credential_connection_id=credential.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await run_activation_saga(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                approved_hash=verification.verified_snapshot_hash,
                verification_id=verification.id,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "PROPOSAL_NOT_ACTIVATING"
    async with _async_session_factory() as db:
        persisted_proposal = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        persisted_target = (
            await db.execute(select(ActivationTarget).where(ActivationTarget.proposal_id == proposal.id))
        ).scalar_one()
        api_tool = (
            await db.execute(select(APIToolConfiguration).where(APIToolConfiguration.activation_target_id == persisted_target.id))
        ).scalar_one()

    assert persisted_proposal.status == "verification_stale"
    assert persisted_proposal.activation_snapshot_hash is None
    assert persisted_target.activation_status == "disabled"
    assert api_tool.enabled is False


@pytest.mark.asyncio
async def test_revoked_credential_disables_direct_api_config_when_proposal_bundle_is_stale(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)

    async with _async_session_factory() as db:
        stale_bundle_credential = await create_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Stale proposal API key",
            provider="weather.example",
            connection_type="api_key",
            credential_kind="api_key",
            secret_storage_kind="encrypted_db",
            secret_value=f"sk-stale-{uuid.uuid4().hex}",
            allowed_target_types=["api_tool"],
        )
        direct_config_credential = await create_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Direct config API key",
            provider="weather.example",
            connection_type="api_key",
            credential_kind="api_key",
            secret_storage_kind="encrypted_db",
            secret_value=f"sk-direct-{uuid.uuid4().hex}",
            allowed_target_types=["api_tool"],
        )
        await db.commit()

    proposal = await _runtime_proposal(tenant_id, user_id, stale_bundle_credential.id)
    async with _async_session_factory() as db:
        verification = await verify_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            verification_kind="contract",
            input_fixture={"city": "London"},
            expected_result={"ok": True},
            actual_result={"ok": True},
            artifact_refs=[{"artifact_id": "verify-weather", "digest": "sha256:evidence"}],
            idempotency_key=f"verify-{uuid.uuid4().hex}",
        )
        api_tool = APIToolConfiguration(
            tenant_id=tenant_id,
            user_id=user_id,
            activation_target_id=None,
            name="weather-direct",
            tool_name=api_tool_name("weather-direct"),
            base_url="https://api.weather.example",
            method="GET",
            path_template="/weather",
            headers_schema={},
            auth_scheme="api_key",
            credential_ref=direct_config_credential.id,
            credential_generation=direct_config_credential.secret_generation,
            input_schema={},
            output_schema={},
            allowed_hosts=["api.weather.example"],
            deny_private_networks=True,
            redirect_policy={"follow": False},
            allowed_content_types=["application/json"],
            max_request_bytes=1024,
            max_response_bytes=4096,
            idempotency_policy={"safe": True},
            response_redaction_policy={},
            rate_limit={"rpm": 60},
            timeout_s=5,
            retry_policy={"retries": 0},
            error_contract={},
            enabled=True,
            risk_level="safe",
        )
        db.add(api_tool)
        await db.flush()
        api_tool_id = api_tool.id
        await revoke_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            credential_connection_id=direct_config_credential.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        persisted_proposal = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        persisted_api_tool = (
            await db.execute(select(APIToolConfiguration).where(APIToolConfiguration.id == api_tool_id))
        ).scalar_one()

    assert verification.verified_snapshot_hash is not None
    assert persisted_proposal.status == "verified"
    assert persisted_proposal.activation_snapshot_hash == verification.verified_snapshot_hash
    assert persisted_api_tool.enabled is False
    assert persisted_api_tool.last_verified_at is None


@pytest.mark.asyncio
async def test_llm_provider_and_channel_credentials_are_not_reowned(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    provider_secret = f"llm-{uuid.uuid4().hex}"
    channel_secret = f"channel-{uuid.uuid4().hex}"

    async with _async_session_factory() as db:
        llm_provider = LLMProvider(
            tenant_id=tenant_id,
            name=f"policy-llm-{uuid.uuid4().hex}",
            api_base="https://llm.example/v1",
            encrypted_api_key=provider_secret,
            model="gpt-test",
        )
        channel = ChannelConfiguration(
            tenant_id=tenant_id,
            channel_type=f"policy-channel-{uuid.uuid4().hex}",
            public_config={},
            encrypted_secrets=channel_secret,
        )
        db.add_all([llm_provider, channel])
        credential = await create_credential_connection(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="New acquisition key",
            provider="weather.example",
            connection_type="api_key",
            credential_kind="api_key",
            secret_storage_kind="encrypted_db",
            secret_value=f"sk-new-{uuid.uuid4().hex}",
        )
        await db.commit()

    async with _async_session_factory() as db:
        persisted_provider = (
            await db.execute(select(LLMProvider).where(LLMProvider.id == llm_provider.id))
        ).scalar_one()
        persisted_channel = (
            await db.execute(select(ChannelConfiguration).where(ChannelConfiguration.id == channel.id))
        ).scalar_one()

    assert persisted_provider.encrypted_api_key == provider_secret
    assert persisted_channel.encrypted_secrets == channel_secret
    assert credential.id != persisted_provider.id
    assert credential.id != persisted_channel.id
