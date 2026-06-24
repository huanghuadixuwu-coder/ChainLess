"""Focused tests for W2.3 acquired tool manifest invalidation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.api.deps import _async_session_factory
from app.core.acquisition.tool_manifest import CONFIG_MODELS, hide_target_manifest_refs
from app.core.tools.api_runtime import execute_api_tool
from app.core.tools.manifest import (
    assert_manifest_version_current,
    build_user_tool_manifest,
    get_user_tool_manifest_version,
)
from app.models.acquisition import (
    AcquisitionProposal,
    APIToolConfiguration,
    ActivationTarget,
    CapabilityGap,
    CapabilityRecommendation,
)
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


def _target_graph(tenant_id: uuid.UUID, user_id: uuid.UUID) -> tuple[CapabilityGap, CapabilityRecommendation, AcquisitionProposal, ActivationTarget]:
    gap_id = uuid.uuid4()
    rec_id = uuid.uuid4()
    proposal_id = uuid.uuid4()
    gap = CapabilityGap(
        id=gap_id,
        tenant_id=tenant_id,
        user_id=user_id,
        source_kind="test",
        source_run_id=f"manifest-{uuid.uuid4().hex}",
        dedupe_key=f"manifest:{uuid.uuid4().hex}",
        title="Manifest test gap",
        description="Manifest test gap",
        gap_type="missing_api",
        severity="low",
        status="detected",
        source_evidence=[],
        evidence={},
    )
    rec = CapabilityRecommendation(
        id=rec_id,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        recommendation_type="api_recommendation",
        title="Manifest test recommendation",
        summary="Manifest test recommendation",
        reason="test",
        evidence={},
        risk_level="safe",
        expected_value={},
        required_permissions={},
        candidate_targets=[],
    )
    proposal = AcquisitionProposal(
        id=proposal_id,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        recommendation_id=rec_id,
        proposal_kind="runtime_activation",
        title="Manifest test proposal",
        reason="test",
        evidence={},
        status="activated",
        risk_level="safe",
        permission_bundle={},
        primary_target={"target_type": "api_tool", "target_name": "weather"},
        secondary_targets=[],
        verification_plan={},
        rollback_plan={},
        user_visible_effect="test",
        approval_history=[],
    )
    target = ActivationTarget(
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        target_type="api_tool",
        target_name="weather",
        target_owner="core.api_tools",
        target_payload={},
        permission_bundle={},
        verification_plan={},
        rollback_plan={"disable": True},
        activation_status="active",
        activation_result={
            "tool_manifest": {
                "manifest_version": "2026-06-24T00:00:01+00:00",
                "tool_name": "api__weather",
            }
        },
        activated_resource_ref={"manifest_ref": "api_tool:api__weather"},
    )
    return gap, rec, proposal, target


async def test_manifest_owner_covers_user_visible_activation_target_types() -> None:
    assert {"api_tool", "mcp_tool", "workspace_connector", "browser_automation"}.issubset(CONFIG_MODELS)


async def test_hide_target_manifest_refs_marks_resource_ref_hidden() -> None:
    target = ActivationTarget(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        proposal_id=uuid.uuid4(),
        target_type="api_tool",
        target_name="weather",
        target_owner="core.api_tools",
        target_payload={},
        permission_bundle={},
        verification_plan={},
        rollback_plan={"disable": True},
        activation_status="active",
        activation_result={},
        activated_resource_ref={"manifest_ref": "api_tool:weather"},
    )

    async with _async_session_factory() as db:
        evidence = await hide_target_manifest_refs(
            db,
            target=target,
            idempotency_key="manifest-hide",
        )

    assert evidence["status"] == "hidden"
    assert target.activated_resource_ref["hidden"] is True
    assert target.activation_result["tool_manifest"]["idempotency_key"] == "manifest-hide"


async def test_activation_bumps_user_tool_manifest_version_and_next_run_sees_tool(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap, rec, proposal, target = _target_graph(tenant_id, user_id)

    async with _async_session_factory() as db:
        db.add(gap)
        await db.flush()
        db.add(rec)
        await db.flush()
        db.add(proposal)
        await db.flush()
        db.add(target)
        await db.flush()
        version = await get_user_tool_manifest_version(db, tenant_id=tenant_id, user_id=user_id)

    assert version == "2026-06-24T00:00:01+00:00"
    assert_manifest_version_current(version, expected_version="2026-06-24T00:00:01+00:00")


async def test_manifest_only_exposes_verified_active_non_hidden_runtime_configs(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap, rec, proposal, target = _target_graph(tenant_id, user_id)

    async with _async_session_factory() as db:
        db.add(gap)
        await db.flush()
        db.add(rec)
        await db.flush()
        db.add(proposal)
        await db.flush()
        db.add(target)
        await db.flush()
        config = APIToolConfiguration(
            tenant_id=tenant_id,
            user_id=user_id,
            activation_target_id=target.id,
            name="weather",
            tool_name="api__weather",
            base_url="https://api.weather.example",
            method="GET",
            path_template="/weather",
            headers_schema={},
            auth_scheme="none",
            input_schema={},
            output_schema={},
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
            error_contract={},
            enabled=True,
            risk_level="safe",
            last_verified_at=datetime.now(timezone.utc),
        )
        db.add(config)
        await db.flush()
        visible_manifest = await build_user_tool_manifest(db, tenant_id=tenant_id, user_id=user_id)
        config.last_verified_at = None
        unverified_manifest = await build_user_tool_manifest(db, tenant_id=tenant_id, user_id=user_id)
        config.last_verified_at = datetime.now(timezone.utc)
        target.activated_resource_ref = {"manifest_ref": "api_tool:api__weather", "hidden": True}
        hidden_manifest = await build_user_tool_manifest(db, tenant_id=tenant_id, user_id=user_id)

    assert any(tool["tool_name"] == "api__weather" for tool in visible_manifest["tools"])
    assert all(tool.get("tool_name") != "api__weather" for tool in unverified_manifest["tools"])
    assert all(tool.get("tool_name") != "api__weather" for tool in hidden_manifest["tools"])


async def test_revocation_or_rollback_bumps_manifest_and_resumed_run_cannot_see_stale_tool(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap, rec, proposal, target = _target_graph(tenant_id, user_id)

    async with _async_session_factory() as db:
        db.add(gap)
        await db.flush()
        db.add(rec)
        await db.flush()
        db.add(proposal)
        await db.flush()
        db.add(target)
        await db.flush()
        old_version = await get_user_tool_manifest_version(db, tenant_id=tenant_id, user_id=user_id)
        await hide_target_manifest_refs(db, target=target, idempotency_key="rollback")
        new_version = await get_user_tool_manifest_version(db, tenant_id=tenant_id, user_id=user_id)
        manifest = await build_user_tool_manifest(db, tenant_id=tenant_id, user_id=user_id)

    assert new_version != old_version
    assert new_version != "empty"
    assert manifest["version"] == new_version
    with pytest.raises(ValueError, match="ACQUIRED_TOOL_MANIFEST_STALE"):
        assert_manifest_version_current(new_version, expected_version=old_version)


async def test_acquired_api_runtime_enforces_manifest_version_on_execution(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    gap, rec, proposal, target = _target_graph(tenant_id, user_id)

    async with _async_session_factory() as db:
        db.add(gap)
        await db.flush()
        db.add(rec)
        await db.flush()
        db.add(proposal)
        await db.flush()
        db.add(target)
        await db.flush()
        db.add(
            APIToolConfiguration(
                tenant_id=tenant_id,
                user_id=user_id,
                activation_target_id=target.id,
                name="weather",
                tool_name="api__weather",
                base_url="https://api.weather.example",
                method="GET",
                path_template="/weather",
                headers_schema={},
                auth_scheme="none",
                input_schema={},
                output_schema={},
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
                error_contract={},
                enabled=True,
                risk_level="safe",
                last_verified_at=datetime.now(timezone.utc),
            )
        )
        await db.flush()
        old_version = await get_user_tool_manifest_version(db, tenant_id=tenant_id, user_id=user_id)
        await hide_target_manifest_refs(db, target=target, idempotency_key="rollback-runtime")
        await db.commit()

    with pytest.raises(ValueError, match="ACQUIRED_TOOL_MANIFEST_STALE"):
        await execute_api_tool(
            "api__weather",
            {},
            context={
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "acquired_tool_manifest_version": old_version,
            },
        )
