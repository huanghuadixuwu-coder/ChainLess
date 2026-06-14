"""System endpoints beyond the top-level health route."""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app.api.deps import require_role
from app.config import settings
from app.core.ops.health import collect_operational_health
from app.core.sandbox.manager import SandboxManager, get_sandbox_manager

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
async def system_health(
    _current_user: dict = Depends(require_role("admin")),
    sandbox_manager: SandboxManager = Depends(get_sandbox_manager),
):
    """Return detailed operational health for the admin Settings surface."""
    return await collect_operational_health(sandbox_manager)


@router.get("/metrics", response_class=PlainTextResponse)
async def system_metrics(
    _current_user: dict = Depends(require_role("admin")),
    sandbox_manager: SandboxManager = Depends(get_sandbox_manager),
):
    """Expose lightweight Prometheus-style metrics for v1."""
    health = await collect_operational_health(sandbox_manager)
    checks = health["checks"]
    sandbox = checks["sandbox"]
    db_up = 1 if checks["db"]["status"] == "connected" else 0
    redis_up = 1 if checks["redis"]["status"] == "connected" else 0
    worker_up = 1 if checks["worker"]["status"] == "ok" else 0
    sandbox_up = 1 if sandbox["status"] == "ok" else 0
    pool_size = int(sandbox.get("pool_size", 0))
    total_containers = int(sandbox.get("total_containers", 0))

    lines = [
        "# HELP chainless_db_up Database health status.",
        "# TYPE chainless_db_up gauge",
        f"chainless_db_up {db_up}",
        "# HELP chainless_redis_up Redis health status.",
        "# TYPE chainless_redis_up gauge",
        f"chainless_redis_up {redis_up}",
        "# HELP chainless_worker_up Background worker heartbeat status.",
        "# TYPE chainless_worker_up gauge",
        f"chainless_worker_up {worker_up}",
        "# HELP chainless_sandbox_up Sandbox proxy health status.",
        "# TYPE chainless_sandbox_up gauge",
        f"chainless_sandbox_up {sandbox_up}",
        "# HELP chainless_sandbox_pool_size Number of warm containers in the sandbox pool.",
        "# TYPE chainless_sandbox_pool_size gauge",
        f"chainless_sandbox_pool_size {pool_size}",
        "# HELP chainless_sandbox_total_containers Total containers reported by sandbox proxy.",
        "# TYPE chainless_sandbox_total_containers gauge",
        f"chainless_sandbox_total_containers {total_containers}",
        "# HELP chainless_rate_limit_enabled Whether HTTP rate limiting is enabled.",
        "# TYPE chainless_rate_limit_enabled gauge",
        f"chainless_rate_limit_enabled {1 if settings.rate_limit_enabled else 0}",
        "# HELP chainless_rate_limit_per_minute HTTP requests allowed per minute.",
        "# TYPE chainless_rate_limit_per_minute gauge",
        f"chainless_rate_limit_per_minute {settings.rate_limit_per_minute}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n")
