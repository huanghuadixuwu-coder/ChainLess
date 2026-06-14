"""Admin-only, tenant-scoped LLM provider settings API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, error_envelope, not_found, validation_error
from app.api.deps import get_db, require_role
from app.api.pagination import paginated_response
from app.core.audit.service import AuditRecord, write_audit_log
from app.core.llm.gateway import LLMGateway
from app.core.secrets import decrypt_secret, encrypt_secret, secret_metadata
from app.main import app_state
from app.models.llm_provider import LLMProvider

router = APIRouter(prefix="/llm-providers", tags=["settings"])
Admin = Depends(require_role("admin"))


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    api_base: str = Field(min_length=1, max_length=1000)
    api_key: str = Field(min_length=1)
    model: str = Field(min_length=1, max_length=255)
    embedding_model: str | None = Field(default="embedding-3", max_length=255)
    is_default: bool = False


class ProviderUpdate(BaseModel):
    api_base: str | None = Field(default=None, min_length=1, max_length=1000)
    api_key: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=255)
    embedding_model: str | None = Field(default=None, max_length=255)
    is_default: bool | None = None


def _tenant_id(user: dict) -> uuid.UUID:
    return uuid.UUID(user["tenant_id"])


async def _provider_or_404(db: AsyncSession, tenant_id: uuid.UUID, name: str) -> LLMProvider:
    provider = (
        await db.execute(
            select(LLMProvider).where(
                LLMProvider.tenant_id == tenant_id,
                LLMProvider.name == name,
            )
        )
    ).scalar_one_or_none()
    if provider is None:
        raise not_found("PROVIDER_NOT_FOUND", f"Provider '{name}' not found")
    return provider


def _serialize(provider: LLMProvider) -> dict:
    return {
        "id": str(provider.id),
        "name": provider.name,
        "api_base": provider.api_base,
        "model": provider.model,
        "embedding_model": provider.embedding_model,
        "is_default": provider.is_default,
        "api_key": secret_metadata(decrypt_secret(provider.encrypted_api_key)),
    }


async def _select_default(db: AsyncSession, tenant_id: uuid.UUID, provider: LLMProvider) -> None:
    await db.execute(
        update(LLMProvider)
        .where(LLMProvider.tenant_id == tenant_id, LLMProvider.id != provider.id)
        .values(is_default=False)
    )
    await db.flush()
    provider.is_default = True


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    tenant_id = _tenant_id(user)
    if (
        not body.name.strip()
        or not body.api_base.strip()
        or not body.api_key.strip()
        or not body.model.strip()
    ):
        raise validation_error("Provider name, api_base, api_key, and model cannot be blank")
    has_provider = bool(
        (
            await db.execute(
                select(LLMProvider.id).where(LLMProvider.tenant_id == tenant_id).limit(1)
            )
        ).scalar_one_or_none()
    )
    provider = LLMProvider(
        tenant_id=tenant_id,
        name=body.name.strip(),
        api_base=body.api_base.strip(),
        encrypted_api_key=encrypt_secret(body.api_key.strip()),
        model=body.model.strip(),
        embedding_model=body.embedding_model,
        is_default=False,
    )
    db.add(provider)
    if body.is_default or not has_provider:
        await _select_default(db, tenant_id, provider)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(409, "PROVIDER_EXISTS", "Provider name already exists") from exc
    await db.refresh(provider)
    return _serialize(provider)


@router.get("/")
async def list_providers(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    tenant_id = _tenant_id(user)
    total = int(
        (await db.execute(select(func.count()).select_from(LLMProvider).where(LLMProvider.tenant_id == tenant_id))).scalar()
        or 0
    )
    providers = list(
        (
            await db.execute(
                select(LLMProvider)
                .where(LLMProvider.tenant_id == tenant_id)
                .order_by(LLMProvider.name)
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return paginated_response([_serialize(provider) for provider in providers], total, limit, offset, request)


@router.put("/{name}")
async def update_provider(
    name: str,
    body: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    tenant_id = _tenant_id(user)
    provider = await _provider_or_404(db, tenant_id, name)
    if body.api_base is not None:
        if not body.api_base.strip():
            raise validation_error("api_base cannot be blank")
        provider.api_base = body.api_base.strip()
    if body.api_key is not None and body.api_key.strip():
        provider.encrypted_api_key = encrypt_secret(body.api_key)
    if body.model is not None:
        if not body.model.strip():
            raise validation_error("model cannot be blank")
        provider.model = body.model.strip()
    if body.embedding_model is not None:
        provider.embedding_model = body.embedding_model
    if body.is_default is True:
        await _select_default(db, tenant_id, provider)
    elif body.is_default is False and provider.is_default:
        raise validation_error("Select another default provider before unsetting this one")
    await db.commit()
    await db.refresh(provider)
    return _serialize(provider)


@router.post("/{name}/default")
async def set_default_provider(
    name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    tenant_id = _tenant_id(user)
    provider = await _provider_or_404(db, tenant_id, name)
    await _select_default(db, tenant_id, provider)
    await db.commit()
    await db.refresh(provider)
    return _serialize(provider)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    tenant_id = _tenant_id(user)
    provider = await _provider_or_404(db, tenant_id, name)
    replacement = None
    if provider.is_default:
        replacement = (
            await db.execute(
                select(LLMProvider)
                .where(LLMProvider.tenant_id == tenant_id, LLMProvider.id != provider.id)
                .order_by(LLMProvider.name)
                .limit(1)
            )
        ).scalar_one_or_none()
    await db.delete(provider)
    await db.flush()
    if replacement is not None:
        replacement.is_default = True
    await db.commit()
    return None


async def _test_provider(
    name: str,
    db: AsyncSession,
    user: dict,
    *,
    method: str,
    route_template: str,
) -> JSONResponse | dict:
    tenant_id = _tenant_id(user)
    provider = await _provider_or_404(db, tenant_id, name)
    gateway: LLMGateway = app_state.llm_gateway or LLMGateway()
    try:
        output = []
        async for delta in gateway.chat_stream(
            provider.name,
            [{"role": "user", "content": "Say 'pong' and nothing else."}],
            max_tokens=10,
            tenant_id=str(tenant_id),
        ):
            if delta["type"] == "text":
                output.append(delta["content"])
        result: JSONResponse | dict = {
            "status": "ok",
            "response": "".join(output).strip(),
            "provider": provider.name,
        }
        status_code = 200
    except Exception:
        status_code = status.HTTP_502_BAD_GATEWAY
        result = JSONResponse(
            status_code=status_code,
            content=error_envelope("LLM_PROVIDER_ERROR", "Provider connectivity test failed"),
        )
    await write_audit_log(
        db,
        AuditRecord(
            tenant_id=tenant_id,
            user_id=uuid.UUID(user["user_id"]),
            action="TEST llm-provider",
            resource_type="llm-providers",
            resource_id=str(provider.id),
            method=method,
            path=route_template,
            status_code=status_code,
            details={"provider_id": str(provider.id)},
        ),
    )
    return result


@router.post("/{name}/test")
async def test_provider(
    name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    return await _test_provider(
        name,
        db,
        user,
        method="POST",
        route_template="/api/v1/llm-providers/{name}/test",
    )


@router.get("/test/{name}")
async def test_provider_compat(
    name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    """Compatibility adapter for the previously published test route."""
    return await _test_provider(
        name,
        db,
        user,
        method="GET",
        route_template="/api/v1/llm-providers/test/{name}",
    )


@router.get("/{name}")
async def get_provider(
    name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    return _serialize(await _provider_or_404(db, _tenant_id(user), name))
