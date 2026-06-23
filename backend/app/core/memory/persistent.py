"""Memory CRUD with async embedding via ARQ.

Provides helpers to create, search, and retrieve memories for a tenant.
Embedding computation is offloaded to a background ARQ worker so that
the API response is not blocked by the LLM embedding call.
"""

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import not_found
from app.config import settings
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
    metadata: dict | None = None,
    commit: bool = True,
    write_source: bool = True,
    compute_inline_embedding: bool = True,
) -> Memory:
    """Create a memory row and enqueue async embedding computation.

    The ``embedding`` column is set immediately when embedding is available,
    otherwise it is backfilled asynchronously.
    """
    embedding = None
    if compute_inline_embedding:
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
        meta_data=metadata or {},
    )
    db.add(mem)
    if commit:
        await db.commit()
    else:
        await db.flush()
    await db.refresh(mem)

    if embedding is None and commit:
        asyncio.ensure_future(_enqueue_embedding_safe(str(mem.id), content))
    if write_source:
        write_memory_source(mem)

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


async def write_memory_source_safe(memory: Memory) -> None:
    """Write the derived memory source file without failing the durable DB write."""
    try:
        write_memory_source(memory)
    except Exception:
        logger.warning("Failed to write memory source for %s", memory.id)


async def delete_memory_from_acquisition(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    memory_id: uuid.UUID,
) -> None:
    """Remove a memory created by acquisition rollback without committing."""

    memory = (
        await db.execute(
            select(Memory)
            .where(
                Memory.id == memory_id,
                Memory.tenant_id == tenant_id,
                Memory.user_id == user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if memory is None:
        raise not_found("MEMORY_NOT_FOUND", "Memory not found")
    await db.delete(memory)
    await db.flush()


async def search_memories(
    db: AsyncSession,
    tenant_id: str,
    query: str,
    limit: int = 5,
    user_id: str | None = None,
    include_userless: bool = True,
) -> list[Memory]:
    """Semantic search via pgvector cosine distance."""
    from app.main import app_state

    await _backfill_missing_embeddings(
        db,
        tenant_id,
        user_id=user_id,
        include_userless=include_userless,
    )

    gateway = app_state.llm_gateway
    query_embedding = (await gateway.embed("default", [query], tenant_id=tenant_id))[0]

    result = await db.execute(
        select(Memory)
        .where(
            Memory.tenant_id == tenant_id,
            *_memory_visibility_conditions(user_id, include_userless=include_userless),
            Memory.embedding.isnot(None),
        )
        .order_by(Memory.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list(result.scalars().all())


async def _backfill_missing_embeddings(
    db: AsyncSession,
    tenant_id: str,
    limit: int = 25,
    user_id: str | None = None,
    include_userless: bool = True,
) -> None:
    result = await db.execute(
        select(Memory)
        .where(
            Memory.tenant_id == tenant_id,
            *_memory_visibility_conditions(user_id, include_userless=include_userless),
            Memory.embedding.is_(None),
        )
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
    user_id: str | None = None,
    include_userless: bool = True,
) -> list[Memory]:
    """Tag-based search using PostgreSQL array overlap (&&)."""
    if not tags:
        result = await db.execute(
            select(Memory)
            .where(
                Memory.tenant_id == tenant_id,
                *_memory_visibility_conditions(user_id, include_userless=include_userless),
            )
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    result = await db.execute(
        select(Memory)
        .where(
            Memory.tenant_id == tenant_id,
            *_memory_visibility_conditions(user_id, include_userless=include_userless),
            Memory.tags.overlap(tags),
        )
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
    user_id: str | None = None,
    include_userless: bool = True,
) -> list[str]:
    """Extract explicit and keyword-matched tags from the current task."""
    explicit = {
        _normalize_tag(tag)
        for tag in re.findall(r"(?<!\w)#([A-Za-z0-9_-]+)", task_description)
    }
    tokens = _task_tokens(task_description)

    result = await db.execute(
        select(Memory.tags).where(
            Memory.tenant_id == tenant_id,
            *_memory_visibility_conditions(user_id, include_userless=include_userless),
        )
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
    user_id: str | None = None,
    include_userless: bool = True,
) -> list[Memory]:
    """Get relevant memories for a session, with tag matches taking priority."""
    task_tags = await _extract_task_tags(
        db,
        tenant_id,
        task_description,
        user_id=user_id,
        include_userless=include_userless,
    )
    tag_matches = (
        await search_by_tags(
            db,
            tenant_id,
            task_tags,
            limit,
            user_id=user_id,
            include_userless=include_userless,
        )
        if task_tags
        else []
    )

    try:
        semantic_matches = await search_memories(
            db,
            tenant_id,
            task_description,
            limit,
            user_id=user_id,
            include_userless=include_userless,
        )
    except Exception:
        logger.warning(
            "Semantic search failed, falling back to tag search",
            exc_info=True,
        )
        semantic_matches = []

    merged = _merge_memory_results(tag_matches, semantic_matches, limit)
    if merged:
        return merged

    return await search_by_tags(
        db,
        tenant_id,
        [],
        limit,
        user_id=user_id,
        include_userless=include_userless,
    )


def _memory_visibility_conditions(user_id: str | None, *, include_userless: bool = True) -> list:
    if user_id is None:
        return []
    if not include_userless:
        return [Memory.user_id == user_id]
    return [(Memory.user_id.is_(None)) | (Memory.user_id == user_id)]


def memory_tenant_root(base_path: str, tenant_id: str) -> Path:
    """Return the tenant-scoped memory source directory."""
    return Path(base_path) / str(tenant_id) / "persistent"


def memory_index_path(base_path: str, tenant_id: str) -> Path:
    """Return the tenant-scoped MEMORY.md index path."""
    return memory_tenant_root(base_path, tenant_id) / "MEMORY.md"


def _memory_source_filename(memory: Memory) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", memory.name or "memory").strip("-")
    return f"{memory.type}-{name}-{memory.id}.md"


def render_memory_source(memory: Memory) -> str:
    """Render one memory as a durable markdown source file."""
    metadata = {
        "id": str(memory.id),
        "type": memory.type,
        "name": memory.name,
        "tags": memory.tags or [],
        "description": memory.description,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }
    return (
        "---\n"
        f"{json.dumps(metadata, ensure_ascii=False, sort_keys=True)}\n"
        "---\n\n"
        f"# {memory.name}\n\n"
        f"{memory.content or ''}\n"
    )


def write_memory_source(memory: Memory, base_path: str | None = None) -> Path:
    """Write a memory source file and refresh the tenant MEMORY.md index."""
    root = memory_tenant_root(base_path or settings.memory_base_path, str(memory.tenant_id))
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / _memory_source_filename(memory)
    source_path.write_text(render_memory_source(memory), encoding="utf-8")
    _refresh_memory_index(root)
    return source_path


def _refresh_memory_index(root: Path) -> None:
    entries = sorted(path for path in root.glob("*.md") if path.name != "MEMORY.md")
    lines = [
        "# MEMORY.md",
        "",
        "This tenant-scoped index is generated from durable memory source files.",
        "",
    ]
    for path in entries:
        lines.append(f"- [{path.stem}]({path.name})")
    (root / "MEMORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_memory_index(base_path: str, tenant_id: str) -> str:
    """Read the tenant MEMORY.md index, returning an empty string if missing."""
    path = memory_index_path(base_path, tenant_id)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_memory_context(memories: list[Memory], budget_chars: int | None = None) -> str:
    """Render cited memories within a configurable injection budget."""
    remaining = budget_chars if budget_chars is not None else settings.memory_injection_budget_chars
    parts: list[str] = []
    for memory in memories:
        tag_str = " ".join(f"#{tag}" for tag in (memory.tags or []))
        line = f"- [memory:{memory.name}] {memory.content or ''} {tag_str}".strip()
        if len(line) > remaining:
            if remaining <= 0:
                break
            line = line[: max(0, remaining - 15)] + " [truncated]"
        parts.append(line)
        remaining -= len(line)
        if remaining <= 0:
            break
    return "\n".join(parts)
