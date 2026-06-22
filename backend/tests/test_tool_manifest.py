"""Focused tests for W2.3 acquired tool manifest invalidation."""

from __future__ import annotations

import uuid

import pytest

from app.api.deps import _async_session_factory
from app.core.acquisition.tool_manifest import CONFIG_MODELS, hide_target_manifest_refs
from app.models.acquisition import ActivationTarget

pytestmark = pytest.mark.asyncio


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
