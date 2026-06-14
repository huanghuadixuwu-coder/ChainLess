"""FastAPI dependencies: database session and JWT auth."""

import uuid
import os
from typing import AsyncGenerator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.contracts import api_error, auth_expired
from app.config import settings
from app.models.user import User
from app.services.auth_service import decode_token

security = HTTPBearer(auto_error=False)

_engine_kwargs = {"echo": False}
if os.environ.get("CHAINLESS_TESTING") == "1":
    _engine_kwargs["poolclass"] = NullPool

_engine = create_async_engine(settings.database_url, **_engine_kwargs)
engine = _engine  # public alias for ARQ tasks
_async_session_factory = async_sessionmaker(
    _engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session for the request lifespan.

    The session is automatically closed when the request finishes.
    """
    async with _async_session_factory() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Extract and validate JWT, return current user info dict.

    Returns:
        dict with keys: user_id, tenant_id, username, role
    """
    if credentials is None:
        raise auth_expired("Missing bearer token")

    try:
        payload = decode_token(credentials.credentials)
        user_id = uuid.UUID(str(payload["user_id"]))
        tenant_id = uuid.UUID(str(payload["tenant_id"]))
        username = str(payload["username"])
    except ValueError:
        raise auth_expired("Invalid credentials")
    except (KeyError, TypeError):
        raise auth_expired("Invalid credentials")

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise auth_expired("User no longer exists")
    if (user.preferences or {}).get("disabled") is True:
        raise auth_expired("User is disabled")

    return {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "username": username,
        "role": user.role,
    }


def require_role(*roles: str):
    """Return a dependency that requires the authenticated user to have a role."""

    async def _dependency(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in roles:
            raise api_error(403, "FORBIDDEN", "Insufficient role")
        return current_user

    return _dependency
