"""Sandbox proxy — manages a pool of isolated Docker containers for code execution."""

import base64
import asyncio
import concurrent.futures
import logging
import os
import time
from typing import Optional

import docker
from docker.models.containers import Container
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROXY_AUTH_TOKEN = os.environ.get("PROXY_AUTH_TOKEN", "dev-token")
CONTAINER_IMAGE = "chainless_sandbox:latest"
MAX_EXECUTIONS = 50
MAX_LIFETIME_SECONDS = 600
CONTAINER_MEMORY = "512m"
CONTAINER_CPU_QUOTA = 100000
CONTAINER_CPU_PERIOD = 100000

docker_client = docker.from_env()
_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)

app = FastAPI(title="Chainless Sandbox Proxy")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
# Maps short container id -> docker Container object
_container_objects: dict[str, Container] = {}
# Maps short container id -> metadata dict
_container_meta: dict[str, dict] = {}
# Queue of idle container ids
_pool: asyncio.Queue[str] = asyncio.Queue()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ExecuteRequest(BaseModel):
    script: str
    timeout: int = 30


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
async def verify_token(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization[len("Bearer "):]
    if token != PROXY_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid auth token")
    return token


# ---------------------------------------------------------------------------
# Container lifecycle helpers
# ---------------------------------------------------------------------------
def _create_container() -> str:
    """Create a new sandbox container with security restrictions.

    Returns the short container id (first 12 hex chars).
    """
    container = docker_client.containers.run(
        CONTAINER_IMAGE,
        "sleep infinity",
        mem_limit=CONTAINER_MEMORY,
        cpu_quota=CONTAINER_CPU_QUOTA,
        cpu_period=CONTAINER_CPU_PERIOD,
        network_mode="none",
        read_only=True,
        tmpfs={"/workspace": "size=64m,mode=1777"},
        security_opt=["no-new-privileges:true"],
        detach=True,
    )
    cid = container.id[:12]
    _container_objects[cid] = container
    _container_meta[cid] = {
        "created_at": time.time(),
        "exec_count": 0,
        "allocated_at": None,
    }
    logger.info("Created container %s", cid)
    return cid


def _remove_container(cid: str) -> None:
    """Stop and remove a container, cleaning up all references."""
    container = _container_objects.pop(cid, None)
    _container_meta.pop(cid, None)
    if container is not None:
        try:
            container.stop(timeout=5)
        except Exception:
            pass
        try:
            container.remove(force=True)
        except Exception:
            pass
    logger.info("Removed container %s", cid)


def _is_expired(cid: str) -> bool:
    """Check if a container has exceeded max executions or max lifetime."""
    meta = _container_meta.get(cid)
    if not meta:
        return True
    if meta["exec_count"] >= MAX_EXECUTIONS:
        return True
    if meta["allocated_at"] is not None:
        age = time.time() - meta["allocated_at"]
        if age >= MAX_LIFETIME_SECONDS:
            return True
    return False


async def _warm_pool(target: int = 2) -> None:
    """Create *target* idle containers and add them to the pool."""
    loop = asyncio.get_running_loop()
    current = _pool.qsize()
    needed = max(0, target - current)
    for _ in range(needed):
        try:
            cid = await loop.run_in_executor(_thread_pool, _create_container)
            await _pool.put(cid)
            logger.info("Pool warmed with container %s", cid)
        except Exception as exc:
            logger.error("Failed to warm container: %s", exc)


async def _ping_container(cid: str) -> bool:
    """Quick health check — run ``print('ping')`` inside the container."""
    container = _container_objects.get(cid)
    if not container:
        return False
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _thread_pool,
            lambda: container.exec_run(
                ["python", "-c", "print('ping')"],
                stdout=True, stderr=True,
            ),
        )
        return result.exit_code == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    logger.info("Starting up — warming sandbox pool ...")
    try:
        await _warm_pool(2)
    except Exception as exc:
        logger.warning("Initial pool warm failed (may be transient): %s", exc)
    logger.info("Sandbox proxy ready")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "pool_size": _pool.qsize(),
        "total_containers": len(_container_objects),
    }


# ---------------------------------------------------------------------------
# Container allocation
# ---------------------------------------------------------------------------
@app.post("/containers/allocate")
async def allocate_container(token: str = Depends(verify_token)):
    """Return a healthy container from the pool, or create one if empty.

    Each returned container is marked *allocated* — it should be recycled
    (or deleted) after use.
    """
    # Drain stale or expired pool entries
    while True:
        try:
            cid = _pool.get_nowait()
        except asyncio.QueueEmpty:
            break

        if cid not in _container_objects:
            continue  # stale reference, drop it
        if _is_expired(cid):
            _remove_container(cid)
            continue

        # Health check before handing out
        if await _ping_container(cid):
            _container_meta[cid]["allocated_at"] = time.time()
            _container_meta[cid]["exec_count"] = 0
            return {"container_id": cid}
        else:
            logger.warning("Container %s failed health check, removing", cid)
            _remove_container(cid)

    # Pool exhausted — create a fresh container
    loop = asyncio.get_running_loop()
    try:
        cid = await loop.run_in_executor(_thread_pool, _create_container)
    except Exception as exc:
        logger.error("Failed to create container: %s", exc)
        raise HTTPException(status_code=503, detail=f"Cannot allocate container: {exc}")

    _container_meta[cid]["allocated_at"] = time.time()
    _container_meta[cid]["exec_count"] = 0
    return {"container_id": cid}


# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------
@app.post("/containers/{cid}/execute")
async def execute_script(cid: str, body: ExecuteRequest, token: str = Depends(verify_token)):
    """Write a script to the container and execute it, streaming output as SSE."""
    if cid not in _container_objects:
        raise HTTPException(status_code=404, detail="Container not found")

    container = _container_objects[cid]
    meta = _container_meta[cid]
    loop = asyncio.get_running_loop()
    exec_timeout = body.timeout or 30

    # ---- 1. Write script.py to /workspace via exec_run (put_archive fails on read-only rootfs) ----
    script_bytes = body.script.encode("utf-8")
    encoded = base64.b64encode(script_bytes).decode()

    def _write_script():
        result = container.exec_run(
            ["sh", "-c", f"echo {encoded} | base64 -d > /workspace/script.py"],
            user="root",
        )
        if result.exit_code != 0:
            raise RuntimeError(f"Write failed (exit {result.exit_code}): {result.output}")

    try:
        await loop.run_in_executor(_thread_pool, _write_script)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write script: {exc}")

    # ---- 2. Start execution in background thread ----
    queue: asyncio.Queue[tuple[str, Optional[str]]] = asyncio.Queue()

    def _exec():
        """Blocking: runs docker exec and feeds output chunks into the async queue."""
        try:
            result = container.exec_run(
                ["timeout", str(exec_timeout), "python", "/runner.py"],
                stdout=True, stderr=True, stream=True, demux=True,
            )
            for chunk in result.output:
                if chunk is None:
                    continue
                out, err = chunk
                if out:
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("stdout", out.decode("utf-8", errors="replace"))), loop
                    )
                if err:
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("stderr", err.decode("utf-8", errors="replace"))), loop
                    )
        except Exception as exc:
            asyncio.run_coroutine_threadsafe(
                queue.put(("error", str(exc))), loop
            )
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(("done", None)), loop)

    exec_future = loop.run_in_executor(_thread_pool, _exec)  # fire-and-forget

    meta["exec_count"] += 1

    # ---- 3. SSE streaming response ----
    async def _generate():
        try:
            while True:
                try:
                    event_type, data = await asyncio.wait_for(
                        queue.get(), timeout=exec_timeout + 5,
                    )
                except asyncio.TimeoutError:
                    yield "event: error\ndata: Execution timed out\n\n"
                    break

                if event_type == "done":
                    break
                elif event_type == "error":
                    yield f"event: error\ndata: {data}\n\n"
                else:
                    yield f"data: {data}\n\n"

            yield "event: done\n\n"
        finally:
            if not exec_future.done():
                exec_future.cancel()

    return StreamingResponse(_generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Recycle
# ---------------------------------------------------------------------------
@app.post("/containers/{cid}/recycle")
async def recycle_container(cid: str, token: str = Depends(verify_token)):
    """Clean /workspace and return the container to the idle pool.

    If the container has exceeded its max lifetime or execution count it is
    destroyed and a fresh replacement is created instead.
    """
    if cid not in _container_objects:
        raise HTTPException(status_code=404, detail="Container not found")

    # Expired -> replace with a new one
    if _is_expired(cid):
        _remove_container(cid)
        loop = asyncio.get_running_loop()
        try:
            new_cid = await loop.run_in_executor(_thread_pool, _create_container)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Failed to create replacement: {exc}")
        await _pool.put(new_cid)
        return {"container_id": new_cid, "recycled": True, "expired": True}

    # Clean workspace
    container = _container_objects[cid]
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            _thread_pool,
            lambda: container.exec_run(
                ["rm", "-rf", "/workspace/script.py"],
                stdout=True, stderr=True,
            ),
        )
    except Exception:
        pass

    # Return to pool
    _container_meta[cid]["allocated_at"] = None
    _container_meta[cid]["exec_count"] = 0
    await _pool.put(cid)

    return {"container_id": cid, "recycled": True}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------
@app.delete("/containers/{cid}")
async def delete_container(cid: str, token: str = Depends(verify_token)):
    """Stop and remove a container entirely."""
    if cid not in _container_objects:
        raise HTTPException(status_code=404, detail="Container not found")
    _remove_container(cid)
    return {"container_id": cid, "deleted": True}
