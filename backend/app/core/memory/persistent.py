"""Memory CRUD with async embedding via ARQ.

Provides helpers to create, search, and retrieve memories for a tenant.
Embedding computation is offloaded to a background ARQ worker so that
the API response is not blocked by the LLM embedding call.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory

logger = logging.getLogger(__name__)


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

    # Fire-and-forget: don't block the API response waiting for Redis.
    asyncio.ensure_future(_enqueue_embedding_safe(str(mem.id), content))

    return mem


async def _enqueue_embedding_safe(memory_id: str, content: str) -> None:
    """Enqueue an embedding job, logging (not swallowing) failures."""
    try:
        from app.core.memory.tasks import enqueue_embedding

        await enqueue_embedding(memory_id, content)
    except Exception as exc:
        logger.warning("Failed to enqueue embedding for %s: %s", memory_id, exc)


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
        logger.warning("Semantic search failed, falling back to tag search", exc_info=True)
        # Fallback: return recent memories by tag
        return await search_by_tags(db, tenant_id, [], limit)
