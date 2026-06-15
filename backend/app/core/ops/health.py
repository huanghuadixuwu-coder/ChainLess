"""Operational health checks shared by health and metrics endpoints."""

import asyncio
from datetime import datetime, timezone
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from app.config import settings
from app.core.secrets import safe_error_message

WORKER_HEARTBEAT_KEY = "chainless:worker:heartbeat"
WORKER_HEARTBEAT_TTL_SECONDS = 180
DB_HEALTH_BUDGET_SECONDS = 0.7
SANDBOX_HEALTH_BUDGET_SECONDS = 0.6
_db_pool: asyncpg.Pool | None = None
_db_pool_dsn = ""
_db_pool_loop: asyncio.AbstractEventLoop | None = None
_db_pool_lock = asyncio.Lock()
_redis_client: aioredis.Redis | None = None
_redis_client_url = ""
_redis_client_loop: asyncio.AbstractEventLoop | None = None
_redis_client_lock = asyncio.Lock()


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _check_db() -> dict[str, Any]:
    try:
        pool = await _get_db_pool()
        async with pool.acquire(timeout=DB_HEALTH_BUDGET_SECONDS) as conn:
            await asyncio.wait_for(
                conn.execute("SELECT 1"),
                timeout=DB_HEALTH_BUDGET_SECONDS,
            )
        return {"status": "connected"}
    except Exception as exc:
        await _reset_db_pool()
        return {"status": "degraded", "error": safe_error_message(exc, "Database health check")}


async def _get_db_pool() -> asyncpg.Pool:
    global _db_pool, _db_pool_dsn, _db_pool_loop
    dsn = _asyncpg_dsn()
    loop = asyncio.get_running_loop()
    if _db_pool is not None and _db_pool_dsn == dsn and _db_pool_loop is loop:
        return _db_pool
    async with _db_pool_lock:
        if _db_pool is not None and _db_pool_dsn == dsn and _db_pool_loop is loop:
            return _db_pool
        if _db_pool is not None:
            if _db_pool_loop is loop:
                await _db_pool.close()
            else:
                _db_pool.terminate()
        _db_pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=1,
            max_size=1,
            timeout=DB_HEALTH_BUDGET_SECONDS,
        )
        _db_pool_dsn = dsn
        _db_pool_loop = loop
        return _db_pool


async def _reset_db_pool() -> None:
    global _db_pool, _db_pool_dsn, _db_pool_loop
    if _db_pool is None:
        return
    pool = _db_pool
    _db_pool = None
    _db_pool_dsn = ""
    pool_loop = _db_pool_loop
    _db_pool_loop = None
    try:
        if pool_loop is asyncio.get_running_loop():
            await pool.close()
        else:
            pool.terminate()
    except Exception:
        pass


async def _check_redis() -> dict[str, Any]:
    try:
        client = await _get_redis_client()
        pong = await client.ping()
        return {"status": "connected" if pong else "degraded"}
    except Exception as exc:
        await _reset_redis_client()
        return {"status": "degraded", "error": safe_error_message(exc, "Redis health check")}


async def _check_worker() -> dict[str, Any]:
    try:
        client = await _get_redis_client()
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
        await _reset_redis_client()
        return {"status": "degraded", "error": safe_error_message(exc, "Worker health check")}


async def _get_redis_client() -> aioredis.Redis:
    global _redis_client, _redis_client_url, _redis_client_loop
    loop = asyncio.get_running_loop()
    if (
        _redis_client is not None
        and _redis_client_url == settings.redis_url
        and _redis_client_loop is loop
    ):
        return _redis_client
    async with _redis_client_lock:
        if (
            _redis_client is not None
            and _redis_client_url == settings.redis_url
            and _redis_client_loop is loop
        ):
            return _redis_client
        if _redis_client is not None:
            await _redis_client.aclose()
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        _redis_client_url = settings.redis_url
        _redis_client_loop = loop
        return _redis_client


async def _reset_redis_client() -> None:
    global _redis_client, _redis_client_url, _redis_client_loop
    if _redis_client is None:
        return
    client = _redis_client
    _redis_client = None
    _redis_client_url = ""
    _redis_client_loop = None
    try:
        await client.aclose()
    except Exception:
        pass


async def write_worker_heartbeat(redis_client: Any) -> None:
    """Write a bounded heartbeat that health checks can use for worker liveness."""
    await redis_client.set(
        WORKER_HEARTBEAT_KEY,
        datetime.now(timezone.utc).isoformat(),
        ex=WORKER_HEARTBEAT_TTL_SECONDS,
    )


async def collect_operational_health(sandbox_manager: Any | None = None) -> dict[str, Any]:
    """Collect DB, Redis, worker, and sandbox health in one shape."""
    db, redis, worker, sandbox = await asyncio.gather(
        _check_db(),
        _check_redis(),
        _check_worker(),
        _check_sandbox(sandbox_manager),
    )

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


async def _check_sandbox(sandbox_manager: Any | None = None) -> dict[str, Any]:
    sandbox = {
        "status": "unavailable",
        "pool_size": 0,
        "total_containers": 0,
    }
    if sandbox_manager is None:
        return sandbox
    try:
        live = await asyncio.wait_for(
            sandbox_manager.get_proxy_health(),
            timeout=SANDBOX_HEALTH_BUDGET_SECONDS,
        )
        return {
            "status": "ok",
            "pool_size": int(live.get("pool_size", 0) or 0),
            "total_containers": int(live.get("total_containers", 0) or 0),
        }
    except Exception as exc:
        return {
            "status": "degraded",
            "pool_size": int(getattr(sandbox_manager, "pool_size", 0) or 0),
            "total_containers": 0,
            "error": safe_error_message(exc, "Sandbox health check"),
        }
