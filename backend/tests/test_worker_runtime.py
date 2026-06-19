"""Worker owner and activation-gate tests for the V2 capability layer."""

from __future__ import annotations

import uuid
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import _async_session_factory
from app.core.agent.engine import run_agent
from app.core.capabilities.policy import WorkerPolicyError
from app.core.workers.matcher import match_workers
from app.core.workers.runtime import execute_worker_run
from app.core.workers.service import create_worker
from app.models.capability import CapabilityCandidate
from app.models.worker import Worker, WorkerRun, WorkerVersion
from app.services.auth_service import decode_token
from app.services.conversation_stream_service import (
    WORKER_DELETE_TOOL_NAME,
    _maybe_queue_worker_delete_confirmation,
    execute_confirmed_tool,
)

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> dict[str, str]:
    return decode_token(headers["Authorization"].split(" ", 1)[1])


def _nested_json(depth: int) -> dict:
    value: dict = {}
    for _ in range(depth):
        value = {"child": value}
    return value


def _many_key_json() -> dict[str, str]:
    return {f"k{index:04d}": "v" for index in range(650)}


async def _register_same_tenant_user(
    client: AsyncClient,
    tenant_name: str,
) -> dict[str, str]:
    suffix = uuid.uuid4().hex
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": tenant_name,
            "username": f"user-{suffix}",
            "password": "secret123",
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_worker(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "Daily digest worker",
) -> dict:
    response = await client.post(
        "/api/v1/workers",
        headers=headers,
        json={
            "name": f"{name} {uuid.uuid4().hex}",
            "description": "Draft worker metadata only",
            "trigger": {"type": "manual"},
            "policy": {"requires_confirmation": True},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_version(
    client: AsyncClient,
    headers: dict[str, str],
    worker_id: str,
    *,
    version: int = 1,
) -> dict:
    response = await client.post(
        f"/api/v1/workers/{worker_id}/versions",
        headers=headers,
        json={
            "version": version,
            "definition": {"steps": [{"type": "noop"}]},
            "verification_plan": {"checks": ["contract-only"]},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _fake_embedding(text: str) -> list[float]:
    lowered = text.casefold()
    if "keyword-only" in lowered:
        return [0.0, 1.0, 0.0]
    if "medium-match" in lowered:
        return [0.65, 0.76, 0.0]
    if any(term in lowered for term in ("weather forecast", "rain outlook", "will it rain", "umbrella")):
        return [1.0, 0.0, 0.0]
    return [0.2, 0.8, 0.0]


async def _active_worker(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str = "Forecast worker",
    description: str = "weather forecast for city planning",
    trigger: dict | None = None,
    policy: dict | None = None,
    definition: dict | None = None,
    status: str = "active",
    version_status: str = "active",
) -> tuple[Worker, WorkerVersion]:
    async with _async_session_factory() as db:
        worker = Worker(
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"{name} {uuid.uuid4().hex}",
            description=description,
            status=status,
            enabled=status == "active",
            trigger=trigger or {"examples": ["weather forecast", "rain outlook"], "keywords": ["weather"]},
            policy=policy or {"allowed_tools": ["weather_get"], "risk": "low"},
            activation_evidence={"approved_by": "test"},
            activation_confirmed_at=datetime.now(timezone.utc) if status == "active" else None,
            activation_confirmed_by=user_id if status == "active" else None,
        )
        db.add(worker)
        await db.flush()
        version = WorkerVersion(
            tenant_id=tenant_id,
            user_id=user_id,
            worker_id=worker.id,
            version=1,
            status=version_status,
            definition=definition
            or {
                "instructions": "Answer weather planning requests.",
                "input_schema": {
                    "type": "object",
                    "required": ["city"],
                    "properties": {"city": {"type": "string"}},
                },
            },
            verification_evidence={"tests": "passed"} if version_status in {"verified", "active"} else {},
        )
        db.add(version)
        await db.flush()
        worker.active_version_id = version.id if version_status == "active" else None
        await db.commit()
        await db.refresh(worker)
        await db.refresh(version)
        return worker, version


class TextGateway:
    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        yield {"type": "text", "content": "worker completed"}


class FailingThenFallbackGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("worker boom")
        yield {"type": "text", "content": "fallback completed"}


async def test_worker_and_version_start_as_draft(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    worker = await _create_worker(client, tenant_a_headers)
    version = await _create_version(client, tenant_a_headers, worker["id"])

    assert worker["status"] == "draft"
    assert worker["enabled"] is False
    assert worker["soft_deleted_at"] is None
    assert worker["tenant_id"] == _identity(tenant_a_headers)["tenant_id"]
    assert worker["user_id"] == _identity(tenant_a_headers)["user_id"]
    assert version["status"] == "draft"
    assert version["verification_evidence"] == {}


async def test_worker_match_decisions_use_semantics_schema_risk_and_active_state(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    active, _ = await _active_worker(tenant_id=tenant_id, user_id=user_id)
    high_risk, _ = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        name="High risk forecast",
        policy={"allowed_tools": ["weather_get"], "risk": "high"},
    )
    external_delivery, _ = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        name="External delivery forecast",
        policy={"allowed_tools": ["weather_get"], "risk": "low"},
        definition={"instructions": "Deliver externally.", "external_delivery": True},
    )
    disabled, _ = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        name="Disabled forecast",
        status="disabled",
    )
    soft_deleted, _ = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        name="Soft deleted forecast",
        status="soft_deleted",
    )

    async with _async_session_factory() as db:
        missing_input = await match_workers(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            request="Will it rain in Suzhou tomorrow?",
            input_payload={},
            embedding_fn=_fake_embedding,
        )
        auto = await match_workers(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            request="I need an umbrella outlook for tomorrow.",
            input_payload={"city": "Suzhou"},
            embedding_fn=_fake_embedding,
        )
        medium = await match_workers(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            request="medium-match planning request",
            input_payload={"city": "Suzhou"},
            embedding_fn=_fake_embedding,
        )

    by_worker = {decision.worker_id: decision for decision in missing_input}
    assert by_worker[active.id].decision == "blocked_missing_input"
    assert all(decision.worker_id not in {disabled.id, soft_deleted.id} for decision in missing_input)
    assert next(decision for decision in auto if decision.worker_id == active.id).decision == "auto_notice"
    assert next(decision for decision in auto if decision.worker_id == high_risk.id).decision == "needs_confirmation"
    assert next(decision for decision in auto if decision.worker_id == external_delivery.id).decision == "needs_confirmation"
    assert next(decision for decision in medium if decision.worker_id == active.id).decision == "skip_and_suggest_after"


async def test_worker_semantic_match_works_without_keyword_overlap_and_keyword_only_is_insufficient(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    semantic_worker, _ = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        trigger={"examples": ["weather forecast"], "keywords": []},
    )
    keyword_worker, _ = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        name="keyword-only worker",
        description="keyword-only",
        trigger={"examples": ["keyword-only"], "keywords": ["umbrella"]},
    )

    async with _async_session_factory() as db:
        decisions = await match_workers(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            request="umbrella rain outlook",
            input_payload={"city": "Wuxi"},
            embedding_fn=_fake_embedding,
        )

    semantic = next(decision for decision in decisions if decision.worker_id == semantic_worker.id)
    keyword_only = next(decision for decision in decisions if decision.worker_id == keyword_worker.id)
    assert semantic.semantic_score >= 0.8
    assert semantic.decision == "auto_notice"
    assert keyword_only.keyword_score > 0
    assert keyword_only.semantic_score < 0.5
    assert keyword_only.decision == "no_match"


async def test_draft_or_unverified_worker_version_cannot_run(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, version = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        status="draft",
        version_status="draft",
    )

    async with _async_session_factory() as db:
        db_worker = await db.get(Worker, worker.id)
        db_version = await db.get(WorkerVersion, version.id)
        result = await execute_worker_run(
            db,
            gateway=TextGateway(),
            sandbox_manager=object(),
            provider="default",
            worker=db_worker,
            version=db_version,
            messages=[{"role": "user", "content": "rain outlook"}],
            input_payload={"city": "Suzhou"},
            matched_request="rain outlook",
            match_score=0.95,
        )

    assert result["status"] == "blocked_by_policy"
    assert result["reason"] == "worker_not_active"


async def test_worker_recursion_and_max_depth_are_blocked_with_traceable_reasons(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, version = await _active_worker(tenant_id=tenant_id, user_id=user_id)

    async with _async_session_factory() as db:
        db_worker = await db.get(Worker, worker.id)
        db_version = await db.get(WorkerVersion, version.id)
        same_worker = await execute_worker_run(
            db,
            gateway=TextGateway(),
            sandbox_manager=object(),
            provider="default",
            worker=db_worker,
            version=db_version,
            messages=[{"role": "user", "content": "rain outlook"}],
            input_payload={"city": "Suzhou"},
            matched_request="rain outlook",
            match_score=0.95,
            worker_context={"worker_stack": [str(worker.id)], "depth": 1, "max_depth": 3},
        )
        too_deep = await execute_worker_run(
            db,
            gateway=TextGateway(),
            sandbox_manager=object(),
            provider="default",
            worker=db_worker,
            version=db_version,
            messages=[{"role": "user", "content": "rain outlook"}],
            input_payload={"city": "Suzhou"},
            matched_request="rain outlook",
            match_score=0.95,
            worker_context={"worker_stack": [], "depth": 2, "max_depth": 2},
        )

    assert same_worker["status"] == "blocked_by_policy"
    assert same_worker["reason"] == "worker_recursion_blocked"
    assert too_deep["status"] == "blocked_by_policy"
    assert too_deep["reason"] == "worker_max_depth_exceeded"


async def test_natural_language_worker_delete_uses_confirmation_before_soft_delete(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, _ = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        name="Deletable browser worker",
        description="Worker that must not auto-run for delete requests.",
    )
    queue: asyncio.Queue = asyncio.Queue()

    async with _async_session_factory() as db:
        result = await _maybe_queue_worker_delete_confirmation(
            db,
            queue=queue,
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            request=f"delete {worker.name} Worker",
        )

    assert result == "queued"
    event_name, confirmation = await queue.get()
    assert event_name == "confirmation_required"
    assert confirmation["tool_name"] == WORKER_DELETE_TOOL_NAME
    assert confirmation["args"]["worker_id"] == str(worker.id)
    assert confirmation["risk"] == "destructive"
    assert await queue.get() == ("done", {"tokens_used": 0})

    async with _async_session_factory() as db:
        still_active = await db.get(Worker, worker.id)
        worker_runs = list(
            (
                await db.execute(
                    select(WorkerRun).where(WorkerRun.worker_id == worker.id)
                )
            ).scalars()
        )
    assert still_active.status == "active"
    assert still_active.soft_deleted_at is None
    assert worker_runs == []

    confirmed = await execute_confirmed_tool(
        WORKER_DELETE_TOOL_NAME,
        {"worker_id": str(worker.id)},
        object(),
        gateway=TextGateway(),
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        conversation_id=str(uuid.uuid4()),
        tool_call_id=confirmation["tool_call_id"],
        risk="destructive",
    )

    assert "soft deleted" in confirmed
    async with _async_session_factory() as db:
        deleted = await db.get(Worker, worker.id)
    assert deleted.status == "soft_deleted"
    assert deleted.soft_deleted_at is not None


async def test_worker_delete_guard_bypasses_reference_edit_requests_without_confirmation(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, _ = await _active_worker(
        tenant_id=tenant_id,
        user_id=user_id,
        name="Docs cleanup worker",
        description="Worker name may appear in ordinary editing tasks.",
    )
    queue: asyncio.Queue = asyncio.Queue()

    async with _async_session_factory() as db:
        result = await _maybe_queue_worker_delete_confirmation(
            db,
            queue=queue,
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            request=f"delete references to {worker.name} Worker from docs/code",
        )

    assert result == "bypass_worker"
    assert queue.empty()
    async with _async_session_factory() as db:
        still_active = await db.get(Worker, worker.id)
        worker_runs = list(
            (
                await db.execute(
                    select(WorkerRun).where(WorkerRun.worker_id == worker.id)
                )
            ).scalars()
        )
    assert still_active.status == "active"
    assert still_active.soft_deleted_at is None
    assert worker_runs == []


async def test_worker_policy_blocks_disallowed_tool_in_normal_and_confirmation_resume(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, version = await _active_worker(tenant_id=tenant_id, user_id=user_id)

    class WebGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {
                "type": "tool_call",
                "index": 0,
                "id": "call-web",
                "name": "web_fetch",
                "arguments": '{"url":"https://example.com"}',
            }

    events = [
        event
        async for event in run_agent(
            WebGateway(),
            object(),
            "default",
            [{"role": "user", "content": "fetch"}],
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            worker_context={
                "worker_id": str(worker.id),
                "worker_version_id": str(version.id),
                "worker_run_id": str(uuid.uuid4()),
                "allowed_tool_names": ["weather_get"],
            },
            max_consecutive_errors=1,
        )
    ]

    blocked = next(event for event in events if event["type"] == "tool_error")
    assert blocked["code"] == "WORKER_TOOL_NOT_ALLOWED"
    assert blocked["blocked"] is True

    with pytest.raises(WorkerPolicyError) as blocked_resume:
        await execute_confirmed_tool(
            "web_fetch",
            {"url": "https://example.com"},
            object(),
            gateway=TextGateway(),
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            worker_context={
                "worker_id": str(worker.id),
                "worker_version_id": str(version.id),
                "worker_run_id": str(uuid.uuid4()),
                "allowed_tool_names": ["weather_get"],
            },
        )
    assert blocked_resume.value.reason == "worker_tool_not_allowed"


async def test_worker_run_records_trace_fallback_fields_and_timestamps(
    tenant_a_headers: dict[str, str],
) -> None:
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
            messages=[{"role": "user", "content": "rain outlook"}],
            input_payload={"city": "Suzhou"},
            matched_request="rain outlook",
            match_score=0.91,
            source_run_id="source-1",
        )
        run = await db.get(WorkerRun, uuid.UUID(result["worker_run_id"]))

    assert run is not None
    assert run.status == "succeeded"
    assert run.created_at is not None
    assert run.updated_at is not None
    assert run.input_payload["matched_request"] == "rain outlook"
    assert run.input_payload["match_score"] == 0.91
    assert run.output_payload["events"][-1]["type"] == "done"
    assert run.output_payload["tool_trace"] == []
    assert run.output_payload["fallback"]["attempted"] is False
    assert run.confirmation_metadata["allowed_tool_names"] == ["weather_get"]


async def test_worker_failure_fallback_and_feedback_candidate_lifecycle(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    worker, version = await _active_worker(tenant_id=tenant_id, user_id=user_id)

    async with _async_session_factory() as db:
        fallback = await execute_worker_run(
            db,
            gateway=FailingThenFallbackGateway(),
            sandbox_manager=object(),
            provider="default",
            worker=await db.get(Worker, worker.id),
            version=await db.get(WorkerVersion, version.id),
            messages=[{"role": "user", "content": "rain outlook"}],
            input_payload={"city": "Suzhou"},
            matched_request="rain outlook",
            match_score=0.91,
            source_run_id="fallback-source",
        )
        failed_worker = await db.get(Worker, worker.id)
        candidates = list(
            (
                await db.execute(
                    select(CapabilityCandidate).where(
                        CapabilityCandidate.worker_id == worker.id,
                        CapabilityCandidate.source_run_id == "fallback-source",
                    )
                )
            ).scalars()
        )

    assert fallback["status"] == "failed_fallback_succeeded"
    assert fallback["events"][0]["type"] == "worker_notice"
    assert fallback["events"][0]["status"] == "fallback_started"
    assert fallback["events"][0]["worker_name"] == worker.name
    assert "failed" in fallback["events"][0]["message"]
    assert "fallback" in fallback["events"][0]["message"]
    assert fallback["events"][-1]["type"] == "done"
    assert failed_worker.metadata_["runtime_feedback"]["confidence"] < 0.5
    assert len(candidates) == 1
    assert candidates[0].candidate_type == "worker"

    success_worker, success_version = await _active_worker(tenant_id=tenant_id, user_id=user_id)
    async with _async_session_factory() as db:
        success = await execute_worker_run(
            db,
            gateway=TextGateway(),
            sandbox_manager=object(),
            provider="default",
            worker=await db.get(Worker, success_worker.id),
            version=await db.get(WorkerVersion, success_version.id),
            messages=[{"role": "user", "content": "rain outlook"}],
            input_payload={"city": "Suzhou"},
            matched_request="rain outlook",
            match_score=0.91,
            source_run_id="success-source",
        )
        raised_worker = await db.get(Worker, success_worker.id)
        success_candidates = list(
            (
                await db.execute(
                    select(CapabilityCandidate).where(
                        CapabilityCandidate.worker_id == success_worker.id,
                        CapabilityCandidate.source_run_id == "success-source",
                    )
                )
            ).scalars()
        )

    assert success["status"] == "succeeded"
    assert raised_worker.metadata_["runtime_feedback"]["confidence"] > 0.5
    assert success_candidates == []


async def test_draft_worker_cannot_be_activated_without_verified_version_and_confirmation(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    worker = await _create_worker(client, tenant_a_headers)
    version = await _create_version(client, tenant_a_headers, worker["id"])

    direct_activation = await client.post(
        f"/api/v1/workers/{worker['id']}/activate",
        headers=tenant_a_headers,
        json={
            "version_id": version["id"],
            "activation_token": "not-issued",
            "confirmation_evidence": {"approved_by": "test"},
        },
    )
    requested = await client.post(
        f"/api/v1/workers/{worker['id']}/request-activation",
        headers=tenant_a_headers,
        json={"version_id": version["id"]},
    )

    assert direct_activation.status_code == 409
    assert direct_activation.json()["error"]["code"] == "WORKER_VERSION_NOT_VERIFIED"
    assert requested.status_code == 409
    assert requested.json()["error"]["code"] == "WORKER_VERSION_NOT_VERIFIED"


async def test_verified_version_requires_confirmation_before_activation_and_records_audit_evidence(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    worker = await _create_worker(client, tenant_a_headers)
    version = await _create_version(client, tenant_a_headers, worker["id"])

    verified = await client.post(
        f"/api/v1/workers/{worker['id']}/versions/{version['id']}/verify",
        headers=tenant_a_headers,
        json={"verification_evidence": {"tests": "passed", "review": "manual"}},
    )
    requested = await client.post(
        f"/api/v1/workers/{worker['id']}/request-activation",
        headers=tenant_a_headers,
        json={"version_id": version["id"]},
    )
    no_confirmation = await client.post(
        f"/api/v1/workers/{worker['id']}/activate",
        headers=tenant_a_headers,
        json={
            "version_id": version["id"],
            "activation_token": requested.json()["activation_token"],
        },
    )
    activated = await client.post(
        f"/api/v1/workers/{worker['id']}/activate",
        headers=tenant_a_headers,
        json={
            "version_id": version["id"],
            "activation_token": requested.json()["activation_token"],
            "confirmation_evidence": {"approved_by": "user", "ticket": "W1"},
        },
    )

    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"
    assert requested.status_code == 200, requested.text
    assert requested.json()["requires_confirmation"] is True
    assert no_confirmation.status_code == 422
    assert no_confirmation.json()["error"]["code"] == "VALIDATION_ERROR"
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"
    assert activated.json()["enabled"] is True
    assert activated.json()["active_version_id"] == version["id"]
    assert activated.json()["activation_confirmed_by"] == _identity(tenant_a_headers)["user_id"]
    assert activated.json()["activation_evidence"] == {"approved_by": "user", "ticket": "W1"}


async def test_activation_token_is_bound_to_requested_version(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    worker = await _create_worker(client, tenant_a_headers)
    v1 = await _create_version(client, tenant_a_headers, worker["id"], version=1)
    v2 = await _create_version(client, tenant_a_headers, worker["id"], version=2)
    for version in (v1, v2):
        verified = await client.post(
            f"/api/v1/workers/{worker['id']}/versions/{version['id']}/verify",
            headers=tenant_a_headers,
            json={"verification_evidence": {"version": version["version"]}},
        )
        assert verified.status_code == 200, verified.text

    requested_v1 = await client.post(
        f"/api/v1/workers/{worker['id']}/request-activation",
        headers=tenant_a_headers,
        json={"version_id": v1["id"]},
    )
    cross_version_activate = await client.post(
        f"/api/v1/workers/{worker['id']}/activate",
        headers=tenant_a_headers,
        json={
            "version_id": v2["id"],
            "activation_token": requested_v1.json()["activation_token"],
            "confirmation_evidence": {"approved_by": "user"},
        },
    )
    activated_v1 = await client.post(
        f"/api/v1/workers/{worker['id']}/activate",
        headers=tenant_a_headers,
        json={
            "version_id": v1["id"],
            "activation_token": requested_v1.json()["activation_token"],
            "confirmation_evidence": {"approved_by": "user"},
        },
    )

    assert requested_v1.status_code == 200, requested_v1.text
    assert cross_version_activate.status_code == 409
    assert cross_version_activate.json()["error"]["code"] == "WORKER_ACTIVATION_NOT_REQUESTED"
    assert activated_v1.status_code == 200, activated_v1.text
    assert activated_v1.json()["active_version_id"] == v1["id"]


async def test_rollback_token_is_bound_to_requested_version(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    worker = await _create_worker(client, tenant_a_headers)
    v1 = await _create_version(client, tenant_a_headers, worker["id"], version=1)
    v2 = await _create_version(client, tenant_a_headers, worker["id"], version=2)
    for version in (v1, v2):
        verified = await client.post(
            f"/api/v1/workers/{worker['id']}/versions/{version['id']}/verify",
            headers=tenant_a_headers,
            json={"verification_evidence": {"version": version["version"]}},
        )
        assert verified.status_code == 200, verified.text

    requested_v1 = await client.post(
        f"/api/v1/workers/{worker['id']}/request-activation",
        headers=tenant_a_headers,
        json={"version_id": v1["id"]},
    )
    cross_version_rollback = await client.post(
        f"/api/v1/workers/{worker['id']}/rollback",
        headers=tenant_a_headers,
        json={
            "version_id": v2["id"],
            "activation_token": requested_v1.json()["activation_token"],
            "confirmation_evidence": {"approved_by": "user"},
        },
    )

    assert requested_v1.status_code == 200, requested_v1.text
    assert cross_version_rollback.status_code == 409
    assert cross_version_rollback.json()["error"]["code"] == "WORKER_ACTIVATION_NOT_REQUESTED"


async def test_worker_disable_enable_soft_delete_and_rollback(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    worker = await _create_worker(client, tenant_a_headers)
    v1 = await _create_version(client, tenant_a_headers, worker["id"], version=1)
    v2 = await _create_version(client, tenant_a_headers, worker["id"], version=2)
    for version in (v1, v2):
        verified = await client.post(
            f"/api/v1/workers/{worker['id']}/versions/{version['id']}/verify",
            headers=tenant_a_headers,
            json={"verification_evidence": {"version": version["version"]}},
        )
        assert verified.status_code == 200, verified.text
        requested = await client.post(
            f"/api/v1/workers/{worker['id']}/request-activation",
            headers=tenant_a_headers,
            json={"version_id": version["id"]},
        )
        activated = await client.post(
            f"/api/v1/workers/{worker['id']}/activate",
            headers=tenant_a_headers,
            json={
                "version_id": version["id"],
                "activation_token": requested.json()["activation_token"],
                "confirmation_evidence": {"version": version["version"]},
            },
        )
        assert activated.status_code == 200, activated.text

    disabled = await client.post(f"/api/v1/workers/{worker['id']}/disable", headers=tenant_a_headers)
    enabled = await client.post(f"/api/v1/workers/{worker['id']}/enable", headers=tenant_a_headers)
    rollback_without_evidence = await client.post(
        f"/api/v1/workers/{worker['id']}/rollback",
        headers=tenant_a_headers,
        json={"version_id": v1["id"], "reason": "rollback test"},
    )
    rollback_without_request_token = await client.post(
        f"/api/v1/workers/{worker['id']}/rollback",
        headers=tenant_a_headers,
        json={
            "version_id": v1["id"],
            "reason": "rollback test",
            "confirmation_evidence": {"approved_by": "user", "reason": "rollback"},
        },
    )
    rollback_request = await client.post(
        f"/api/v1/workers/{worker['id']}/request-activation",
        headers=tenant_a_headers,
        json={"version_id": v1["id"]},
    )
    rollback_wrong_token = await client.post(
        f"/api/v1/workers/{worker['id']}/rollback",
        headers=tenant_a_headers,
        json={
            "version_id": v1["id"],
            "activation_token": "wrong-token",
            "reason": "rollback test",
            "confirmation_evidence": {"approved_by": "user", "reason": "rollback"},
        },
    )
    rolled_back = await client.post(
        f"/api/v1/workers/{worker['id']}/rollback",
        headers=tenant_a_headers,
        json={
            "version_id": v1["id"],
            "activation_token": rollback_request.json()["activation_token"],
            "reason": "rollback test",
            "confirmation_evidence": {"approved_by": "user", "reason": "rollback"},
        },
    )
    soft_deleted = await client.delete(f"/api/v1/workers/{worker['id']}", headers=tenant_a_headers)
    listed = await client.get("/api/v1/workers", headers=tenant_a_headers)

    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["enabled"] is False
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "active"
    assert rollback_without_evidence.status_code == 422
    assert rollback_without_evidence.json()["error"]["code"] == "VALIDATION_ERROR"
    assert rollback_without_request_token.status_code == 409
    assert rollback_without_request_token.json()["error"]["code"] == "WORKER_ACTIVATION_NOT_REQUESTED"
    assert rollback_request.status_code == 200
    assert rollback_wrong_token.status_code == 409
    assert rollback_wrong_token.json()["error"]["code"] == "WORKER_ACTIVATION_NOT_REQUESTED"
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["active_version_id"] == v1["id"]
    assert rolled_back.json()["activation_confirmed_by"] == _identity(tenant_a_headers)["user_id"]
    assert rolled_back.json()["activation_evidence"] == {"approved_by": "user", "reason": "rollback"}
    assert soft_deleted.status_code == 200
    assert soft_deleted.json()["status"] == "soft_deleted"
    assert soft_deleted.json()["soft_deleted_at"] is not None
    assert all(item["id"] != worker["id"] for item in listed.json()["items"])


async def test_worker_user_and_tenant_isolation(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    tenant_name = f"worker-tenant-{uuid.uuid4().hex}"
    first_user = await _register_same_tenant_user(client, tenant_name)
    second_user = await _register_same_tenant_user(client, tenant_name)
    worker = await _create_worker(client, first_user, name="private worker")
    tenant_b_worker = await _create_worker(client, tenant_b_headers, name="tenant b worker")

    same_tenant_other_user = await client.get(f"/api/v1/workers/{worker['id']}", headers=second_user)
    other_tenant = await client.get(f"/api/v1/workers/{worker['id']}", headers=tenant_b_headers)
    first_user_list = await client.get("/api/v1/workers", headers=first_user)
    tenant_a_list = await client.get("/api/v1/workers", headers=tenant_a_headers)

    assert same_tenant_other_user.status_code == 404
    assert other_tenant.status_code == 404
    assert first_user_list.status_code == 200
    assert first_user_list.json()["items"][0]["id"] == worker["id"]
    assert all(item["id"] != tenant_b_worker["id"] for item in tenant_a_list.json()["items"])


async def test_worker_json_bounds_are_enforced(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as too_deep_worker:
            await create_worker(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                name=f"oversized worker {uuid.uuid4().hex}",
                description="bounded JSON test",
                trigger=_nested_json(12),
                policy={},
            )

    assert too_deep_worker.value.status_code == 422


async def test_worker_public_json_bounds_reject_before_db_constraint(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/workers",
        headers=tenant_a_headers,
        json={
            "name": f"many key worker {uuid.uuid4().hex}",
            "description": "representation-boundary test",
            "trigger": _many_key_json(),
            "policy": {},
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_invalid_worker_durable_states_are_rejected(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])

    async with _async_session_factory() as db:
        worker = Worker(
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"invalid status worker {uuid.uuid4().hex}",
            status="not-a-worker-status",
        )
        db.add(worker)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

        valid_worker = Worker(
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"valid worker {uuid.uuid4().hex}",
            status="draft",
        )
        db.add(valid_worker)
        await db.commit()
        await db.refresh(valid_worker)
        valid_worker_id = valid_worker.id

        db.add(
            WorkerVersion(
                tenant_id=tenant_id,
                user_id=user_id,
                worker_id=valid_worker_id,
                version=1,
                status="not-a-version-status",
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

        db.add(
            WorkerRun(
                tenant_id=tenant_id,
                user_id=user_id,
                worker_id=valid_worker_id,
                status="not-a-run-status",
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()

async def test_skill_migration_downgrade_preflights_scoped_duplicates() -> None:
    migration = Path("alembic/versions/0008_add_capability_layer.py").read_text()

    assert "duplicate Skill names" in migration
    assert "RuntimeError" in migration
    assert "uq_skills_tenant_name" in migration
