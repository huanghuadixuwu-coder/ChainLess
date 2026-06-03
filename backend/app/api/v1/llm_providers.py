"""LLM Provider management API — configure LLM providers per tenant."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.llm.gateway import LLMGateway
from app.main import app_state

router = APIRouter(prefix="/llm-providers")


class ProviderCreate(BaseModel):
    name: str
    api_base: str
    api_key: str
    model: str
    embedding_model: str | None = "text-embedding-3-small"
    is_default: bool = False


class ProviderUpdate(BaseModel):
    api_base: str | None = None
    api_key: str | None = None
    model: str | None = None
    embedding_model: str | None = None
    is_default: bool | None = None


# In-memory provider registry (persisted to DB in future)
_providers: dict[str, dict] = {}


@router.post("/")
async def create_provider(body: ProviderCreate, user=Depends(get_current_user)):
    key = f"{user['tenant_id']}:{body.name}"
    _providers[key] = {
        "name": body.name, "api_base": body.api_base,
        "api_key": body.api_key, "model": body.model,
        "embedding_model": body.embedding_model, "is_default": body.is_default
    }
    gateway: LLMGateway = app_state.llm_gateway
    gateway.register(body.name, body.api_base, body.api_key, body.model, body.embedding_model)
    return {"name": body.name, "registered": True}


@router.get("/")
async def list_providers(user=Depends(get_current_user)):
    prefix = f"{user['tenant_id']}:"
    items = [{"name": v["name"], "model": v["model"],
              "api_base": v["api_base"][:40] + "...",
              "is_default": v["is_default"]}
             for k, v in _providers.items() if k.startswith(prefix)]
    return {"items": items, "total": len(items)}


@router.put("/{name}")
async def update_provider(name: str, body: ProviderUpdate,
                          user=Depends(get_current_user)):
    key = f"{user['tenant_id']}:{name}"
    if key not in _providers:
        raise HTTPException(404, detail={"error": {"code": "PROVIDER_NOT_FOUND",
                                                     "message": f"Provider '{name}' not found"}})
    for field in ("api_base", "api_key", "model", "embedding_model", "is_default"):
        val = getattr(body, field)
        if val is not None:
            _providers[key][field] = val
    p = _providers[key]
    gateway: LLMGateway = app_state.llm_gateway
    gateway.register(name, p["api_base"], p["api_key"], p["model"], p["embedding_model"])
    return {"name": name, "updated": True}


@router.delete("/{name}")
async def delete_provider(name: str, user=Depends(get_current_user)):
    key = f"{user['tenant_id']}:{name}"
    if key not in _providers:
        raise HTTPException(404, detail={"error": {"code": "PROVIDER_NOT_FOUND",
                                                     "message": f"Provider '{name}' not found"}})
    del _providers[key]
    return {"deleted": True}


@router.get("/test/{name}")
async def test_provider(name: str, user=Depends(get_current_user)):
    """Test connectivity by sending a ping prompt to the provider."""
    gateway: LLMGateway = app_state.llm_gateway
    try:
        output = []
        async for delta in gateway.chat_stream(
            name, [{"role": "user", "content": "Say 'pong' and nothing else."}],
            max_tokens=10
        ):
            if delta["type"] == "text":
                output.append(delta["content"])
        return {"status": "ok", "response": "".join(output).strip(), "provider": name}
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": {"code": "LLM_PROVIDER_ERROR", "message": str(e)}}
        )
