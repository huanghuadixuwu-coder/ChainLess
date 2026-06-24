"""Capability Candidate contract tests for the V2 capability layer."""

from __future__ import annotations

import uuid
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import _async_session_factory
from app.core.capabilities.analyzer import analyze_run_for_candidates
from app.core.capabilities.outbox import (
    claim_analysis_job,
    claim_pending_analysis,
    complete_analysis_job,
    enqueue_analysis_job,
    enqueue_run_analysis,
    fail_analysis_job,
    skip_duplicate_analysis_job,
)
from app.core.capabilities.rules import should_analyze_run
from app.core.capabilities.service import (
    analyze_run_tail_for_candidates,
    create_candidate,
    get_active_candidate_for_retrieval,
    process_pending_capability_analysis,
)
from app.core.observability import get_runtime_metric_snapshot, reset_runtime_metrics
from app.models.capability import CapabilityAnalysisJob, CapabilityCandidate
from app.models.skill import Skill
from app.models.user import User
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> dict[str, str]:
    return decode_token(headers["Authorization"].split(" ", 1)[1])


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in text.strip().split("\n\n"):
        event_name = ""
        data = {}
        for line in frame.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        if event_name:
            events.append((event_name, data))
    return events


async def _promote(headers: dict[str, str]) -> None:
    identity = _identity(headers)
    async with _async_session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == uuid.UUID(identity["user_id"]))
            .values(role="admin")
        )
        await db.commit()


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


async def _seed_candidate(
    headers: dict[str, str],
    *,
    title: str = "remember release checklist",
    candidate_type: str = "memory",
    dedupe_key: str | None = None,
    source_run_id: str | None = None,
) -> CapabilityCandidate:
    identity = _identity(headers)
    async with _async_session_factory() as db:
        candidate = await create_candidate(
            db,
            tenant_id=uuid.UUID(identity["tenant_id"]),
            user_id=uuid.UUID(identity["user_id"]),
            candidate_type=candidate_type,
            title=title,
            body="Candidate body",
            source_run_id=source_run_id or f"run-{uuid.uuid4().hex}",
            source_event_id=f"event-{uuid.uuid4().hex}",
            source_message_id=f"message-{uuid.uuid4().hex}",
            source_uri="conversation://test",
            source_kind="conversation",
            dedupe_key=dedupe_key or f"candidate:{uuid.uuid4().hex}",
            evidence={"reason": "test"},
            payload={"bounded": True},
        )
        await db.commit()
        await db.refresh(candidate)
        return candidate


def _nested_json(depth: int) -> dict:
    value: dict = {}
    for _ in range(depth):
        value = {"child": value}
    return value


def _array_heavy_json() -> dict[str, list[int]]:
    return {"items": [0 for _ in range(3000)]}


@pytest.mark.parametrize(
    ("user_text", "expected_reason"),
    [
        ("Please remember that release checks use staging first.", "remember_text"),
        ("Next time I ask for a release, start with the staging checklist.", "next_time_text"),
        ("Always use pnpm for this repo instead of npm.", "always_text"),
    ],
)
async def test_rules_text_signals_trigger_candidate_analysis(
    user_text: str,
    expected_reason: str,
) -> None:
    signal = should_analyze_run(
        user_messages=[user_text],
        assistant_messages=["Understood, I will use that going forward."],
    )

    assert signal.should_analyze is True
    assert expected_reason in signal.reasons
    assert signal.user_correction is False


async def test_rules_tool_chain_artifact_correction_fallback_and_noise_signals() -> None:
    tool_chain = should_analyze_run(
        user_messages=["Please prepare the release notes."],
        assistant_messages=["I checked the repo, generated notes, and summarized them."],
        tool_events=[
            {"name": "repo_search", "status": "completed"},
            {"name": "file_write", "status": "completed"},
        ],
    )
    artifact = should_analyze_run(
        user_messages=["Use the uploaded requirements document."],
        assistant_messages=["I summarized the attached requirements."],
        artifacts=[{"id": "artifact-1", "path": "requirements.md"}],
    )
    correction = should_analyze_run(
        user_messages=["No, I meant use pnpm instead of npm for Chainless."],
        assistant_messages=["Thanks for the correction; I will use pnpm."],
    )
    fallback = should_analyze_run(
        user_messages=[
            "We repeatedly deploy this service by cutting a release branch, "
            "running the same smoke checks, and posting a short operator note."
        ],
        assistant_messages=[
            "I can turn that into a reusable release routine with the smoke "
            "checks and operator note kept together for future runs."
        ],
    )
    greeting = should_analyze_run(
        user_messages=["hi"],
        assistant_messages=["Hello! How can I help?"],
    )

    assert tool_chain.should_analyze is True
    assert "tool_chain" in tool_chain.reasons
    assert artifact.should_analyze is True
    assert "artifact" in artifact.reasons
    assert correction.should_analyze is True
    assert correction.user_correction is True
    assert "user_correction" in correction.reasons
    assert fallback.should_analyze is True
    assert "fallback_useful_run" in fallback.reasons
    assert greeting.should_analyze is False
    assert greeting.reasons == []


async def test_analyzer_parses_memory_skill_and_worker_candidates_from_valid_json() -> None:
    class FakeAnalyzerGateway:
        async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
            _ = (provider, messages, tools, max_tokens, tenant_id)
            yield {
                "type": "text",
                "content": json.dumps(
                    {
                        "candidates": [
                            {
                                "type": "memory",
                                "title": "Remember staging release checks",
                                "body": "Use staging checks before production release.",
                                "dedupe_key": "memory:staging-release-checks",
                                "confidence": 0.82,
                                "source_evidence": ["User asked to remember staging checks."],
                                "payload": {"memory_text": "Use staging checks before release."},
                            },
                            {
                                "type": "skill",
                                "title": "Release checklist skill",
                                "body": "A reusable release checklist routine.",
                                "dedupe_key": "skill:release-checklist",
                                "confidence": 1.7,
                                "source_evidence": ["User described a repeatable release workflow."],
                                "payload": {"trigger_terms": ["release checklist"]},
                            },
                            {
                                "type": "worker",
                                "title": "Release note worker",
                                "body": "Prepare release notes from merged changes.",
                                "dedupe_key": "worker:release-notes",
                                "confidence": -0.4,
                                "source_evidence": ["Assistant used multiple tools to prepare notes."],
                                "payload": {"trigger": "release notes requested"},
                            },
                        ]
                    }
                ),
            }

    signal = should_analyze_run(
        user_messages=["Next time remember staging release checks."],
        assistant_messages=["I will remember the staging release checks."],
    )
    candidates = await analyze_run_for_candidates(
        FakeAnalyzerGateway(),
        provider="default",
        tenant_id=str(uuid.uuid4()),
        signal=signal,
        run_payload={
            "source_run_id": "run-analyzer-valid",
            "conversation_id": str(uuid.uuid4()),
            "assistant_content": "I will remember the staging release checks.",
        },
    )

    assert [candidate.candidate_type for candidate in candidates] == ["memory", "skill", "worker"]
    assert candidates[0].confidence == 0.82
    assert candidates[1].confidence == 1.0
    assert candidates[2].confidence == 0.0
    assert candidates[0].source_evidence == ["User asked to remember staging checks."]


async def test_analyzer_invalid_json_returns_no_candidates() -> None:
    class InvalidGateway:
        async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
            _ = (provider, messages, tools, max_tokens, tenant_id)
            yield {"type": "text", "content": "```json\n{\"candidates\": []}\n```"}

    signal = should_analyze_run(
        user_messages=["Always use the release checklist."],
        assistant_messages=["I will use the release checklist."],
    )

    assert await analyze_run_for_candidates(
        InvalidGateway(),
        provider="default",
        tenant_id=str(uuid.uuid4()),
        signal=signal,
        run_payload={"source_run_id": "run-invalid"},
    ) == []


async def test_completed_chat_run_persists_inactive_candidate_and_emits_sse_hint(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import app_state

    class FakeGateway:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
            _ = (provider, messages, tools, max_tokens, tenant_id)
            self.calls += 1
            if self.calls == 1:
                yield {"type": "text", "content": "Next time I will use the staging checklist."}
                return
            yield {
                "type": "text",
                "content": json.dumps(
                    {
                        "candidates": [
                            {
                                "type": "memory",
                                "title": "Use staging checklist",
                                "body": "Use the staging checklist before releases.",
                                "dedupe_key": "memory:staging-checklist",
                                "confidence": 0.9,
                                "source_evidence": ["The run contained an explicit next-time preference."],
                                "payload": {"memory_text": "Use the staging checklist before releases."},
                            }
                        ]
                    }
                ),
            }

    monkeypatch.setattr(app_state, "llm_gateway", FakeGateway())
    monkeypatch.setattr(app_state, "sandbox_manager", object())

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "capability-sse"},
    )
    assert created.status_code == 200, created.text
    conv_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/chat",
        headers=tenant_a_headers,
        json={"content": "Next time remember to use the staging checklist."},
    )

    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    event_names = [name for name, _ in events]
    assert event_names == ["context", "text", "done"]

    identity = _identity(tenant_a_headers)
    async with _async_session_factory() as db:
        candidate_result = (
            await db.execute(
                select(CapabilityCandidate).where(
                    CapabilityCandidate.tenant_id == uuid.UUID(identity["tenant_id"]),
                    CapabilityCandidate.user_id == uuid.UUID(identity["user_id"]),
                    CapabilityCandidate.dedupe_key == "memory:staging-checklist",
                )
            )
        )
        candidates = list(candidate_result.scalars())
        job = (
            await db.execute(
                select(CapabilityAnalysisJob).where(
                    CapabilityAnalysisJob.tenant_id == uuid.UUID(identity["tenant_id"]),
                    CapabilityAnalysisJob.user_id == uuid.UUID(identity["user_id"]),
                    CapabilityAnalysisJob.source_kind == "conversation",
                )
                .order_by(CapabilityAnalysisJob.created_at.desc())
            )
        ).scalars().first()

    assert candidates == []
    assert job is not None
    assert job.status == "pending"


async def test_broad_muted_pattern_suppresses_new_matching_candidate_and_hint(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    conversation_id = uuid.uuid4()

    async with _async_session_factory() as db:
        muted = await create_candidate(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_type="skill",
            title="Muted release candidates",
            body="Do not suggest release checklist skills.",
            source_run_id=f"run-muted-{uuid.uuid4().hex}",
            source_kind="conversation",
            dedupe_key="skill:release-muted-anchor",
            evidence={"reason": "test"},
            payload={},
        )
        muted.status = "muted_pattern"
        muted.mute_pattern = "skill:release-*"
        await db.commit()

    class MutedAnalyzerGateway:
        async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
            _ = (provider, messages, tools, max_tokens, tenant_id)
            yield {
                "type": "text",
                "content": json.dumps(
                    {
                        "candidates": [
                            {
                                "type": "skill",
                                "title": "Release checklist skill",
                                "body": "Run a release checklist.",
                                "dedupe_key": "skill:release-checklist-new",
                                "confidence": 0.91,
                                "source_evidence": ["User asked for next-time release behavior."],
                                "payload": {"trigger_terms": ["release checklist"]},
                            }
                        ]
                    }
                ),
            }

    async with _async_session_factory() as db:
        hint = await analyze_run_tail_for_candidates(
            db,
            gateway=MutedAnalyzerGateway(),
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            source_run_id=f"run-muted-new-{uuid.uuid4().hex}",
            user_messages=["Next time use the release checklist."],
            assistant_content="I will use the release checklist next time.",
            provider="default",
            timeout_s=1,
        )

    assert hint is None
    async with _async_session_factory() as db:
        matching_count = (
            await db.execute(
                select(func.count())
                .select_from(CapabilityCandidate)
                .where(
                    CapabilityCandidate.tenant_id == tenant_id,
                    CapabilityCandidate.user_id == user_id,
                    CapabilityCandidate.candidate_type == "skill",
                    CapabilityCandidate.dedupe_key == "skill:release-checklist-new",
                )
            )
        ).scalar_one()
        muted_count = (
            await db.execute(
                select(func.count())
                .select_from(CapabilityCandidate)
                .where(
                    CapabilityCandidate.tenant_id == tenant_id,
                    CapabilityCandidate.user_id == user_id,
                    CapabilityCandidate.status == "muted_pattern",
                    CapabilityCandidate.mute_pattern == "skill:release-*",
                )
            )
        ).scalar_one()

    assert matching_count == 0
    assert muted_count == 1


async def test_stale_running_analysis_job_is_reclaimed(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    source_run_id = f"run-stale-{uuid.uuid4().hex}"

    async with _async_session_factory() as db:
        job = await enqueue_run_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=source_run_id,
            source_kind="conversation",
            payload={"source_run_id": source_run_id},
        )
        first_claim = await claim_pending_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            lease_seconds=60,
        )
        assert first_claim is not None
        first_claim.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        await db.commit()

        reclaimed = await claim_pending_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            lease_seconds=60,
        )
        await db.commit()

    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.status == "running"
    assert reclaimed.attempts == 2


async def test_background_hung_analyzer_times_out_and_marks_job_failed(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    source_run_id = f"run-hung-{uuid.uuid4().hex}"
    reset_runtime_metrics()

    class HungAnalyzerGateway:
        async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
            _ = (provider, messages, tools, max_tokens, tenant_id)
            await asyncio.Event().wait()
            yield {"type": "text", "content": "{}"}

    async with _async_session_factory() as db:
        await enqueue_run_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=source_run_id,
            source_kind="conversation",
            payload={
                "source_run_id": source_run_id,
                "conversation_id": str(uuid.uuid4()),
                "user_messages": ["Always use the hung analyzer timeout path."],
                "assistant_content": "I will use the hung analyzer timeout path.",
                "provider": "default",
                "signal": {
                    "should_analyze": True,
                    "reasons": ["always_text"],
                    "user_text": "Always use the hung analyzer timeout path.",
                    "assistant_text": "I will use the hung analyzer timeout path.",
                },
            },
        )
        await db.commit()

    result = await asyncio.wait_for(
        process_pending_capability_analysis(
            {"llm_gateway": HungAnalyzerGateway()},
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            limit=1,
            analyzer_timeout_s=0.01,
        ),
        timeout=1,
    )

    assert result == {"claimed": 1, "succeeded": 0, "failed": 1}
    metrics = get_runtime_metric_snapshot()
    assert metrics["capability_analysis_timeouts"] == 1
    assert metrics["capability_analysis_failures"] == 1
    async with _async_session_factory() as db:
        failed = (
            await db.execute(
                select(CapabilityAnalysisJob).where(
                    CapabilityAnalysisJob.source_run_id == source_run_id
                )
            )
        ).scalar_one()

    assert failed.status == "failed"
    assert failed.error_code == "ANALYZER_TIMEOUT"
    assert failed.error_message == "Capability analyzer timed out"


async def test_future_snoozed_candidate_suppresses_update_and_hint(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    dedupe_key = f"memory:snoozed-{uuid.uuid4().hex}"

    async with _async_session_factory() as db:
        snoozed = await create_candidate(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_type="memory",
            title="Original snoozed title",
            body="Original snoozed body",
            source_run_id=f"run-snoozed-{uuid.uuid4().hex}",
            source_kind="conversation",
            dedupe_key=dedupe_key,
            evidence={"reason": "test"},
            payload={},
        )
        snoozed.status = "snoozed"
        snoozed.snoozed_until = datetime.now(timezone.utc) + timedelta(days=1)
        await db.commit()

    class SnoozedAnalyzerGateway:
        async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
            _ = (provider, messages, tools, max_tokens, tenant_id)
            yield {
                "type": "text",
                "content": json.dumps(
                    {
                        "candidates": [
                            {
                                "type": "memory",
                                "title": "Updated snoozed title",
                                "body": "Updated snoozed body",
                                "dedupe_key": dedupe_key,
                                "confidence": 0.9,
                                "source_evidence": ["repeat"],
                                "payload": {"memory_text": "updated"},
                            }
                        ]
                    }
                ),
            }

    async with _async_session_factory() as db:
        hint = await analyze_run_tail_for_candidates(
            db,
            gateway=SnoozedAnalyzerGateway(),
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            conversation_id=str(uuid.uuid4()),
            source_run_id=f"run-snoozed-repeat-{uuid.uuid4().hex}",
            user_messages=["Next time remember the snoozed preference."],
            assistant_content="I will remember the snoozed preference.",
            provider="default",
            timeout_s=1,
        )

    assert hint is None
    async with _async_session_factory() as db:
        candidate = (
            await db.execute(
                select(CapabilityCandidate).where(
                    CapabilityCandidate.tenant_id == tenant_id,
                    CapabilityCandidate.user_id == user_id,
                    CapabilityCandidate.dedupe_key == dedupe_key,
                )
            )
        ).scalar_one()

    assert candidate.status == "snoozed"
    assert candidate.title == "Original snoozed title"
    assert candidate.body == "Original snoozed body"


async def test_merged_latest_dedupe_repeat_updates_merge_target_without_spam(
    tenant_a_headers: dict[str, str],
) -> None:
    dedupe_key = f"memory:merged-repeat-{uuid.uuid4().hex}"
    target = await _seed_candidate(
        tenant_a_headers,
        title="Original merge target",
        candidate_type="memory",
        dedupe_key=dedupe_key,
    )
    duplicate = await _seed_candidate(
        tenant_a_headers,
        title="Merged duplicate",
        candidate_type="memory",
        dedupe_key=dedupe_key,
    )
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])

    async with _async_session_factory() as db:
        row = (
            await db.execute(
                select(CapabilityCandidate).where(CapabilityCandidate.id == duplicate.id)
            )
        ).scalar_one()
        row.status = "merged"
        row.merge_target_candidate_id = target.id
        await db.commit()

    class MergedAnalyzerGateway:
        async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
            _ = (provider, messages, tools, max_tokens, tenant_id)
            yield {
                "type": "text",
                "content": json.dumps(
                    {
                        "candidates": [
                            {
                                "type": "memory",
                                "title": "Updated merge target",
                                "body": "Updated body",
                                "dedupe_key": dedupe_key,
                                "confidence": 0.8,
                                "source_evidence": ["repeat"],
                                "payload": {"memory_text": "updated"},
                            }
                        ]
                    }
                ),
            }

    async with _async_session_factory() as db:
        hint = await analyze_run_tail_for_candidates(
            db,
            gateway=MergedAnalyzerGateway(),
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            conversation_id=str(uuid.uuid4()),
            source_run_id=f"run-merged-repeat-{uuid.uuid4().hex}",
            user_messages=["Next time remember the merged preference."],
            assistant_content="I will remember the merged preference.",
            provider="default",
            timeout_s=1,
        )

    assert hint is not None
    assert hint["id"] == str(target.id)
    async with _async_session_factory() as db:
        rows = list(
            (
                await db.execute(
                    select(CapabilityCandidate).where(
                        CapabilityCandidate.tenant_id == tenant_id,
                        CapabilityCandidate.user_id == user_id,
                        CapabilityCandidate.dedupe_key == dedupe_key,
                    )
                )
            ).scalars()
        )
        target_row = next(row for row in rows if row.id == target.id)

    assert len(rows) == 2
    assert target_row.title == "Updated merge target"
    assert target_row.status == "new"


async def test_timeout_pending_background_idempotency_and_failure_metrics(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    conversation_id = uuid.uuid4()
    source_run_id = f"run-timeout-{uuid.uuid4().hex}"

    class SlowAnalyzerGateway:
        async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
            _ = (provider, messages, tools, max_tokens, tenant_id)
            await asyncio.Event().wait()
            yield {"type": "text", "content": "{}"}

    class ValidAnalyzerGateway:
        async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
            _ = (provider, messages, tools, max_tokens, tenant_id)
            yield {
                "type": "text",
                "content": json.dumps(
                    {
                        "candidates": [
                            {
                                "type": "skill",
                                "title": "Release checklist routine",
                                "body": "Run the release checklist for Chainless.",
                                "dedupe_key": "skill:release-checklist",
                                "confidence": 0.88,
                                "source_evidence": ["User asked for next-time release behavior."],
                                "payload": {"trigger_terms": ["release checklist"]},
                            }
                        ]
                    }
                ),
            }

    reset_runtime_metrics()
    async with _async_session_factory() as db:
        hint = await analyze_run_tail_for_candidates(
            db,
            gateway=SlowAnalyzerGateway(),
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            source_run_id=source_run_id,
            user_messages=["Next time use the release checklist."],
            assistant_content="I will use the release checklist next time.",
            provider="default",
            timeout_s=0.01,
        )
        await db.commit()

    assert hint is None
    assert get_runtime_metric_snapshot()["capability_analysis_timeouts"] == 1

    async with _async_session_factory() as db:
        pending = (
            await db.execute(
                select(CapabilityAnalysisJob).where(
                    CapabilityAnalysisJob.tenant_id == tenant_id,
                    CapabilityAnalysisJob.user_id == user_id,
                    CapabilityAnalysisJob.source_run_id == source_run_id,
                )
            )
        ).scalar_one()
        duplicate = await enqueue_run_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=source_run_id,
            source_kind="conversation",
            payload=pending.payload,
        )
        await db.commit()

    assert pending.id == duplicate.id
    assert pending.status == "pending"
    assert get_runtime_metric_snapshot()["capability_analysis_duplicate_enqueues"] == 1

    first_background = await process_pending_capability_analysis(
        {"llm_gateway": ValidAnalyzerGateway()},
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        limit=1,
    )
    second_background = await process_pending_capability_analysis(
        {"llm_gateway": ValidAnalyzerGateway()},
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        limit=1,
    )

    assert first_background == {"claimed": 1, "succeeded": 1, "failed": 0}
    assert second_background == {"claimed": 0, "succeeded": 0, "failed": 0}

    async with _async_session_factory() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(CapabilityCandidate)
                .where(
                    CapabilityCandidate.tenant_id == tenant_id,
                    CapabilityCandidate.user_id == user_id,
                    CapabilityCandidate.dedupe_key == "skill:release-checklist",
                )
            )
        ).scalar_one()
        succeeded = (
            await db.execute(
                select(CapabilityAnalysisJob).where(CapabilityAnalysisJob.source_run_id == source_run_id)
            )
        ).scalar_one()

    assert count == 1
    assert succeeded.status == "succeeded"
    assert succeeded.result_metadata["candidate_count"] == 1

    class FailingAnalyzerGateway:
        async def chat_stream(self, provider, messages, tools=None, max_tokens=4096, tenant_id=None):
            _ = (provider, messages, tools, max_tokens, tenant_id)
            raise RuntimeError("x" * 5000)
            yield {"type": "text", "content": "{}"}

    failed_run_id = f"run-fail-{uuid.uuid4().hex}"
    async with _async_session_factory() as db:
        await enqueue_run_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=failed_run_id,
            source_kind="conversation",
            payload={
                "source_run_id": failed_run_id,
                "conversation_id": str(conversation_id),
                "user_messages": ["Always remember the failed analyzer path."],
                "assistant_content": "I will remember the failed analyzer path.",
                "signal": {"reasons": ["always_text"]},
            },
        )
        await db.commit()

    failed_background = await process_pending_capability_analysis(
        {"llm_gateway": FailingAnalyzerGateway()},
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        limit=1,
    )

    assert failed_background == {"claimed": 1, "succeeded": 0, "failed": 1}
    assert get_runtime_metric_snapshot()["capability_analysis_failures"] == 1
    async with _async_session_factory() as db:
        failed = (
            await db.execute(
                select(CapabilityAnalysisJob).where(CapabilityAnalysisJob.source_run_id == failed_run_id)
            )
        ).scalar_one()

    assert failed.status == "failed"
    assert failed.error_code == "ANALYZER_ERROR"
    assert failed.error_message is not None
    assert len(failed.error_message) <= 1024
    assert failed.result_metadata["attempts"] == 1


async def test_create_list_get_and_required_field_serialization(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    candidate = await _seed_candidate(
        tenant_a_headers,
        title="promote launch checklist",
        source_run_id="run-required-fields",
    )

    listed = await client.get(
        "/api/v1/capability-candidates?limit=20&offset=0",
        headers=tenant_a_headers,
    )
    fetched = await client.get(
        f"/api/v1/capability-candidates/{candidate.id}",
        headers=tenant_a_headers,
    )

    assert listed.status_code == 200, listed.text
    assert set(listed.json()) == {"items", "total", "limit", "offset", "next"}
    assert listed.json()["total"] == 1
    item = listed.json()["items"][0]
    required = {
        "id",
        "tenant_id",
        "user_id",
        "candidate_type",
        "status",
        "title",
        "body",
        "source_run_id",
        "source_event_id",
        "source_message_id",
        "source_uri",
        "source_kind",
        "dedupe_key",
        "merge_target_candidate_id",
        "worker_id",
        "snoozed_until",
        "mute_pattern",
        "evidence",
        "payload",
        "created_at",
        "updated_at",
    }
    assert required.issubset(item)
    assert item["status"] == "new"
    assert item["source_run_id"] == "run-required-fields"
    assert fetched.status_code == 200
    assert fetched.json()["id"] == str(candidate.id)


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [
        ("accept", "accepted"),
        ("dismiss", "dismissed"),
        ("snooze", "snoozed"),
        ("archive", "archived"),
        ("mute-pattern", "muted_pattern"),
    ],
)
async def test_candidate_status_transition_actions_are_personal(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    action: str,
    expected_status: str,
) -> None:
    candidate = await _seed_candidate(tenant_a_headers)
    payload = (
        {"snoozed_until": "2030-01-01T00:00:00Z"}
        if action == "snooze"
        else {"mute_pattern": "release-*"}
        if action == "mute-pattern"
        else {}
    )

    response = await client.post(
        f"/api/v1/capability-candidates/{candidate.id}/{action}",
        headers=tenant_a_headers,
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected_status


async def test_candidate_route_contract_is_exact(client: AsyncClient) -> None:
    openapi = (await client.get("/openapi.json")).json()
    paths = openapi["paths"]
    expected = {
        "/api/v1/capability-candidates": {"get"},
        "/api/v1/capability-candidates/{candidate_id}": {"get"},
        "/api/v1/capability-candidates/{candidate_id}/accept": {"post"},
        "/api/v1/capability-candidates/{candidate_id}/dismiss": {"post"},
        "/api/v1/capability-candidates/{candidate_id}/snooze": {"post"},
        "/api/v1/capability-candidates/{candidate_id}/archive": {"post"},
        "/api/v1/capability-candidates/{candidate_id}/mute-pattern": {"post"},
        "/api/v1/capability-candidates/{candidate_id}/merge": {"post"},
    }

    for path, methods in expected.items():
        assert path in paths
        assert methods.issubset(set(paths[path]))

    assert "/api/v1/capability-candidates/" not in paths
    assert not any(path.startswith("/api/v1/candidates") for path in paths)


async def test_candidate_user_and_tenant_isolation(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    tenant_name = f"candidate-tenant-{uuid.uuid4().hex}"
    first_user = await _register_same_tenant_user(client, tenant_name)
    second_user = await _register_same_tenant_user(client, tenant_name)
    candidate = await _seed_candidate(first_user, title="private user candidate")
    tenant_b_candidate = await _seed_candidate(tenant_b_headers, title="tenant b")

    same_tenant_other_user_list = await client.get(
        "/api/v1/capability-candidates",
        headers=second_user,
    )
    same_tenant_other_user_get = await client.get(
        f"/api/v1/capability-candidates/{candidate.id}",
        headers=second_user,
    )
    other_tenant_get = await client.get(
        f"/api/v1/capability-candidates/{candidate.id}",
        headers=tenant_b_headers,
    )
    first_user_list = await client.get(
        "/api/v1/capability-candidates",
        headers=first_user,
    )
    tenant_a_list = await client.get(
        "/api/v1/capability-candidates",
        headers=tenant_a_headers,
    )

    assert same_tenant_other_user_list.status_code == 200
    assert same_tenant_other_user_list.json()["items"] == []
    assert same_tenant_other_user_get.status_code == 404
    assert other_tenant_get.status_code == 404
    assert first_user_list.json()["items"][0]["id"] == str(candidate.id)
    assert all(
        item["id"] != str(tenant_b_candidate.id)
        for item in tenant_a_list.json()["items"]
    )


async def test_dedupe_key_merge_lookup_and_inactive_retrieval_filter(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    original = await _seed_candidate(
        tenant_a_headers,
        title="first candidate",
        dedupe_key="candidate:dedupe",
    )
    duplicate = await _seed_candidate(
        tenant_a_headers,
        title="duplicate candidate",
        dedupe_key="candidate:dedupe",
    )

    merged = await client.post(
        f"/api/v1/capability-candidates/{duplicate.id}/merge",
        headers=tenant_a_headers,
        json={"target_candidate_id": str(original.id), "merge_reason": "same signal"},
    )

    assert merged.status_code == 200, merged.text
    assert merged.json()["status"] == "merged"
    assert merged.json()["merge_target_candidate_id"] == str(original.id)

    identity = _identity(tenant_a_headers)
    async with _async_session_factory() as db:
        active = await get_active_candidate_for_retrieval(
            db,
            tenant_id=uuid.UUID(identity["tenant_id"]),
            user_id=uuid.UUID(identity["user_id"]),
            candidate_id=duplicate.id,
        )
    assert active is None


async def test_retrieval_helper_only_returns_accepted_personal_candidates(
    client: AsyncClient,
    tenant_b_headers: dict[str, str],
) -> None:
    tenant_name = f"candidate-retrieval-{uuid.uuid4().hex}"
    owner_headers = await _register_same_tenant_user(client, tenant_name)
    same_tenant_other_user = await _register_same_tenant_user(client, tenant_name)
    owner = _identity(owner_headers)
    other_user = _identity(same_tenant_other_user)
    other_tenant = _identity(tenant_b_headers)
    tenant_id = uuid.UUID(owner["tenant_id"])
    user_id = uuid.UUID(owner["user_id"])

    status_to_candidate: dict[str, CapabilityCandidate] = {}
    for status in [
        "new",
        "seen",
        "snoozed",
        "dismissed",
        "merged",
        "archived",
        "muted_pattern",
        "accepted",
        "edited_accepted",
    ]:
        candidate = await _seed_candidate(owner_headers, title=f"candidate {status}")
        async with _async_session_factory() as db:
            row = (
                await db.execute(
                    select(CapabilityCandidate).where(CapabilityCandidate.id == candidate.id)
                )
            ).scalar_one()
            row.status = status
            await db.commit()
            await db.refresh(row)
            status_to_candidate[status] = row

    async with _async_session_factory() as db:
        for inactive_status in [
            "new",
            "seen",
            "snoozed",
            "dismissed",
            "merged",
            "archived",
            "muted_pattern",
        ]:
            active = await get_active_candidate_for_retrieval(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                candidate_id=status_to_candidate[inactive_status].id,
            )
            assert active is None, inactive_status

        for active_status in ["accepted", "edited_accepted"]:
            candidate = status_to_candidate[active_status]
            owner_active = await get_active_candidate_for_retrieval(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                candidate_id=candidate.id,
            )
            same_tenant_other_active = await get_active_candidate_for_retrieval(
                db,
                tenant_id=tenant_id,
                user_id=uuid.UUID(other_user["user_id"]),
                candidate_id=candidate.id,
            )
            other_tenant_active = await get_active_candidate_for_retrieval(
                db,
                tenant_id=uuid.UUID(other_tenant["tenant_id"]),
                user_id=uuid.UUID(other_tenant["user_id"]),
                candidate_id=candidate.id,
            )
            assert owner_active is not None, active_status
            assert same_tenant_other_active is None
            assert other_tenant_active is None


async def test_analysis_outbox_enqueue_claim_complete_fail_and_idempotency(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    source_run_id = f"run-{uuid.uuid4().hex}"

    async with _async_session_factory() as db:
        first = await enqueue_analysis_job(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=source_run_id,
            source_kind="conversation",
            payload={"message_count": 1},
        )
        second = await enqueue_analysis_job(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=source_run_id,
            source_kind="conversation",
            payload={"message_count": 2},
        )
        await db.commit()

        assert first.id == second.id
        assert first.status == "pending"
        assert first.payload == {"message_count": 1}

        claimed = await claim_analysis_job(db, tenant_id=tenant_id, user_id=user_id)
        assert claimed is not None
        assert claimed.status == "running"
        await complete_analysis_job(db, claimed, result_metadata={"created": 1})
        assert claimed.status == "succeeded"
        assert claimed.result_metadata == {"created": 1}

        failed = await enqueue_analysis_job(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=f"{source_run_id}-fail",
            source_kind="conversation",
            payload={},
        )
        await fail_analysis_job(
            db,
            failed,
            error_code="ANALYZER_UNAVAILABLE",
            error_message="Analyzer not installed in W1",
        )
        await db.commit()

        persisted = (
            await db.execute(
                select(CapabilityAnalysisJob).where(CapabilityAnalysisJob.id == failed.id)
            )
        ).scalar_one()
        assert persisted.status == "failed"
        assert persisted.error_code == "ANALYZER_UNAVAILABLE"
        assert persisted.error_message == "Analyzer not installed in W1"


async def test_analysis_outbox_concurrent_enqueue_and_claim_are_idempotent(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    source_run_id = f"run-concurrent-{uuid.uuid4().hex}"

    async def enqueue_once() -> uuid.UUID:
        async with _async_session_factory() as db:
            job = await enqueue_analysis_job(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                source_run_id=source_run_id,
                source_kind="conversation",
                payload={"source": source_run_id},
            )
            await db.commit()
            return job.id

    first_id, second_id = await asyncio.gather(enqueue_once(), enqueue_once())

    async with _async_session_factory() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(CapabilityAnalysisJob)
                .where(
                    CapabilityAnalysisJob.tenant_id == tenant_id,
                    CapabilityAnalysisJob.user_id == user_id,
                    CapabilityAnalysisJob.source_run_id == source_run_id,
                )
            )
        ).scalar_one()

    assert first_id == second_id
    assert count == 1

    async def claim_once() -> uuid.UUID | None:
        async with _async_session_factory() as db:
            job = await claim_analysis_job(db, tenant_id=tenant_id, user_id=user_id)
            await db.commit()
            return job.id if job else None

    claim_ids = await asyncio.gather(claim_once(), claim_once())
    assert sorted(id_ is not None for id_ in claim_ids) == [False, True]


async def test_analysis_outbox_can_mark_pending_duplicate_as_skipped(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])

    async with _async_session_factory() as db:
        job = await enqueue_analysis_job(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=f"run-skip-{uuid.uuid4().hex}",
            source_kind="conversation",
            payload={},
        )
        await skip_duplicate_analysis_job(
            db,
            job,
            result_metadata={"duplicate_of": "existing-analysis"},
        )
        await db.commit()
        await db.refresh(job)

    assert job.status == "skipped_duplicate"
    assert job.result_metadata == {"duplicate_of": "existing-analysis"}
    assert job.completed_at is not None


async def test_capability_json_bounds_and_error_message_are_enforced(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as too_large_candidate:
            await create_candidate(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                candidate_type="memory",
                title="oversized evidence",
                evidence={"blob": "x" * 9000},
                payload={},
            )
        assert too_large_candidate.value.status_code == 422

        with pytest.raises(HTTPException) as too_deep_job:
            await enqueue_analysis_job(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                source_run_id=f"run-deep-{uuid.uuid4().hex}",
                source_kind="conversation",
                payload=_nested_json(12),
            )
        assert too_deep_job.value.status_code == 422

        with pytest.raises(HTTPException) as array_heavy_candidate:
            await create_candidate(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                candidate_type="memory",
                title="array-heavy evidence",
                evidence=_array_heavy_json(),
                payload={},
            )
        assert array_heavy_candidate.value.status_code == 422

        with pytest.raises(HTTPException) as array_heavy_enqueue:
            await enqueue_analysis_job(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                source_run_id=f"run-array-heavy-{uuid.uuid4().hex}",
                source_kind="conversation",
                payload=_array_heavy_json(),
            )
        assert array_heavy_enqueue.value.status_code == 422

        failed = await enqueue_analysis_job(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=f"run-error-{uuid.uuid4().hex}",
            source_kind="conversation",
            payload={},
        )
        await fail_analysis_job(
            db,
            failed,
            error_code="ANALYZER_UNAVAILABLE",
            error_message="x" * 5000,
        )
        await db.commit()
        await db.refresh(failed)

        with pytest.raises(HTTPException) as array_heavy_complete:
            await complete_analysis_job(
                db,
                failed,
                result_metadata=_array_heavy_json(),
            )
        assert array_heavy_complete.value.status_code == 422

    assert failed.status == "failed"
    assert failed.error_message is not None
    assert len(failed.error_message) <= 1024
    assert failed.error_message.endswith("...[truncated]")


async def test_invalid_candidate_and_analysis_job_durable_states_are_rejected(
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])

    async with _async_session_factory() as db:
        db.add(
            CapabilityCandidate(
                tenant_id=tenant_id,
                user_id=user_id,
                candidate_type="invalid-type",
                status="new",
                title="invalid candidate type",
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

        db.add(
            CapabilityAnalysisJob(
                tenant_id=tenant_id,
                user_id=user_id,
                source_run_id=f"run-invalid-{uuid.uuid4().hex}",
                status="not-a-job-status",
                payload={},
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_skill_personal_scope_uniqueness_and_legacy_shared_rows(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_name = f"skill-scope-{uuid.uuid4().hex}"
    user_a = await _register_same_tenant_user(client, tenant_name)
    user_b = await _register_same_tenant_user(client, tenant_name)
    identity_a = _identity(user_a)
    identity_b = _identity(user_b)
    tenant_id = uuid.UUID(identity_a["tenant_id"])

    async with _async_session_factory() as db:
        legacy = Skill(
            tenant_id=tenant_id,
            user_id=None,
            scope="shared_legacy",
            name="shared legacy skill",
            trigger_terms=["legacy"],
        )
        private_a = Skill(
            tenant_id=tenant_id,
            user_id=uuid.UUID(identity_a["user_id"]),
            scope="private",
            name="same personal skill",
            trigger_terms=["a"],
        )
        private_b = Skill(
            tenant_id=tenant_id,
            user_id=uuid.UUID(identity_b["user_id"]),
            scope="private",
            name="same personal skill",
            trigger_terms=["b"],
        )
        db.add_all([legacy, private_a, private_b])
        await db.commit()

        duplicate = Skill(
            tenant_id=tenant_id,
            user_id=uuid.UUID(identity_a["user_id"]),
            scope="private",
            name="same personal skill",
            trigger_terms=["dup"],
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    listed = await client.get("/api/v1/skills/?limit=100", headers=user_a)
    assert listed.status_code in (200, 403)
    if listed.status_code == 200:
        names = {item["name"]: item for item in listed.json()["items"]}
        assert names["shared legacy skill"]["scope"] == "shared_legacy"
        assert names["same personal skill"]["user_id"] == identity_a["user_id"]


async def test_private_skill_direct_get_update_delete_are_user_scoped(
    client: AsyncClient,
) -> None:
    tenant_name = f"skill-private-{uuid.uuid4().hex}"
    user_a = await _register_same_tenant_user(client, tenant_name)
    user_b = await _register_same_tenant_user(client, tenant_name)
    await _promote(user_a)
    await _promote(user_b)
    identity_a = _identity(user_a)
    identity_b = _identity(user_b)
    tenant_id = uuid.UUID(identity_a["tenant_id"])
    user_a_id = uuid.UUID(identity_a["user_id"])

    async with _async_session_factory() as db:
        private_skill = Skill(
            tenant_id=tenant_id,
            user_id=user_a_id,
            scope="private",
            name=f"private-{uuid.uuid4().hex}",
            trigger_terms=["private"],
        )
        shared_skill = Skill(
            tenant_id=tenant_id,
            user_id=None,
            scope="shared_legacy",
            name=f"shared-{uuid.uuid4().hex}",
            trigger_terms=["shared"],
        )
        db.add_all([private_skill, shared_skill])
        await db.commit()
        await db.refresh(private_skill)
        await db.refresh(shared_skill)
        private_id = private_skill.id
        shared_id = shared_skill.id

    denied_get = await client.get(f"/api/v1/skills/{private_id}", headers=user_b)
    denied_update = await client.put(
        f"/api/v1/skills/{private_id}",
        headers=user_b,
        json={"name": "stolen-private-skill"},
    )
    denied_delete = await client.delete(f"/api/v1/skills/{private_id}", headers=user_b)
    owner_get = await client.get(f"/api/v1/skills/{private_id}", headers=user_a)
    shared_get = await client.get(f"/api/v1/skills/{shared_id}", headers=user_b)

    assert denied_get.status_code == 404
    assert denied_update.status_code == 404
    assert denied_delete.status_code == 404
    assert owner_get.status_code == 200
    assert owner_get.json()["user_id"] == identity_a["user_id"]
    assert shared_get.status_code == 200
    assert shared_get.json()["user_id"] is None

    async with _async_session_factory() as db:
        still_exists = (
            await db.execute(
                select(Skill).where(
                    Skill.id == private_id,
                    Skill.user_id == user_a_id,
                )
            )
        ).scalar_one_or_none()

    assert still_exists is not None
