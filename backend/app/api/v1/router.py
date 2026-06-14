"""v1 API router — aggregates all v1 sub-routers."""

from fastapi import APIRouter

from app.api.v1.auth import auth_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.memories import router as memories_router
from app.api.v1.tools import router as tools_router
from app.api.v1.channels import router as channels_router
from app.api.v1.proactive import router as proactive_router
from app.api.v1.agents import router as agents_router
from app.api.v1.llm_providers import router as llm_providers_router
from app.api.v1.system import router as system_router
from app.api.v1.audit import router as audit_router
from app.api.v1.skills import router as skills_router
from app.api.v1.eval import router as eval_router
from app.api.v1.artifacts import router as artifacts_router
from app.api.v1.uploads import router as uploads_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(conversations_router)
api_router.include_router(memories_router)
api_router.include_router(tools_router)
api_router.include_router(channels_router)
api_router.include_router(proactive_router)
api_router.include_router(agents_router)
api_router.include_router(llm_providers_router)
api_router.include_router(system_router)
api_router.include_router(audit_router)
api_router.include_router(skills_router)
api_router.include_router(eval_router)
api_router.include_router(artifacts_router)
api_router.include_router(uploads_router)
