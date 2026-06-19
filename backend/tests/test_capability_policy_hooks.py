"""W6 hard-guard and internal hook contracts for Worker execution."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.capabilities.hooks import clear_hook_events, get_hook_events
from app.core.capabilities.policy import (
    WorkerPolicyError,
    evaluate_worker_policy,
)
from app.core.workers.runtime import execute_worker_run
from app.models.capability import CapabilityCandidate
from app.models.worker import Worker, WorkerRun, WorkerVersion
from app.services.auth_service import decode_token
from app.services.conversation_stream_service import execute_confirmed_tool

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> dict[str, str]:
    return decode_token(headers["Authorization"].split(" ", 1)[1])


async def _active_worker(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str = "Policy hook worker",
    trigger: dict | None = None,
    policy: dict | None = None,
    definition: dict | None = None,
) -> tuple[Worker, WorkerVersion]:
    async with _async_session_factory() as db:
        worker = Worker(
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"{name} {uuid.uuid4().hex}",
            description="policy hook test worker",
            status="active",
            enabled=True,
            trigger=trigger or {"examples": ["policy hook"], "keywords": ["policy"]},
            policy=policy or {"allowed_tools": ["weather_get"], "risk": "low"},
            activation_evidence={"approved_by": "test"},
            activation_confirmed_at=datetime.now(timezone.utc),
            activation_confirmed_by=user_id,
        )
        db.add(worker)
        await db.flush()
        version = WorkerVersion(
            tenant_id=tenant_id,
            user_id=user_id,
            worker_id=worker.id,
            version=1,
            status="active",
            definition=definition
            or {
                "instructions": "Exercise policy hooks.",
                "input_schema": {
                    "type": "object",
                    "required": ["request"],
                    "properties": {"request": {"type": "string"}},
                },
            },
            verification_evidence={"tests": "passed"},
            verified_at=datetime.now(timezone.utc),
            verified_by=user_id,
            activated_at=datetime.now(timezone.utc),
        )
        db.add(version)
        await db.flush()
        worker.active_version_id = version.id
        await db.commit()
        await db.refresh(worker)
        await db.refresh(version)
        return worker, version


class TextGateway:
    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        yield {"type": "text", "content": "worker ok"}


class DestructiveToolGateway:
    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        yield {
            "type": "tool_call",
            "index": 0,
            "id": "call-shell",
            "name": "shell_exec",
            "arguments": '{"cmd":"echo hi","api_key":"secret-value"}',
        }


class WebFetchGateway:
    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        yield {
            "type": "tool_call",
            "index": 0,
            "id": "call-web",
            "name": "web_fetch",
            "arguments": '{"url":"https://example.com"}',
        }


class FailingThenFallbackGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("worker failed")
        yield {"type": "text", "content": "fallback ok"}


async def test_worker_policy_requires_external_delivery_and_destructive_confirmation(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    external_worker, external_version = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        policy={"allowed_tools": [], "risk": "low", "external_delivery": True},
        definition={"instructions": "Deliver externally."},
    )
    destructive_worker, destructive_version = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        policy={"allowed_tools": ["shell_exec"], "risk": "destructive"},
        definition={"instructions": "Run a destructive action."},
    )

    assert evaluate_worker_policy(
        external_worker,
        external_version,
        input_payload={},
    ).action == "confirm"
    assert evaluate_worker_policy(
        destructive_worker,
        destructive_version,
        input_payload={},
    ).reason == "worker_risk_requires_confirmation"
    definition_external_worker, definition_external_version = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        policy={"allowed_tools": [], "risk": "low"},
        definition={"instructions": "Deliver externally.", "external_delivery": True},
    )
    assert evaluate_worker_policy(
        definition_external_worker,
        definition_external_version,
        input_payload={},
    ).action == "confirm"


async def test_hook_records_denied_worker_run_and_cannot_override_policy(
    tenant_a_headers: dict[str, str],
) -> None:
    clear_hook_events()
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, version = await _active_worker(tenant_id=tenant_id, user_id=user_id)

    async with _async_session_factory() as db:
        result = await execute_worker_run(
            db,
            gateway=TextGateway(),
            sandbox_manager=object(),
            provider="default",
            worker=await db.get(Worker, worker.id),
            version=await db.get(WorkerVersion, version.id),
            messages=[{"role": "user", "content": "policy hook"}],
            input_payload={},
            matched_request="policy hook",
            match_score=0.9,
        )

    assert result["status"] == "blocked_by_policy"
    assert result["reason"] == "missing_required_input"
    events = get_hook_events()
    assert [event["name"] for event in events if event["name"] in {"before_worker_run", "after_worker_run"}] == [
        "before_worker_run",
        "after_worker_run",
    ]
    after = next(event for event in events if event["name"] == "after_worker_run")
    assert after["payload"]["policy_action"] == "block"
    assert after["payload"]["reason"] == "missing_required_input"


async def test_worker_confirmation_context_records_risk_without_secrets(
    tenant_a_headers: dict[str, str],
) -> None:
    clear_hook_events()
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, version = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        policy={"allowed_tools": ["shell_exec"], "risk": "low"},
        definition={"instructions": "Run shell when needed."},
    )

    async with _async_session_factory() as db:
        result = await execute_worker_run(
            db,
            gateway=DestructiveToolGateway(),
            sandbox_manager=object(),
            provider="default",
            worker=await db.get(Worker, worker.id),
            version=await db.get(WorkerVersion, version.id),
            messages=[{"role": "user", "content": "run shell"}],
            input_payload={"request": "run shell"},
            matched_request="run shell",
            match_score=0.9,
            tools=[
                {
                    "type": "function",
                    "function": {"name": "shell_exec", "parameters": {"type": "object"}},
                }
            ],
        )
        run = await db.get(WorkerRun, uuid.UUID(result["worker_run_id"]))

    assert result["status"] == "needs_user_confirmation"
    metadata_text = str(run.confirmation_metadata)
    assert run.confirmation_metadata["allowed_tool_names"] == ["shell_exec"]
    assert run.confirmation_metadata["worker_context"]["worker_run_id"] == str(run.id)
    assert run.confirmation_metadata["worker_context"]["risk_decision"] == "low"
    assert run.confirmation_metadata["worker_context"]["confirmation_context"] == {
        "tool_name": "shell_exec",
        "risk": "destructive",
        "requires_confirmation": True,
    }
    assert "secret-value" not in metadata_text
    assert "api_key" not in metadata_text


async def test_empty_worker_allowed_tools_blocks_normal_and_confirmation_resume(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, version = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        policy={"allowed_tools": [], "risk": "low"},
        definition={"instructions": "No tools allowed."},
    )

    async with _async_session_factory() as db:
        result = await execute_worker_run(
            db,
            gateway=WebFetchGateway(),
            sandbox_manager=object(),
            provider="default",
            worker=await db.get(Worker, worker.id),
            version=await db.get(WorkerVersion, version.id),
            messages=[{"role": "user", "content": "fetch"}],
            input_payload={"request": "fetch"},
            matched_request="fetch",
            match_score=0.9,
            fallback_on_failure=False,
        )

    blocked_event = next(event for event in result["events"] if event.get("type") == "tool_error")
    assert blocked_event["code"] == "WORKER_TOOL_NOT_ALLOWED"
    assert blocked_event["rejection_reason"] == "worker_tool_not_allowed"
    worker_context = {
        "worker_id": str(worker.id),
        "worker_version_id": str(version.id),
        "worker_run_id": str(uuid.uuid4()),
        "allowed_tool_names": [],
    }

    with pytest.raises(WorkerPolicyError) as blocked_resume:
        await execute_confirmed_tool(
            "web_fetch",
            {"url": "https://example.com"},
            object(),
            gateway=TextGateway(),
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            worker_context=worker_context,
        )

    assert blocked_resume.value.reason == "worker_tool_not_allowed"


async def test_worker_confirmation_resume_requires_context_for_risky_tool(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, version = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        policy={"allowed_tools": ["shell_exec"], "risk": "low"},
        definition={"instructions": "Run shell only after confirmation."},
    )

    with pytest.raises(WorkerPolicyError) as missing_context:
        await execute_confirmed_tool(
            "shell_exec",
            {"cmd": "echo hi"},
            object(),
            gateway=TextGateway(),
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            worker_context={
                "worker_id": str(worker.id),
                "worker_version_id": str(version.id),
                "worker_run_id": str(uuid.uuid4()),
                "allowed_tool_names": ["shell_exec"],
            },
            risk="destructive",
        )
    assert missing_context.value.reason == "worker_confirmation_context_missing"


async def test_worker_failure_hook_records_event_and_improvement_candidate(
    tenant_a_headers: dict[str, str],
) -> None:
    clear_hook_events()
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, version = await _active_worker(tenant_id=tenant_id, user_id=user_id)

    async with _async_session_factory() as db:
        result = await execute_worker_run(
            db,
            gateway=FailingThenFallbackGateway(),
            sandbox_manager=object(),
            provider="default",
            worker=await db.get(Worker, worker.id),
            version=await db.get(WorkerVersion, version.id),
            messages=[{"role": "user", "content": "policy hook"}],
            input_payload={"request": "policy hook"},
            matched_request="policy hook",
            match_score=0.9,
            source_run_id="w6-hook-failure",
        )
        candidates = list(
            (
                await db.execute(
                    select(CapabilityCandidate).where(
                        CapabilityCandidate.worker_id == worker.id,
                        CapabilityCandidate.source_run_id == "w6-hook-failure",
                    )
                )
            ).scalars()
        )

    assert result["status"] == "failed_fallback_succeeded"
    assert result["events"][0]["type"] == "worker_notice"
    assert len(candidates) == 1
    failure_hook = next(event for event in get_hook_events() if event["name"] == "on_worker_failure")
    assert failure_hook["payload"]["worker_id"] == str(worker.id)
    assert failure_hook["payload"]["status"] == "failed_fallback_succeeded"
    created_hook = next(event for event in get_hook_events() if event["name"] == "on_capability_candidate_created")
    assert created_hook["payload"]["candidate_id"] == str(candidates[0].id)
    assert created_hook["payload"]["worker_id"] == str(worker.id)
