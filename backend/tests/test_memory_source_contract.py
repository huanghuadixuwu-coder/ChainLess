"""W8 memory source-of-truth, budget, and short-term context contract."""

from __future__ import annotations

import inspect
import uuid

import pytest

from app.api.deps import _async_session_factory
from app.main import app_state
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
from app.models.memory import Memory
from app.models.tenant import Tenant


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
