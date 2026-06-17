"""W8 memory source-of-truth, budget, and short-term context contract."""

from __future__ import annotations

import inspect
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.api.deps import _async_session_factory
from app.main import app_state
from app.core.capabilities.service import create_candidate
from app.core.memory import persistent
from app.core.memory.persistent import (
    build_memory_context,
    load_memory_index,
    search_memories,
    write_memory_source,
)
from app.core.memory.short_term import (
    append_short_term_context,
    cleanup_short_term_context,
    load_short_term_context,
    short_term_context_key,
)
from app.models.capability import CapabilityCandidate
from app.models.memory import Memory
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_service import decode_token


def _identity(headers: dict[str, str]) -> dict[str, str]:
    return decode_token(headers["Authorization"].split(" ", 1)[1])


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


async def _seed_memory_candidate(headers: dict[str, str], title: str) -> CapabilityCandidate:
    identity = _identity(headers)
    async with _async_session_factory() as db:
        candidate = await create_candidate(
            db,
            tenant_id=uuid.UUID(identity["tenant_id"]),
            user_id=uuid.UUID(identity["user_id"]),
            candidate_type="memory",
            title=title,
            body="Owner-only release memory",
            source_run_id=f"run-{uuid.uuid4().hex}",
            source_kind="conversation",
            dedupe_key=f"memory:{uuid.uuid4().hex}",
            evidence={"source_evidence": ["owner said remember this"]},
            payload={
                "memory_type": "project",
                "memory_text": "Owner-only release memory",
                "tags": ["owner-release"],
            },
        )
        await db.commit()
        await db.refresh(candidate)
        return candidate


def test_memory_source_file_and_index_are_tenant_scoped(tmp_path) -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    memory = Memory(
        id=uuid.uuid4(),
        tenant_id=tenant_a,
        type="user",
        name="Functional Style",
        content="The user prefers pure functions.",
        tags=["style"],
    )

    source = write_memory_source(memory, str(tmp_path))

    assert source.exists()
    assert "The user prefers pure functions." in source.read_text(encoding="utf-8")
    index = load_memory_index(str(tmp_path), str(tenant_a))
    assert "MEMORY.md" in index
    assert source.name in index
    assert load_memory_index(str(tmp_path), str(tenant_b)) == ""


def test_memory_context_respects_configurable_injection_budget() -> None:
    memory = Memory(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        type="project",
        name="Long",
        content="x" * 200,
        tags=[],
    )

    context = build_memory_context([memory], budget_chars=80)

    assert len(context) <= 92
    assert "[memory:Long]" in context
    assert "[truncated]" in context


def test_semantic_memory_search_uses_pgvector_cosine_distance_owner() -> None:
    source = inspect.getsource(persistent.search_memories)
    assert "cosine_distance" in source
    assert "Memory.embedding.isnot(None)" in source


@pytest.mark.asyncio
async def test_exact_memory_gate_uses_five_types_and_real_cosine_distance_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = Tenant(name=f"w8-memory-{uuid.uuid4().hex}", settings={})
    query_embedding = [0.0] * 1536
    query_embedding[0] = 1.0
    memory_vectors = []
    for index in range(5):
        vector = [0.0] * 1536
        vector[index] = 1.0
        memory_vectors.append(vector)

    class Gateway:
        async def embed(self, provider, texts, tenant_id=None):
            return [query_embedding for _ in texts]

    monkeypatch.setattr(app_state, "llm_gateway", Gateway())
    async with _async_session_factory() as db:
        db.add(tenant)
        await db.flush()
        for memory_type, name, vector in zip(
            ["user", "project", "reference", "feedback", "system"],
            ["nearest", "project", "reference", "feedback", "system"],
            memory_vectors,
        ):
            db.add(
                Memory(
                    tenant_id=tenant.id,
                    type=memory_type,
                    name=name,
                    content=f"{memory_type} memory",
                    tags=[memory_type],
                    embedding=vector,
                )
            )
        await db.commit()

        results = await search_memories(db, str(tenant.id), "nearest", limit=5)

        await db.delete(tenant)
        await db.commit()

    assert len(results) == 5
    assert {memory.type for memory in results} == {
        "user",
        "project",
        "reference",
        "feedback",
        "system",
    }
    assert results[0].name == "nearest"


@pytest.mark.asyncio
async def test_short_term_context_is_tenant_scoped_expiring_and_cleanable() -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())

    await append_short_term_context(
        tenant_a,
        conversation_id,
        role="user",
        content="tenant-a secret",
        ttl_seconds=60,
    )
    await append_short_term_context(
        tenant_b,
        conversation_id,
        role="user",
        content="tenant-b secret",
        ttl_seconds=60,
    )

    tenant_a_messages = await load_short_term_context(tenant_a, conversation_id)
    tenant_b_messages = await load_short_term_context(tenant_b, conversation_id)

    assert [message["content"] for message in tenant_a_messages] == ["tenant-a secret"]
    assert [message["content"] for message in tenant_b_messages] == ["tenant-b secret"]
    assert short_term_context_key(tenant_a, conversation_id) != short_term_context_key(
        tenant_b,
        conversation_id,
    )

    assert await cleanup_short_term_context(tenant_a, conversation_id) == 1
    assert await load_short_term_context(tenant_a, conversation_id) == []
    await cleanup_short_term_context(tenant_b, conversation_id)


@pytest.mark.asyncio
async def test_accepted_private_memory_list_search_and_merge_are_user_scoped(
    client: AsyncClient,
) -> None:
    tenant_name = f"memory-private-{uuid.uuid4().hex}"
    owner_headers = await _register_same_tenant_user(client, tenant_name)
    same_tenant_other = await _register_same_tenant_user(client, tenant_name)
    await _promote(owner_headers)
    await _promote(same_tenant_other)
    candidate = await _seed_memory_candidate(owner_headers, f"Owner release memory {uuid.uuid4().hex}")

    accepted = await client.post(
        f"/api/v1/capability-candidates/{candidate.id}/accept",
        headers=owner_headers,
    )
    assert accepted.status_code == 200, accepted.text
    memory_id = accepted.json()["metadata"]["target"]["memory_id"]

    owner_list = await client.get("/api/v1/memories/?limit=100", headers=owner_headers)
    other_list = await client.get("/api/v1/memories/?limit=100", headers=same_tenant_other)
    other_search = await client.get(
        "/api/v1/memories/search?q=owner-release&limit=50",
        headers=same_tenant_other,
    )
    other_merge = await client.post(
        "/api/v1/memories/merge",
        headers=same_tenant_other,
        json={"task": "owner-release"},
    )

    assert owner_list.status_code == 200
    assert memory_id in {item["id"] for item in owner_list.json()["items"]}
    assert other_list.status_code == 200
    assert memory_id not in {item["id"] for item in other_list.json()["items"]}
    assert other_search.status_code == 200
    assert memory_id not in {item["id"] for item in other_search.json()["items"]}
    assert other_merge.status_code == 200
    assert memory_id not in {item["id"] for item in other_merge.json()["memories"]}
