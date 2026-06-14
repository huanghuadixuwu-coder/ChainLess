"""Operational health checks shared by health and metrics endpoints."""

from datetime import datetime, timezone
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from app.config import settings
from app.core.secrets import safe_error_message

WORKER_HEARTBEAT_KEY = "chainless:worker:heartbeat"
WORKER_HEARTBEAT_TTL_SECONDS = 180


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _check_db() -> dict[str, Any]:
    conn = None
    try:
        conn = await asyncpg.connect(dsn=_asyncpg_dsn(), timeout=3)
        await conn.execute("SELECT 1")
        return {"status": "connected"}
    except Exception as exc:
        return {"status": "degraded", "error": safe_error_message(exc, "Database health check")}
    finally:
        if conn is not None:
            await conn.close()


async def _check_redis() -> dict[str, Any]:
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        pong = await client.ping()
        return {"status": "connected" if pong else "degraded"}
    except Exception as exc:
        return {"status": "degraded", "error": safe_error_message(exc, "Redis health check")}
    finally:
        await client.aclose()


async def _check_worker() -> dict[str, Any]:
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await client.get(WORKER_HEARTBEAT_KEY)
        if not raw:
            return {"status": "degraded", "error": "worker heartbeat missing"}

        seen_at = datetime.fromisoformat(raw)
        age_seconds = (datetime.now(timezone.utc) - seen_at).total_seconds()
        if age_seconds > WORKER_HEARTBEAT_TTL_SECONDS:
            return {
                "status": "degraded",
                "last_seen_at": raw,
                "age_seconds": round(age_seconds, 1),
            }
        return {
            "status": "ok",
            "last_seen_at": raw,
            "age_seconds": round(age_seconds, 1),
        }
    except Exception as exc:
        return {"status": "degraded", "error": safe_error_message(exc, "Worker health check")}
    finally:
        await client.aclose()


async def write_worker_heartbeat(redis_client: Any) -> None:
    """Write a bounded heartbeat that health checks can use for worker liveness."""
    await redis_client.set(
        WORKER_HEARTBEAT_KEY,
        datetime.now(timezone.utc).isoformat(),
        ex=WORKER_HEARTBEAT_TTL_SECONDS,
    )


async def collect_operational_health(sandbox_manager: Any | None = None) -> dict[str, Any]:
    """Collect DB, Redis, worker, and sandbox health in one shape."""
    db = await _check_db()
    redis = await _check_redis()
    worker = await _check_worker()

    sandbox = {
        "status": "unavailable",
        "pool_size": 0,
        "total_containers": 0,
    }
    if sandbox_manager is not None:
        try:
            live = await sandbox_manager.get_proxy_health()
            sandbox = {
                "status": "ok",
                "pool_size": int(live.get("pool_size", 0) or 0),
                "total_containers": int(live.get("total_containers", 0) or 0),
            }
        except Exception as exc:
            sandbox = {
                "status": "degraded",
                "pool_size": int(getattr(sandbox_manager, "pool_size", 0) or 0),
                "total_containers": 0,
                "error": safe_error_message(exc, "Sandbox health check"),
            }

    checks = {
        "db": db,
        "redis": redis,
        "worker": worker,
        "sandbox": sandbox,
    }
    overall = "ok" if all(
        item.get("status") in ("ok", "connected") for item in checks.values()
    ) else "degraded"

    return {
        "status": overall,
        "db": db["status"],
        "redis": redis["status"],
        "worker": worker["status"],
        "sandbox_pool": sandbox["pool_size"],
        "checks": checks,
    }
