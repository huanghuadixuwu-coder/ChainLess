"""Memory CRUD with async embedding via ARQ.

Provides helpers to create, search, and retrieve memories for a tenant.
Embedding computation is offloaded to a background ARQ worker so that
the API response is not blocked by the LLM embedding call.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory


async def create_memory(
    db: AsyncSession,
    tenant_id: str,
    memory_type: str,
    name: str,
    content: str,
    tags: list[str] | None = None,
    user_id: str | None = None,
    description: str | None = None,
) -> Memory:
    """Create a memory row and enqueue async embedding computation.

    The ``embedding`` column is set to ``NULL`` — an ARQ background job
    computes and fills it later.
    """
    mem = Memory(
        tenant_id=tenant_id,
        user_id=user_id,
        type=memory_type,
        name=name,
        content=content,
        description=description,
        tags=tags or [],
        embedding=None,
    )
    db.add(mem)
    await db.commit()
    await db.refresh(mem)

    # Enqueue ARQ job for async embedding (best-effort).
    try:
        from app.core.memory.tasks import enqueue_embedding

        await enqueue_embedding(str(mem.id), content)
    except Exception:
        pass  # ARQ not running yet — embedding will be backfilled later

    return mem


async def search_memories(
    db: AsyncSession,
    tenant_id: str,
    query: str,
    limit: int = 5,
) -> list[Memory]:
    """Semantic search via pgvector cosine distance.

    Requires the LLM gateway to be available via ``app.main.app_state``.
    """
    from app.main import app_state

    gateway = app_state.llm_gateway
    query_embedding = (await gateway.embed("default", [query]))[0]

    result = await db.execute(
        select(Memory)
        .where(Memory.tenant_id == tenant_id, Memory.embedding.isnot(None))
        .order_by(Memory.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list(result.scalars().all())


async def search_by_tags(
    db: AsyncSession,
    tenant_id: str,
    tags: list[str],
    limit: int = 5,
) -> list[Memory]:
    """Tag-based search using PostgreSQL array overlap (&&).

    Useful as a fallback when embeddings have not yet been computed.
    """
    if not tags:
        # Return most recent memories when no tags are specified.
        result = await db.execute(
            select(Memory)
            .where(Memory.tenant_id == tenant_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    result = await db.execute(
        select(Memory)
        .where(Memory.tenant_id == tenant_id, Memory.tags.overlap(tags))
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_memories_for_session(
    db: AsyncSession,
    tenant_id: str,
    task_description: str,
    limit: int = 5,
) -> list[Memory]:
    """Get relevant memories for a session.

    Attempts semantic search first; falls back to tag-based / recent
    memories when the embedding service or gateway is unavailable.
    """
    try:
        return await search_memories(db, tenant_id, task_description, limit)
    except Exception:
        # Fallback: return recent memories by tag
        return await search_by_tags(db, tenant_id, [], limit)
