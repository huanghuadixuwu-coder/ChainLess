"""FastAPI dependencies: database session and JWT auth."""

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.services.auth_service import decode_token

security = HTTPBearer()

_engine = create_async_engine(settings.database_url, echo=False)
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
    credentials=Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Extract and validate JWT, return current user info dict.

    Returns:
        dict with keys: user_id, tenant_id, username
    """
    try:
        payload = decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_EXPIRED", "message": "Invalid credentials"},
        )
    return {
        "user_id": payload["user_id"],
        "tenant_id": payload["tenant_id"],
        "username": payload["username"],
    }
