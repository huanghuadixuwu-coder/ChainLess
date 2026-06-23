import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command

from app.config import settings, validate_production_settings
from app.core.llm.gateway import LLMGateway
from app.core.sandbox.manager import SandboxManager
from app.middleware.audit import AuditMiddleware

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------

class AppState:
    def __init__(self) -> None:
        self.llm_gateway: Optional[LLMGateway] = None
        self.sandbox_manager: Optional[SandboxManager] = None
        self.redis: Optional["redis.asyncio.Redis"] = None  # type: ignore[name-defined]


app_state = AppState()


# ---------------------------------------------------------------------------
# Migration helper
# ---------------------------------------------------------------------------

def _run_migrations_sync() -> None:
    """Synchronous wrapper for alembic ``upgrade head``.

    Runs in a thread pool via ``asyncio.loop.run_in_executor`` so the
    nested ``asyncio.run()`` inside alembic's ``env.py`` does not
    conflict with the lifespan's running event loop.
    """
    alembic_cfg = AlembicConfig("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    alembic_command.upgrade(alembic_cfg, "head")


async def run_migrations() -> None:
    """Run database migrations in a thread pool."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_migrations_sync)


async def recover_mcp_servers_on_startup() -> None:
    """Reload durable MCP server configs without failing app startup."""
    try:
        from app.api.deps import _async_session_factory
        from app.core.tools.mcp.manager import mcp_manager

        async with _async_session_factory() as db:
            result = await mcp_manager.recover_enabled_from_db(db)
        logger.info(
            "Recovered %d durable MCP server configuration(s); %d failed",
            result.recovered,
            result.failed,
        )
    except Exception:
        logger.exception("Failed to recover durable MCP server configurations on startup")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle handler."""
    # ---- startup ----
    logger.info("Starting Chainless Backend")
    validate_production_settings(settings)

    # Note: Migrations already run by startup.sh before uvicorn starts.
    # Running them again here would cause event-loop deadlock with async Alembic.

    # Initialize LLM gateway
    app_state.llm_gateway = LLMGateway()

    # Initialize sandbox pool
    app_state.sandbox_manager = SandboxManager(settings)
    try:
        await app_state.sandbox_manager.warm_pool()
    except Exception as exc:
        logger.warning("Could not warm sandbox pool: %s", exc)

    await recover_mcp_servers_on_startup()

    yield

    # ---- shutdown ----
    logger.info("Shutting down Chainless Backend")
    if app_state.sandbox_manager is not None:
        await app_state.sandbox_manager.close()
    if app_state.redis is not None:
        await app_state.redis.aclose()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Chainless Backend",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow all origins during development
def _cors_origins() -> list[str]:
    if settings.app_env.lower() == "production":
        return []
    return [origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
if settings.rate_limit_enabled:
    import redis.asyncio as aioredis  # type: ignore[import-untyped]

    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    app_state.redis = _redis  # for cleanup on shutdown
    from app.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(
        RateLimitMiddleware,
        redis=_redis,
        limit=settings.rate_limit_per_minute,
        window_seconds=60,
    )
    logger.info(
        "Rate limiting enabled: %d requests/min", settings.rate_limit_per_minute
    )

# Error handlers (must be registered after middleware so they wrap everything)
from app.middleware.error_handler import register_error_handlers

register_error_handlers(app)


from app.api.v1.router import api_router  # type: ignore[import-untyped]

app.include_router(api_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

@app.get("/api/v1/health")
async def health():
    """Public liveness endpoint for container and reverse-proxy probes."""
    return {"status": "ok"}


@app.get("/health")
async def root_health():
    """Short alias for infrastructure liveness checks."""
    return {"status": "ok"}
