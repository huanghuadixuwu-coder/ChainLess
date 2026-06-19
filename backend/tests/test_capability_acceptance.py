"""Candidate acceptance contracts for Memory, Skill, and Worker drafts."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import HTTPException
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.api.deps import _async_session_factory
from app.core.memory import persistent as memory_persistent
from app.core.capabilities import service as capability_service
from app.core.capabilities.service import create_candidate
from app.models.capability import CapabilityCandidate
from app.models.memory import Memory
from app.models.skill import Skill
from app.models.worker import Worker, WorkerVersion
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> dict[str, str]:
    return decode_token(headers["Authorization"].split(" ", 1)[1])


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
    candidate_type: str,
    title: str,
    body: str = "Candidate body",
    payload: dict | None = None,
    worker_id: uuid.UUID | None = None,
    status: str = "new",
) -> CapabilityCandidate:
    identity = _identity(headers)
    async with _async_session_factory() as db:
        candidate = await create_candidate(
            db,
            tenant_id=uuid.UUID(identity["tenant_id"]),
            user_id=uuid.UUID(identity["user_id"]),
            candidate_type=candidate_type,
            title=title,
            body=body,
            source_run_id=f"run-{uuid.uuid4().hex}",
            source_event_id=f"event-{uuid.uuid4().hex}",
            source_message_id=f"message-{uuid.uuid4().hex}",
            source_uri="conversation://acceptance-test",
            source_kind="conversation",
            dedupe_key=f"{candidate_type}:{uuid.uuid4().hex}",
            evidence={"source_evidence": ["test evidence"]},
            payload=payload or {},
            worker_id=worker_id,
        )
        candidate.status = status
        await db.commit()
        await db.refresh(candidate)
        return candidate


async def test_accepting_memory_candidate_creates_private_memory_with_source_metadata(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    candidate = await _seed_candidate(
        tenant_a_headers,
        candidate_type="memory",
        title="Remember staging release checks",
        body="Use staging before production release.",
        payload={"memory_type": "project", "memory_text": "Use staging before production release.", "tags": ["release"]},
    )

    response = await client.post(
        f"/api/v1/capability-candidates/{candidate.id}/accept",
        headers=tenant_a_headers,
    )

    assert response.status_code == 200, response.text
    accepted = response.json()
    assert accepted["status"] == "accepted"
    memory_id = accepted["metadata"]["target"]["memory_id"]
    async with _async_session_factory() as db:
        memory = (
            await db.execute(select(Memory).where(Memory.id == uuid.UUID(memory_id)))
        ).scalar_one()
        refreshed = (
            await db.execute(select(CapabilityCandidate).where(CapabilityCandidate.id == candidate.id))
        ).scalar_one()

    assert memory.tenant_id == uuid.UUID(identity["tenant_id"])
    assert memory.user_id == uuid.UUID(identity["user_id"])
    assert memory.content == "Use staging before production release."
    assert memory.tags == ["release"]
    assert memory.meta_data["source"]["candidate_id"] == str(candidate.id)
    assert memory.meta_data["source"]["source_run_id"] == candidate.source_run_id
    assert refreshed.accepted_by == uuid.UUID(identity["user_id"])
    assert refreshed.metadata_["target"]["memory_id"] == str(memory.id)


async def test_accepting_memory_candidate_defers_embedding_and_safe_source_write(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_inline_embedding_runs(*args, **kwargs):
        raise AssertionError("accepted memory should not compute embeddings while holding the candidate lock")

    def fail_source_write(*args, **kwargs):
        raise RuntimeError("source file write is a derived side effect")

    monkeypatch.setattr(memory_persistent, "_compute_embedding_best_effort", fail_if_inline_embedding_runs)
    monkeypatch.setattr(memory_persistent, "write_memory_source", fail_source_write)

    candidate = await _seed_candidate(
        tenant_a_headers,
        candidate_type="memory",
        title="Remember deferred embedding",
        body="Persist first, derive files and embeddings after acceptance.",
        payload={
            "memory_type": "project",
            "memory_text": "Persist first, derive files and embeddings after acceptance.",
        },
    )

    response = await client.post(
        f"/api/v1/capability-candidates/{candidate.id}/accept",
        headers=tenant_a_headers,
    )
    await asyncio.sleep(0)

    assert response.status_code == 200, response.text
    memory_id = response.json()["metadata"]["target"]["memory_id"]
    async with _async_session_factory() as db:
        memory = (
            await db.execute(select(Memory).where(Memory.id == uuid.UUID(memory_id)))
        ).scalar_one()

    assert memory.embedding is None
    assert memory.content == "Persist first, derive files and embeddings after acceptance."


async def test_concurrent_memory_candidate_acceptance_is_exactly_once(
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    candidate = await _seed_candidate(
        tenant_a_headers,
        candidate_type="memory",
        title="Remember exactly once",
        body="Only one memory should be created.",
        payload={"memory_type": "project", "memory_text": "Only one memory should be created."},
    )

    original_accept_memory = capability_service._accept_memory_candidate
    first_accept_creating_target = asyncio.Event()
    second_accept_started = asyncio.Event()

    async def slow_first_memory_create(*args, **kwargs):
        if not first_accept_creating_target.is_set():
            first_accept_creating_target.set()
            await asyncio.wait_for(second_accept_started.wait(), timeout=2)
            await asyncio.sleep(0.2)
        return await original_accept_memory(*args, **kwargs)

    monkeypatch.setattr(capability_service, "_accept_memory_candidate", slow_first_memory_create)

    async def accept_once() -> tuple[int, dict]:
        async with _async_session_factory() as db:
            try:
                accepted = await capability_service.accept_candidate(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    candidate_id=candidate.id,
                )
            except HTTPException as exc:
                return exc.status_code, exc.detail
            return 200, capability_service.as_dict(accepted)

    first = asyncio.create_task(accept_once())
    await asyncio.wait_for(first_accept_creating_target.wait(), timeout=2)
    second = asyncio.create_task(accept_once())
    second_accept_started.set()

    results = await asyncio.gather(first, second)
    status_codes = [status for status, _ in results]

    assert status_codes.count(200) == 1
    assert status_codes.count(409) == 1
    conflict = next(body for status, body in results if status == 409)
    assert conflict["error"]["code"] == "CAPABILITY_CANDIDATE_NOT_ACCEPTABLE"

    async with _async_session_factory() as db:
        memories = list(
            (
                await db.execute(
                    select(Memory).where(Memory.meta_data["source"]["candidate_id"].astext == str(candidate.id))
                )
            ).scalars()
        )
        refreshed = (
            await db.execute(select(CapabilityCandidate).where(CapabilityCandidate.id == candidate.id))
        ).scalar_one()

    assert len(memories) == 1
    assert refreshed.metadata_["target"]["memory_id"] == str(memories[0].id)
    assert memories[0].meta_data["source"]["source_run_id"] == candidate.source_run_id


async def test_accepting_skill_candidate_creates_private_passive_skill(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    candidate = await _seed_candidate(
        tenant_a_headers,
        candidate_type="skill",
        title="Release checklist",
        body="Run the release checklist.",
        payload={"trigger_terms": ["Release", "release", "ship checklist"]},
    )

    response = await client.post(
        f"/api/v1/capability-candidates/{candidate.id}/accept",
        headers=tenant_a_headers,
    )

    assert response.status_code == 200, response.text
    skill_id = response.json()["metadata"]["target"]["skill_id"]
    async with _async_session_factory() as db:
        skill = (
            await db.execute(select(Skill).where(Skill.id == uuid.UUID(skill_id)))
        ).scalar_one()

    assert skill.tenant_id == uuid.UUID(identity["tenant_id"])
    assert skill.user_id == uuid.UUID(identity["user_id"])
    assert skill.scope == "private"
    assert skill.enabled is True
    assert skill.trigger_terms == ["Release", "ship checklist"]
    assert skill.metadata_["source"]["candidate_id"] == str(candidate.id)
    assert skill.metadata_["source"]["source_run_id"] == candidate.source_run_id


async def test_accepting_worker_candidate_creates_draft_worker_and_version(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    candidate = await _seed_candidate(
        tenant_a_headers,
        candidate_type="worker",
        title="Release note worker",
        body="Prepare release notes.",
        payload={
            "trigger": {"type": "manual"},
            "policy": {"requires_confirmation": True},
            "definition": {"steps": [{"type": "summarize_changes"}]},
            "verification_plan": {"checks": ["review before activation"]},
        },
    )

    response = await client.post(
        f"/api/v1/capability-candidates/{candidate.id}/accept",
        headers=tenant_a_headers,
    )

    assert response.status_code == 200, response.text
    target = response.json()["metadata"]["target"]
    async with _async_session_factory() as db:
        worker = (
            await db.execute(select(Worker).where(Worker.id == uuid.UUID(target["worker_id"])))
        ).scalar_one()
        version = (
            await db.execute(select(WorkerVersion).where(WorkerVersion.id == uuid.UUID(target["worker_version_id"])))
        ).scalar_one()

    assert worker.tenant_id == uuid.UUID(identity["tenant_id"])
    assert worker.user_id == uuid.UUID(identity["user_id"])
    assert worker.status == "draft"
    assert worker.enabled is False
    assert worker.active_version_id is None
    assert worker.metadata_["source"]["candidate_id"] == str(candidate.id)
    assert version.worker_id == worker.id
    assert version.version == 1
    assert version.status == "draft"
    assert version.definition == {"steps": [{"type": "summarize_changes"}]}


async def test_accepting_worker_improvement_creates_new_draft_version_without_overwrite(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    identity = _identity(tenant_a_headers)
    tenant_id = uuid.UUID(identity["tenant_id"])
    user_id = uuid.UUID(identity["user_id"])
    async with _async_session_factory() as db:
        worker = Worker(
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"Existing worker {uuid.uuid4().hex}",
            trigger={"type": "manual"},
            policy={},
        )
        db.add(worker)
        await db.flush()
        db.add(
            WorkerVersion(
                tenant_id=tenant_id,
                user_id=user_id,
                worker_id=worker.id,
                version=1,
                definition={"steps": [{"type": "existing"}]},
                verification_plan={"checks": ["existing"]},
            )
        )
        await db.commit()
        await db.refresh(worker)
        worker_id = worker.id

    candidate = await _seed_candidate(
        tenant_a_headers,
        candidate_type="worker",
        title="Improve release worker",
        body="Add changelog review.",
        payload={
            "definition": {"steps": [{"type": "existing"}, {"type": "review_changelog"}]},
            "verification_plan": {"checks": ["review draft"]},
        },
        worker_id=worker_id,
    )

    response = await client.post(
        f"/api/v1/capability-candidates/{candidate.id}/accept",
        headers=tenant_a_headers,
    )

    assert response.status_code == 200, response.text
    target = response.json()["metadata"]["target"]
    async with _async_session_factory() as db:
        versions = list(
            (
                await db.execute(
                    select(WorkerVersion).where(WorkerVersion.worker_id == worker_id).order_by(WorkerVersion.version)
                )
            ).scalars()
        )
        worker = (
            await db.execute(select(Worker).where(Worker.id == worker_id))
        ).scalar_one()

    assert target["worker_id"] == str(worker_id)
    assert [version.version for version in versions] == [1, 2]
    assert versions[0].definition == {"steps": [{"type": "existing"}]}
    assert versions[1].definition == {"steps": [{"type": "existing"}, {"type": "review_changelog"}]}
    assert versions[1].status == "draft"
    assert worker.status == "draft"
    assert worker.active_version_id is None


async def test_accepting_someone_elses_candidate_is_not_found(
    client: AsyncClient,
) -> None:
    tenant_name = f"candidate-acceptance-{uuid.uuid4().hex}"
    owner = await _register_same_tenant_user(client, tenant_name)
    same_tenant_other_user = await _register_same_tenant_user(client, tenant_name)
    candidate = await _seed_candidate(owner, candidate_type="memory", title="Private candidate")

    response = await client.post(
        f"/api/v1/capability-candidates/{candidate.id}/accept",
        headers=same_tenant_other_user,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CAPABILITY_CANDIDATE_NOT_FOUND"


@pytest.mark.parametrize("status", ["archived", "dismissed"])
async def test_accepting_inactive_candidate_is_rejected_with_unified_error(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    status: str,
) -> None:
    candidate = await _seed_candidate(
        tenant_a_headers,
        candidate_type="memory",
        title=f"{status} candidate",
        status=status,
    )

    response = await client.post(
        f"/api/v1/capability-candidates/{candidate.id}/accept",
        headers=tenant_a_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CAPABILITY_CANDIDATE_NOT_ACCEPTABLE"


async def test_accept_candidate_supports_strict_bounded_edited_proposal(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    candidate = await _seed_candidate(
        tenant_a_headers,
        candidate_type="memory",
        title="Original memory",
        body="Original text.",
    )

    edited = await client.post(
        f"/api/v1/capability-candidates/{candidate.id}/accept",
        headers=tenant_a_headers,
        json={"edited_proposal": {"name": "Edited memory", "content": "Edited text.", "tags": ["edited"]}},
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "edited_accepted"
    memory_id = edited.json()["metadata"]["target"]["memory_id"]
    async with _async_session_factory() as db:
        memory = (
            await db.execute(select(Memory).where(Memory.id == uuid.UUID(memory_id)))
        ).scalar_one()
    assert memory.name == "Edited memory"
    assert memory.content == "Edited text."
    assert memory.tags == ["edited"]

    extra_candidate = await _seed_candidate(
        tenant_a_headers,
        candidate_type="memory",
        title="Strict schema memory",
    )
    extra = await client.post(
        f"/api/v1/capability-candidates/{extra_candidate.id}/accept",
        headers=tenant_a_headers,
        json={"edited_proposal": {"content": "safe", "unexpected": True}},
    )
    oversized_candidate = await _seed_candidate(
        tenant_a_headers,
        candidate_type="memory",
        title="Oversized memory",
    )
    oversized = await client.post(
        f"/api/v1/capability-candidates/{oversized_candidate.id}/accept",
        headers=tenant_a_headers,
        json={"edited_proposal": {"content": "x" * 9000}},
    )

    assert extra.status_code == 422
    assert oversized.status_code == 422
