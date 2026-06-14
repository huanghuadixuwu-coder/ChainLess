"""Memory CRUD with async embedding via ARQ.

Provides helpers to create, search, and retrieve memories for a tenant.
Embedding computation is offloaded to a background ARQ worker so that
the API response is not blocked by the LLM embedding call.
"""

import asyncio
import logging
import re

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

    The ``embedding`` column is set immediately when embedding is available,
    otherwise it is backfilled asynchronously.
    """
    embedding = await _compute_embedding_best_effort(tenant_id, content)

    mem = Memory(
        tenant_id=tenant_id,
        user_id=user_id,
        type=memory_type,
        name=name,
        content=content,
        description=description,
        tags=tags or [],
        embedding=embedding,
    )
    db.add(mem)
    await db.commit()
    await db.refresh(mem)

    if embedding is None:
        asyncio.ensure_future(_enqueue_embedding_safe(str(mem.id), content))

    return mem


async def _compute_embedding_best_effort(tenant_id: str, content: str) -> list[float] | None:
    try:
        from app.main import app_state

        gateway = app_state.llm_gateway
        if gateway is None:
            return None
        return (await gateway.embed("default", [content], tenant_id=tenant_id))[0]
    except Exception:
        logger.warning("Inline embedding failed")
        return None


async def _enqueue_embedding_safe(memory_id: str, content: str) -> None:
    """Enqueue an embedding job, logging (not swallowing) failures."""
    try:
        from app.core.memory.tasks import enqueue_embedding

        await enqueue_embedding(memory_id, content)
    except Exception:
        logger.warning("Failed to enqueue embedding for %s", memory_id)


async def search_memories(
    db: AsyncSession,
    tenant_id: str,
    query: str,
    limit: int = 5,
) -> list[Memory]:
    """Semantic search via pgvector cosine distance."""
    from app.main import app_state

    await _backfill_missing_embeddings(db, tenant_id)

    gateway = app_state.llm_gateway
    query_embedding = (await gateway.embed("default", [query], tenant_id=tenant_id))[0]

    result = await db.execute(
        select(Memory)
        .where(Memory.tenant_id == tenant_id, Memory.embedding.isnot(None))
        .order_by(Memory.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list(result.scalars().all())


async def _backfill_missing_embeddings(
    db: AsyncSession,
    tenant_id: str,
    limit: int = 25,
) -> None:
    result = await db.execute(
        select(Memory)
        .where(Memory.tenant_id == tenant_id, Memory.embedding.is_(None))
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )
    missing = list(result.scalars().all())
    if not missing:
        return

    for memory in missing:
        if not memory.content:
            continue
        embedding = await _compute_embedding_best_effort(tenant_id, memory.content)
        if embedding is not None:
            memory.embedding = embedding

    await db.commit()


async def search_by_tags(
    db: AsyncSession,
    tenant_id: str,
    tags: list[str],
    limit: int = 5,
) -> list[Memory]:
    """Tag-based search using PostgreSQL array overlap (&&)."""
    if not tags:
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
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def _normalize_tag(tag: str) -> str:
    return tag.strip().lower().lstrip("#")


def _task_tokens(task_description: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]+", task_description)
    }


async def _extract_task_tags(
    db: AsyncSession,
    tenant_id: str,
    task_description: str,
) -> list[str]:
    """Extract explicit and keyword-matched tags from the current task."""
    explicit = {
        _normalize_tag(tag)
        for tag in re.findall(r"(?<!\w)#([A-Za-z0-9_-]+)", task_description)
    }
    tokens = _task_tokens(task_description)

    result = await db.execute(
        select(Memory.tags).where(Memory.tenant_id == tenant_id)
    )
    known_tags: dict[str, str] = {}
    for tag_list in result.scalars().all():
        for tag in tag_list or []:
            normalized = _normalize_tag(tag)
            if normalized:
                known_tags.setdefault(normalized, tag)

    matches: list[str] = []
    for normalized, original in known_tags.items():
        parts = {part for part in re.split(r"[-_\s]+", normalized) if part}
        if normalized in explicit or normalized in tokens or (parts and parts <= tokens):
            matches.append(original)

    return matches


def _merge_memory_results(
    primary: list[Memory],
    secondary: list[Memory],
    limit: int,
) -> list[Memory]:
    merged: list[Memory] = []
    seen: set[str] = set()
    for memory in [*primary, *secondary]:
        memory_id = str(memory.id)
        if memory_id in seen:
            continue
        seen.add(memory_id)
        merged.append(memory)
        if len(merged) >= limit:
            break
    return merged


async def get_memories_for_session(
    db: AsyncSession,
    tenant_id: str,
    task_description: str,
    limit: int = 5,
) -> list[Memory]:
    """Get relevant memories for a session, with tag matches taking priority."""
    task_tags = await _extract_task_tags(db, tenant_id, task_description)
    tag_matches = await search_by_tags(db, tenant_id, task_tags, limit) if task_tags else []

    try:
        semantic_matches = await search_memories(db, tenant_id, task_description, limit)
    except Exception:
        logger.warning(
            "Semantic search failed, falling back to tag search",
            exc_info=True,
        )
        semantic_matches = []

    merged = _merge_memory_results(tag_matches, semantic_matches, limit)
    if merged:
        return merged

    return await search_by_tags(db, tenant_id, [], limit)
