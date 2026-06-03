"""Agent CRUD API — manage configured agents per tenant."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from pydantic import BaseModel

from app.api.deps import get_db, get_current_user
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
async def create_agent(body: AgentCreate, user=Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
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
async def list_agents(limit: int = 20, offset: int = 0,
                      user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
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
        total, limit, offset, "/api/v1/agents")


@router.get("/{agent_id}")
async def get_agent(agent_id: str, user=Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user["tenant_id"]))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, detail={"error": {"code": "AGENT_NOT_FOUND", "message": "Agent not found"}})
    return {"id": str(agent.id), "name": agent.name, "system_prompt": agent.system_prompt,
            "llm_provider": agent.llm_provider, "is_active": agent.is_active,
            "created_at": agent.created_at.isoformat()}


@router.put("/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate,
                       user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user["tenant_id"]))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, detail={"error": {"code": "AGENT_NOT_FOUND", "message": "Agent not found"}})
    for field in ("name", "system_prompt", "llm_provider", "is_active"):
        if getattr(body, field) is not None:
            setattr(agent, field, getattr(body, field))
    await db.commit()
    return {"id": str(agent.id), "name": agent.name, "updated": True}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, user=Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user["tenant_id"]))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, detail={"error": {"code": "AGENT_NOT_FOUND", "message": "Agent not found"}})
    await db.delete(agent)
    await db.commit()
    return {"deleted": True}
