"""Acquisition disabled-mode contracts for W7."""

from __future__ import annotations

import inspect
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.acquisition.facade import (
    ACQUISITION_SSE_EVENT_NAMES,
    acquisition_notice,
    enqueue_runtime_analysis,
    record_code_as_action_exploration,
    runtime_capability_enabled,
)
from app.core.agent.tool_router import execute_tool
from app.services.conversation_stream_service import get_agent_tools
from app.services.conversation_stream_service import execute_confirmed_tool
from app.models.acquisition import AcquisitionAnalysisJob, CapabilityGap
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


async def test_acquisition_disabled_keeps_chat_v2_inbox_workers_file_tools_and_normal_agent_execution_working(
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    monkeypatch.setattr("app.core.acquisition.facade.settings.acquisition_enabled", False)

    async with _async_session_factory() as db:
        await record_code_as_action_exploration(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id="disabled-code",
            tool_call_id="disabled-call",
            script="print(42)",
            status="succeeded",
            risk_level="safe",
            stdout="42\n",
        )
        job = await enqueue_runtime_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id="disabled-stream",
            source_kind="conversation_stream",
            payload={"status": "completed"},
        )
        await db.commit()

        gaps = list(
            (
                await db.execute(
                    select(CapabilityGap).where(
                        CapabilityGap.tenant_id == tenant_id,
                        CapabilityGap.user_id == user_id,
                        CapabilityGap.source_run_id == "disabled-code",
                    )
                )
            ).scalars()
        )
        jobs = list(
            (
                await db.execute(
                    select(AcquisitionAnalysisJob).where(
                        AcquisitionAnalysisJob.tenant_id == tenant_id,
                        AcquisitionAnalysisJob.user_id == user_id,
                        AcquisitionAnalysisJob.source_run_id == "disabled-stream",
                    )
                )
            ).scalars()
        )

    tools = await get_agent_tools(str(tenant_id), str(user_id))
    tool_names = {tool.get("function", {}).get("name") for tool in tools}

    assert job is None
    assert gaps == []
    assert jobs == []
    assert "file_read" in tool_names
    assert "file_write" in tool_names
    assert "code_as_action" in tool_names
    assert runtime_capability_enabled("api_tool") is False
    assert runtime_capability_enabled("code_as_action") is True


async def test_acquisition_disabled_routes_and_ui_return_clear_disabled_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.acquisition.facade.settings.acquisition_enabled", False)
    assert runtime_capability_enabled("browser_automation") is False
    assert runtime_capability_enabled("workspace_connector") is False


async def test_runtime_capability_flags_disable_individual_acquired_runtimes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.acquisition.facade.settings.acquisition_api_runtime_enabled", False)
    monkeypatch.setattr("app.core.acquisition.facade.settings.acquisition_mcp_runtime_enabled", False)
    monkeypatch.setattr("app.core.acquisition.facade.settings.acquisition_workspace_connectors_enabled", False)
    assert runtime_capability_enabled("api_tool") is False
    assert runtime_capability_enabled("mcp_tool") is False
    assert runtime_capability_enabled("workspace_connector") is False


async def test_mcp_runtime_flag_hides_and_blocks_mcp_tools(
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    monkeypatch.setattr("app.core.acquisition.facade.settings.acquisition_mcp_runtime_enabled", False)
    monkeypatch.setattr(
        "app.services.conversation_stream_service.mcp_manager.get_all_tools",
        lambda tenant_scope: [{"type": "function", "function": {"name": "mcp__demo__echo"}}],
    )

    tools = await get_agent_tools(str(tenant_id), str(user_id))
    assert "mcp__demo__echo" not in {tool.get("function", {}).get("name") for tool in tools}
    with pytest.raises(ValueError, match="MCP runtime is disabled"):
        await execute_tool(
            "mcp__demo__echo",
            {"text": "blocked"},
            context={"tenant_id": str(tenant_id), "user_id": str(user_id)},
        )


async def test_confirmed_code_as_action_respects_runtime_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.acquisition.facade.settings.acquisition_code_as_action_enabled", False)

    with pytest.raises(ValueError, match="Code-as-action runtime is disabled"):
        await execute_confirmed_tool(
            "code_as_action",
            {"script": "print(42)"},
            sandbox=object(),
            gateway=object(),
            tenant_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
        )


async def test_available_tools_endpoint_uses_runtime_visibility(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.acquisition.facade.settings.acquisition_code_as_action_enabled", False)

    response = await client.get("/api/v1/tools/available?limit=200&offset=0", headers=tenant_a_headers)
    assert response.status_code == 200, response.text
    names = {tool.get("function", {}).get("name") for tool in response.json()["items"]}
    assert "file_read" in names
    assert "code_as_action" not in names


async def test_acquisition_sse_event_names_match_spec_contract() -> None:
    assert ACQUISITION_SSE_EVENT_NAMES == {
        "acquisition_gap",
        "acquisition_exploration",
        "acquisition_recommendation",
        "acquisition_approval_required",
        "acquisition_verification",
        "acquisition_activation",
        "acquisition_runtime_planning_issue",
        "acquisition_permission",
        "acquisition_browser_trace",
    }
    notice = acquisition_notice(
        "acquisition_gap",
        {
            "problem": "missing tool api_key=abc Authorization: Bearer secret-token",
            "access_token": "abc",
            "secret": "token=abc",
        },
    )
    assert notice["type"] == "acquisition_gap"
    assert "secret" not in repr(notice)
    assert "token=abc" not in repr(notice)
    assert "api_key=abc" not in repr(notice)
    assert "Bearer secret-token" not in repr(notice)


async def test_stream_service_calls_acquisition_facade_only() -> None:
    import app.services.conversation_stream_service as stream_service

    source = inspect.getsource(stream_service)
    assert "app.core.acquisition.facade import" in source
    assert "enqueue_runtime_analysis" in source
    forbidden = (
        "app.core.acquisition.lifecycle",
        "app.core.acquisition.repository",
        "app.core.acquisition.policy",
        "app.core.credentials",
        "app.core.browser_automation.registry",
    )
    for import_path in forbidden:
        assert import_path not in source
