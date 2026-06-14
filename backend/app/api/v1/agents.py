"""Agent CRUD API — manage configured agents per tenant."""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update
from pydantic import BaseModel

from app.api.contracts import not_found
from app.api.deps import get_db, require_role
from app.api.pagination import paginated_response
from app.models.agent import Agent

router = APIRouter(prefix="/agents")


class AgentCreate(BaseModel):
    name: str
    system_prompt: str = "You are a helpful AI assistant."
    llm_provider: str = "default"
    is_active: bool = True


class AgentUpdate(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    llm_provider: str | None = None
    is_active: bool | None = None


@router.post("/")
async def create_agent(body: AgentCreate, user=Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    if body.is_active:
        await db.execute(
            update(Agent)
            .where(Agent.tenant_id == user["tenant_id"])
            .values(is_active=False)
        )
    agent = Agent(tenant_id=user["tenant_id"], name=body.name,
                  system_prompt=body.system_prompt,
                  llm_provider=body.llm_provider, is_active=body.is_active)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return {"id": str(agent.id), "name": agent.name, "system_prompt": agent.system_prompt,
            "llm_provider": agent.llm_provider, "is_active": agent.is_active,
            "created_at": agent.created_at.isoformat()}


@router.get("/")
async def list_agents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    user=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Agent).where(Agent.tenant_id == user["tenant_id"])
        .order_by(Agent.created_at.desc()).offset(offset).limit(limit))
    agents = result.scalars().all()
    count_r = await db.execute(
        select(func.count()).select_from(Agent).where(Agent.tenant_id == user["tenant_id"]))
    total = count_r.scalar()
    return paginated_response(
        [{"id": str(a.id), "name": a.name, "system_prompt": a.system_prompt,
          "llm_provider": a.llm_provider, "is_active": a.is_active,
          "created_at": a.created_at.isoformat()} for a in agents],
        total, limit, offset, request)


@router.get("/{agent_id}")
async def get_agent(agent_id: uuid.UUID, user=Depends(require_role("admin")),
                    db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user["tenant_id"]))
    agent = result.scalar_one_or_none()
    if not agent:
        raise not_found("AGENT_NOT_FOUND", "Agent not found")
    return {"id": str(agent.id), "name": agent.name, "system_prompt": agent.system_prompt,
            "llm_provider": agent.llm_provider, "is_active": agent.is_active,
            "created_at": agent.created_at.isoformat()}


@router.put("/{agent_id}")
async def update_agent(agent_id: uuid.UUID, body: AgentUpdate,
                       user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user["tenant_id"]))
    agent = result.scalar_one_or_none()
    if not agent:
        raise not_found("AGENT_NOT_FOUND", "Agent not found")
    if body.is_active is True:
        await db.execute(
            update(Agent)
            .where(Agent.tenant_id == user["tenant_id"], Agent.id != agent.id)
            .values(is_active=False)
        )
    for field in ("name", "system_prompt", "llm_provider", "is_active"):
        if getattr(body, field) is not None:
            setattr(agent, field, getattr(body, field))
    await db.commit()
    return {"id": str(agent.id), "name": agent.name, "updated": True}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: uuid.UUID, user=Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user["tenant_id"]))
    agent = result.scalar_one_or_none()
    if not agent:
        raise not_found("AGENT_NOT_FOUND", "Agent not found")
    await db.delete(agent)
    await db.commit()
    return {"deleted": True}
