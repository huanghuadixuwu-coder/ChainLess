"""Memory management API endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import not_found
from app.api.deps import get_db, require_role
from app.api.pagination import paginated_response
from app.config import settings
from app.core.memory.layered import load_layered_instructions
from app.core.memory.persistent import (
    _compute_embedding_best_effort,
    create_memory,
    get_memories_for_session,
    search_memories,
    search_by_tags,
)
from app.models.memory import Memory

router = APIRouter(prefix="/memories", tags=["memories"])


class _CreateMemoryRequest(BaseModel):
    type: str = "user"
    name: str
    content: str
    tags: list[str] | None = None
    description: str | None = None


class _UpdateMemoryRequest(BaseModel):
    content: str | None = None
    name: str | None = None
    tags: list[str] | None = None
    description: str | None = None


class _MergeRequest(BaseModel):
    task: str


class _MemoryResponse(BaseModel):
    id: str
    type: str
    name: str
    content: str | None
    description: str | None
    tags: list[str] | None
    created_at: str
    updated_at: str


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_memory_endpoint(
    body: _CreateMemoryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    mem = await create_memory(
        db=db,
        tenant_id=current_user["tenant_id"],
        memory_type=body.type,
        name=body.name,
        content=body.content,
        tags=body.tags,
        user_id=current_user["user_id"],
        description=body.description,
    )
    return _memory_to_response(mem)


@router.get("/")
async def list_memories(
    type: str | None = Query(None, description="Filter by memory type"),
    tags: str | None = Query(None, description="Comma-separated tag filter"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    tenant_id = current_user["tenant_id"]
    conditions = [Memory.tenant_id == tenant_id]

    if type:
        conditions.append(Memory.type == type)

    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        conditions.append(Memory.tags.overlap(tag_list))

    count_q = select(func.count()).select_from(Memory).where(*conditions)
    total = (await db.execute(count_q)).scalar()

    rows_q = (
        select(Memory)
        .where(*conditions)
        .order_by(Memory.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(rows_q)).scalars().all()

    items = [_memory_to_response(m) for m in rows]
    return paginated_response(items, total, limit, offset, request)


@router.get("/search")
async def search_memories_endpoint(
    q: str = Query(..., description="Search query"),
    limit: int = Query(5, ge=1, le=50),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    try:
        mems = await search_memories(
            db, current_user["tenant_id"], query=q, limit=limit
        )
    except Exception:
        mems = await search_by_tags(
            db, current_user["tenant_id"], [], limit=limit
        )

    items = [_memory_to_response(m) for m in mems]
    total = len(items)
    return paginated_response(items, total, limit, offset, request)


@router.put("/{memory_id}")
async def update_memory(
    memory_id: uuid.UUID,
    body: _UpdateMemoryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    result = await db.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.tenant_id == current_user["tenant_id"],
        )
    )
    mem = result.scalar_one_or_none()
    if mem is None:
        raise not_found("MEMORY_NOT_FOUND", "Memory not found")

    changed = False
    if body.content is not None and body.content != mem.content:
        mem.content = body.content
        mem.embedding = await _compute_embedding_best_effort(body.content)
        changed = True

    if body.name is not None:
        mem.name = body.name
        changed = True
    if body.tags is not None:
        mem.tags = body.tags
        changed = True
    if body.description is not None:
        mem.description = body.description
        changed = True

    if changed:
        await db.commit()
        await db.refresh(mem)

    return _memory_to_response(mem)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    result = await db.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.tenant_id == current_user["tenant_id"],
        )
    )
    mem = result.scalar_one_or_none()
    if mem is None:
        raise not_found("MEMORY_NOT_FOUND", "Memory not found")

    await db.delete(mem)
    await db.commit()
    return None


@router.post("/merge")
async def merge_context(
    body: _MergeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    tenant_id = current_user["tenant_id"]

    memories = await get_memories_for_session(
        db, tenant_id, body.task, limit=5
    )
    memory_context = "\n\n".join(
        f"## {m.name}\n{m.content or ''}" for m in memories
    )

    instructions = load_layered_instructions(settings.memory_base_path, tenant_id)

    merged = []
    if memory_context:
        merged.append(
            "The following memories are relevant to the current task:\n"
            + memory_context
        )
    if instructions:
        merged.append(
            "The following layered instructions apply:\n" + instructions
        )

    return {
        "context": "\n\n---\n\n".join(merged) if merged else "",
        "memories": [_memory_to_response(m) for m in memories],
        "has_instructions": bool(instructions),
    }


def _memory_to_response(mem: Memory) -> _MemoryResponse:
    return _MemoryResponse(
        id=str(mem.id),
        type=mem.type,
        name=mem.name,
        content=mem.content,
        description=mem.description,
        tags=mem.tags,
        created_at=mem.created_at.isoformat() if mem.created_at else "",
        updated_at=mem.updated_at.isoformat() if mem.updated_at else "",
    )
