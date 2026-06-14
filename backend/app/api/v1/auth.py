"""Authentication endpoints: register, login, refresh, me."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, auth_error
from app.api.deps import get_current_user, get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_service import (
    create_access_token,
    hash_password,
    verify_password,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class _RegisterRequest(BaseModel):
    tenant_name: str
    username: str
    password: str


class _LoginRequest(BaseModel):
    tenant_name: str
    username: str
    password: str


class _TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@auth_router.post("/register", response_model=_TokenResponse)
async def register(
    body: _RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new tenant and user, returning a JWT access token."""
    # Look up or create tenant
    result = await db.execute(select(Tenant).where(Tenant.name == body.tenant_name))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name=body.tenant_name)
        db.add(tenant)
        await db.flush()

    # Check for duplicate username within the tenant
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant.id, User.username == body.username
        )
    )
    if result.scalar_one_or_none() is not None:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "VALIDATION_ERROR",
            "Username already exists in this tenant",
        )

    user = User(
        tenant_id=tenant.id,
        username=body.username,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    request.state.audit_tenant_id = tenant.id
    request.state.audit_user_id = user.id

    token = create_access_token(
        tenant_id=tenant.id, user_id=user.id, username=user.username
    )
    return _TokenResponse(access_token=token, token_type="bearer")


@auth_router.post("/login")
async def login(
    body: _LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a user and return a JWT access token."""
    # Find tenant
    result = await db.execute(select(Tenant).where(Tenant.name == body.tenant_name))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise auth_error()
    request.state.audit_tenant_id = tenant.id

    # Find user
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant.id, User.username == body.username
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise auth_error()
    request.state.audit_user_id = user.id
    if (user.preferences or {}).get("disabled") is True:
        raise auth_error()

    token = create_access_token(
        tenant_id=tenant.id, user_id=user.id, username=user.username
    )
    return _TokenResponse(access_token=token, token_type="bearer")


@auth_router.post("/refresh", response_model=_TokenResponse)
async def refresh(
    current_user: dict = Depends(get_current_user),
):
    """Refresh a valid JWT access token.

    v1 keeps the refresh flow simple: an authenticated caller exchanges the
    current bearer token for a new access token with a fresh expiry.
    """
    token = create_access_token(
        tenant_id=current_user["tenant_id"],
        user_id=current_user["user_id"],
        username=current_user["username"],
    )
    return _TokenResponse(access_token=token, token_type="bearer")


@auth_router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    """Return the current authenticated user's info from the JWT."""
    return current_user
