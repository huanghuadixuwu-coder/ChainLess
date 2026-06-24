"""Sandbox proxy — manages a pool of isolated Docker containers for code execution."""

import base64
import asyncio
import concurrent.futures
import hashlib
import hmac
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import docker
from docker.models.containers import Container
from docker.types import Mount
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from policy import configured_network_mode, configured_security_options

logger = logging.getLogger("uvicorn.error")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROXY_AUTH_TOKEN = os.environ.get("PROXY_AUTH_TOKEN", "dev-token")
APP_ENV = os.environ.get("APP_ENV", "development").lower()
PROXY_OWNER = os.environ.get("SANDBOX_PROXY_OWNER", "chainless-default")
SANDBOX_IMAGE = os.environ["SANDBOX_IMAGE"]
MAX_EXECUTIONS = 50
MAX_LIFETIME_SECONDS = 600
CONTAINER_MEMORY = "512m"
CONTAINER_CPU_QUOTA = 100000
CONTAINER_CPU_PERIOD = 100000
CONTAINER_PIDS_LIMIT = int(os.environ.get("SANDBOX_PIDS_LIMIT", "128"))
POOL_MIN = int(os.environ.get("SANDBOX_POOL_MIN", "2"))
POOL_MAX = int(os.environ.get("SANDBOX_POOL_MAX", "10"))
MAX_EXECUTION_TIMEOUT = int(os.environ.get("SANDBOX_MAX_TIMEOUT_SECONDS", "60"))
SANDBOX_EXECUTION_MAX_CONCURRENCY = int(
    os.environ.get("SANDBOX_EXECUTION_MAX_CONCURRENCY", "4")
)
DISPOSABLE_PARENT_MAX_CONCURRENCY = int(
    os.environ.get("DISPOSABLE_PARENT_MAX_CONCURRENCY", "5")
)
DISPOSABLE_PARENT_MAX_STDOUT_BYTES = int(
    os.environ.get("DISPOSABLE_PARENT_MAX_STDOUT_BYTES", "262144")
)
DISPOSABLE_PARENT_MAX_STDERR_BYTES = int(
    os.environ.get("DISPOSABLE_PARENT_MAX_STDERR_BYTES", "262144")
)
DISPOSABLE_PARENT_MAX_OUTPUT_BYTES = int(
    os.environ.get("DISPOSABLE_PARENT_MAX_OUTPUT_BYTES", "524288")
)
PARENT_RUN_STATUS_TTL_SECONDS = int(os.environ.get("PARENT_RUN_STATUS_TTL_SECONDS", "300"))
PARENT_RUN_STATUS_MAX_RECORDS = int(os.environ.get("PARENT_RUN_STATUS_MAX_RECORDS", "1000"))
if not 0 < DISPOSABLE_PARENT_MAX_CONCURRENCY <= 5:
    raise RuntimeError("DISPOSABLE_PARENT_MAX_CONCURRENCY must be between 1 and 5")
if not 0 < SANDBOX_EXECUTION_MAX_CONCURRENCY <= 32:
    raise RuntimeError("SANDBOX_EXECUTION_MAX_CONCURRENCY must be between 1 and 32")
if min(
    DISPOSABLE_PARENT_MAX_STDOUT_BYTES,
    DISPOSABLE_PARENT_MAX_STDERR_BYTES,
    DISPOSABLE_PARENT_MAX_OUTPUT_BYTES,
) <= 0:
    raise RuntimeError("Disposable parent output limits must be positive")
if PARENT_RUN_STATUS_TTL_SECONDS <= 0 or PARENT_RUN_STATUS_MAX_RECORDS <= 0:
    raise RuntimeError("Parent run status retention limits must be positive")

docker_client = None
_pool_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
_execution_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=SANDBOX_EXECUTION_MAX_CONCURRENCY
)
_parent_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=DISPOSABLE_PARENT_MAX_CONCURRENCY
)
_control_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
_disposable_parent_slots = asyncio.Semaphore(DISPOSABLE_PARENT_MAX_CONCURRENCY)
_parent_runs: dict[str, "ParentRunState"] = {}

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
# Maps short container id -> docker Container object
_container_objects: dict[str, Container] = {}
# Maps short container id -> metadata dict
_container_meta: dict[str, dict] = {}
# Queue of idle container ids
_pool: asyncio.Queue[str] = asyncio.Queue()
_pooled_ids: set[str] = set()
_pool_maintenance_lock = asyncio.Lock()
MANAGED_LABEL = "chainless.sandbox.managed"
DISPOSABLE_LABEL = "chainless.sandbox.disposable"
PARENT_RUN_LABEL = "chainless.sandbox.parent_run"
OWNER_LABEL = "chainless.sandbox.proxy_owner"
SUBAGENT_CONTROL_VOLUME = os.environ.get(
    "SUBAGENT_CONTROL_VOLUME",
    "chainless_subagent_control",
)
SUBAGENT_CONTROL_GID = int(os.environ.get("SUBAGENT_CONTROL_GID", "10001"))
WORKSPACE_CONNECTOR_VOLUME = os.environ.get("WORKSPACE_CONNECTOR_VOLUME", "").strip()
WORKSPACE_CONNECTOR_VOLUME_SUBPATH_PREFIX = os.environ.get(
    "WORKSPACE_CONNECTOR_VOLUME_SUBPATH_PREFIX",
    "connectors",
).strip()
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_VOLUME_SUBPATH_PART = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_safe_run_id(run_id: object) -> bool:
    return (
        isinstance(run_id, str)
        and run_id not in {".", ".."}
        and _SAFE_RUN_ID.fullmatch(run_id) is not None
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate policy, warm the pool, and remove owned containers on shutdown."""
    if APP_ENV == "production" and PROXY_AUTH_TOKEN in {"", "dev-token", "change-me"}:
        raise RuntimeError("Unsafe production configuration: PROXY_AUTH_TOKEN is not set")
    configured_network_mode()
    logger.info("Starting up - warming sandbox pool ...")
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_control_executor, _cleanup_managed_containers)
        await _warm_pool(POOL_MIN)
    except Exception as exc:
        logger.warning("Initial pool warm failed (may be transient): %s", exc)
    logger.info("Sandbox proxy ready")
    pruner = asyncio.create_task(_parent_run_pruner_loop())
    try:
        yield
    finally:
        pruner.cancel()
        await asyncio.gather(pruner, return_exceptions=True)
        try:
            for cid in list(_container_objects):
                _remove_container(cid)
        finally:
            for executor in (
                _execution_executor,
                _parent_executor,
                _control_executor,
                _pool_executor,
            ):
                executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Chainless Sandbox Proxy", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
_RAW_HOST_MOUNT_KEYS = {
    "host_path",
    "host_paths",
    "host_realpath",
    "host_realpath_hash",
    "raw_host_path",
    "source",
    "src",
    "bind",
}


def _reject_raw_host_path_keys(value: Any) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _RAW_HOST_MOUNT_KEYS:
                raise ValueError("workspace connector mount bundles cannot include raw host paths")
            _reject_raw_host_path_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_raw_host_path_keys(item)
    return value


class ConnectorMountContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str = Field(pattern=r"^wsc_[0-9a-f]{32}$")
    generation: int = Field(ge=1)
    container_mount_path: str = Field(pattern=r"^/workspace/connectors/wsc_[0-9a-f]{32}$")
    backend_mount_path: str = Field(pattern=r"^/workspace/connectors/wsc_[0-9a-f]{32}$")
    sandbox_mount_path: str = Field(pattern=r"^/workspace/connectors/wsc_[0-9a-f]{32}$")
    mode: str = Field(pattern=r"^read_(only|write)$")

    @model_validator(mode="after")
    def mount_paths_match_connector_id(self) -> "ConnectorMountContract":
        expected_path = f"/workspace/connectors/{self.connector_id}"
        if (
            self.container_mount_path != expected_path
            or self.backend_mount_path != expected_path
            or self.sandbox_mount_path != expected_path
        ):
            raise ValueError("workspace connector mount paths must match connector_id")
        return self


class ConnectorMountBundleContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["workspace_connector_mounts.v1"]
    mounts: list[ConnectorMountContract] = Field(default_factory=list, max_length=32)

    @model_validator(mode="before")
    @classmethod
    def reject_raw_host_paths(cls, value: Any) -> Any:
        return _reject_raw_host_path_keys(value)


class ExecuteRequest(BaseModel):
    script: str
    timeout: int = Field(default=30, ge=1, le=MAX_EXECUTION_TIMEOUT)
    mount_bundle: ConnectorMountBundleContract | None = None


class ParentExecuteRequest(ExecuteRequest):
    run_id: str
    capability: str = Field(min_length=20, max_length=512)


class ParentRunControlRequest(BaseModel):
    capability: str = Field(min_length=20, max_length=512)


@dataclass
class ParentRunState:
    run_id: str
    capability: str | None
    capability_digest: bytes = b""
    task: asyncio.Task | None = None
    container: Container | None = None
    cancel_requested: bool = False
    result: dict | None = None
    error: BaseException | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    completed_at: float | None = None


class DisposableParentOutputLimitError(RuntimeError):
    """Raised when a disposable parent exceeds its bounded output budget."""


def _connector_docker_mounts(
    mount_bundle: ConnectorMountBundleContract | None,
) -> list[Mount]:
    """Translate sanitized connector contracts into Docker mounts."""
    if mount_bundle is None:
        return []
    if mount_bundle.mounts and not WORKSPACE_CONNECTOR_VOLUME:
        raise ValueError(
            "WORKSPACE_CONNECTOR_VOLUME must be configured before Workspace Connector "
            "mount bundles can be executed"
        )
    mounts: list[Mount] = []
    seen_targets: set[str] = set()
    for connector_mount in mount_bundle.mounts:
        if connector_mount.sandbox_mount_path in seen_targets:
            raise ValueError("duplicate workspace connector mount target")
        seen_targets.add(connector_mount.sandbox_mount_path)
        mount = Mount(
            target=connector_mount.sandbox_mount_path,
            source=WORKSPACE_CONNECTOR_VOLUME,
            type="volume",
            read_only=connector_mount.mode == "read_only",
        )
        mount.setdefault("VolumeOptions", {})["Subpath"] = _connector_volume_subpath(
            connector_mount.connector_id
        )
        mounts.append(mount)
    return mounts


def _connector_volume_subpath(connector_id: str) -> str:
    """Return the connector's subpath within the shared workspace Docker volume."""
    prefix_parts = [
        part
        for part in WORKSPACE_CONNECTOR_VOLUME_SUBPATH_PREFIX.replace("\\", "/").split("/")
        if part
    ]
    if not prefix_parts:
        raise ValueError("WORKSPACE_CONNECTOR_VOLUME_SUBPATH_PREFIX must not be empty")
    for part in [*prefix_parts, connector_id]:
        if part in {".", ".."} or _SAFE_VOLUME_SUBPATH_PART.fullmatch(part) is None:
            raise ValueError("Workspace Connector volume subpath configuration is invalid")
    return "/".join([*prefix_parts, connector_id])


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
def _get_docker_client():
    """Connect to Docker only when the proxy first needs a container."""
    global docker_client
    if docker_client is None:
        docker_client = docker.from_env()
    return docker_client


def _cleanup_managed_containers() -> None:
    """Remove containers left by a previous proxy process before warming."""
    containers = _get_docker_client().containers.list(
        all=True,
        filters={"label": [f"{MANAGED_LABEL}=true", f"{OWNER_LABEL}={PROXY_OWNER}"]},
    )
    for container in containers:
        try:
            container.remove(force=True)
        except Exception as exc:
            logger.warning("Failed to remove orphaned managed sandbox %s: %s", container.id[:12], exc)


def _create_container() -> str:
    """Create a new sandbox container with security restrictions.

    Returns the short container id (first 12 hex chars).
    """
    if len(_container_objects) >= POOL_MAX:
        raise RuntimeError(f"Sandbox pool limit reached ({POOL_MAX})")

    container = _get_docker_client().containers.run(
        SANDBOX_IMAGE,
        "sleep infinity",
        mem_limit=CONTAINER_MEMORY,
        cpu_quota=CONTAINER_CPU_QUOTA,
        cpu_period=CONTAINER_CPU_PERIOD,
        pids_limit=CONTAINER_PIDS_LIMIT,
        network_mode=configured_network_mode(),
        read_only=True,
        tmpfs={"/workspace": "size=64m,mode=1777"},
        security_opt=configured_security_options(),
        cap_drop=["ALL"],
        labels={MANAGED_LABEL: "true", OWNER_LABEL: PROXY_OWNER},
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


def _create_disposable_parent(
    run_id: str,
    capability: str,
    mount_bundle: ConnectorMountBundleContract | None = None,
) -> Container:
    """Create a run-bound parent sandbox without granting any permission."""
    if not _is_safe_run_id(run_id):
        raise ValueError("invalid parent run id")
    mount = Mount(
        target="/run/chainless",
        source=SUBAGENT_CONTROL_VOLUME,
        type="volume",
        read_only=False,
    )
    mount.setdefault("VolumeOptions", {})["Subpath"] = run_id
    connector_mounts = _connector_docker_mounts(mount_bundle)
    return _get_docker_client().containers.run(
        SANDBOX_IMAGE,
        "sleep infinity",
        mem_limit=CONTAINER_MEMORY,
        cpu_quota=CONTAINER_CPU_QUOTA,
        cpu_period=CONTAINER_CPU_PERIOD,
        pids_limit=CONTAINER_PIDS_LIMIT,
        network_mode="none",
        read_only=True,
        tmpfs={"/workspace": "size=64m,mode=1777"},
        security_opt=configured_security_options(),
        cap_drop=["ALL"],
        group_add=[str(SUBAGENT_CONTROL_GID)],
        labels={
            MANAGED_LABEL: "true",
            DISPOSABLE_LABEL: "true",
            PARENT_RUN_LABEL: run_id,
            OWNER_LABEL: PROXY_OWNER,
        },
        environment={"CHAINLESS_SUBAGENT_CAPABILITY": capability},
        mounts=[mount, *connector_mounts],
        detach=True,
    )


def _cleanup_disposable_parent(container: Container) -> dict:
    """Try every available cleanup action and return an observable outcome."""
    attempts: list[str] = []
    errors: list[str] = []
    deleted = False

    attempts.append("remove")
    try:
        container.remove(force=True)
        deleted = True
    except Exception as exc:
        errors.append(str(exc))

    if not deleted:
        for action in ("stop", "kill"):
            attempts.append(action)
            try:
                if action == "stop":
                    container.stop(timeout=5)
                else:
                    container.kill()
            except Exception as exc:
                errors.append(str(exc))

        attempts.append("remove")
        try:
            container.remove(force=True)
            deleted = True
        except Exception as exc:
            errors.append(str(exc))

    active = _get_docker_client().containers.list(
        all=True,
        filters={"label": [f"{DISPOSABLE_LABEL}=true", f"{OWNER_LABEL}={PROXY_OWNER}"]},
    )
    return {
        "container_id": container.id[:12],
        "deleted": deleted,
        "active_container_ids": [item.id[:12] for item in active],
        "cleanup_attempts": attempts,
        "cleanup_errors": errors,
    }


def _remove_container(cid: str) -> None:
    """Remove a container and clear references only after confirmed success."""
    container = _container_objects.get(cid)
    if container is not None:
        try:
            container.stop(timeout=5)
        except Exception:
            pass
        try:
            container.remove(force=True)
        except docker.errors.NotFound:
            pass
        except Exception as exc:
            logger.error("Failed to remove container %s: %s", cid, exc)
            raise RuntimeError(f"failed to remove container {cid}: {exc}") from exc
        else:
            try:
                _get_docker_client().containers.get(cid)
            except docker.errors.NotFound:
                pass
            except Exception as exc:
                logger.error("Failed to confirm container %s removal: %s", cid, exc)
                raise RuntimeError(
                    f"failed to confirm container {cid} removal: {exc}"
                ) from exc
            else:
                raise RuntimeError(f"container {cid} still exists after removal")
    _pooled_ids.discard(cid)
    _container_objects.pop(cid, None)
    _container_meta.pop(cid, None)
    logger.info("Removed container %s", cid)


def _forget_container_reference(cid: str, reason: str) -> None:
    """Drop proxy state for a container Docker no longer has."""
    _pooled_ids.discard(cid)
    _container_objects.pop(cid, None)
    _container_meta.pop(cid, None)
    logger.warning("Forgot sandbox container %s: %s", cid, reason)


def _container_exists(cid: str) -> bool:
    try:
        _get_docker_client().containers.get(cid)
        return True
    except docker.errors.NotFound:
        return False


def _is_expired(cid: str) -> bool:
    """Check if a container has exceeded max executions or max lifetime."""
    meta = _container_meta.get(cid)
    if not meta:
        return True
    if meta["exec_count"] >= MAX_EXECUTIONS:
        return True
    if time.time() - meta["created_at"] >= MAX_LIFETIME_SECONDS:
        return True
    if meta.get("unhealthy") is True:
        return True
    return False


async def _enqueue_idle(cid: str) -> None:
    """Put one valid container into the idle queue at most once."""
    if cid not in _container_objects or cid in _pooled_ids:
        return
    if len(_pooled_ids) >= POOL_MAX:
        _remove_container(cid)
        return
    _pooled_ids.add(cid)
    await _pool.put(cid)


def _idle_pool_target() -> int:
    return max(0, min(POOL_MIN, POOL_MAX))


def _trim_idle_pool_to_target_unlocked() -> list[str]:
    """Remove surplus idle containers while keeping the configured warm pool."""
    target = _idle_pool_target()
    trimmed: list[str] = []
    _compact_pool()
    while len(_pooled_ids) > target:
        try:
            cid = _pool.get_nowait()
        except asyncio.QueueEmpty:
            break
        if cid not in _pooled_ids:
            continue
        _pooled_ids.discard(cid)
        try:
            _remove_container(cid)
            trimmed.append(cid)
        except Exception as exc:
            logger.warning("Failed to trim surplus idle container %s: %s", cid, exc)
    _compact_pool()
    return trimmed


async def _return_recycled_container(cid: str) -> bool:
    """Return an allocated container to idle, or delete it if idle pool is full."""
    async with _pool_maintenance_lock:
        _compact_pool()
        if len(_pooled_ids) >= _idle_pool_target():
            _remove_container(cid)
            return True
        await _enqueue_idle(cid)
        return False


def _compact_pool() -> None:
    """Drop stale or duplicate queue entries left by removed containers."""
    retained: list[str] = []
    seen: set[str] = set()
    while True:
        try:
            cid = _pool.get_nowait()
        except asyncio.QueueEmpty:
            break
        if cid in _container_objects and cid in _pooled_ids and cid not in seen:
            retained.append(cid)
            seen.add(cid)
    _pooled_ids.intersection_update(seen)
    for cid in retained:
        _pool.put_nowait(cid)


async def _warm_pool(target: int = POOL_MIN) -> None:
    """Ensure at least *target* total managed containers exist."""
    async with _pool_maintenance_lock:
        _compact_pool()
        loop = asyncio.get_running_loop()
        current = len(_container_objects)
        needed = max(0, min(target, POOL_MAX) - current)
        for _ in range(needed):
            try:
                cid = await loop.run_in_executor(_pool_executor, _create_container)
                await _enqueue_idle(cid)
                logger.info("Pool warmed with container %s", cid)
            except Exception as exc:
                logger.error("Failed to warm container: %s", exc)


async def _reconcile_pool_state() -> None:
    """Prune stale, expired, or unresponsive containers before reporting health."""
    async with _pool_maintenance_lock:
        _compact_pool()
        loop = asyncio.get_running_loop()
        for cid in list(_container_objects):
            exists = await loop.run_in_executor(
                _control_executor,
                lambda cid=cid: _container_exists(cid),
            )
            if not exists:
                _forget_container_reference(cid, "missing from Docker")
                continue
            if _is_expired(cid):
                try:
                    _remove_container(cid)
                except Exception as exc:
                    logger.warning("Failed to remove expired container %s: %s", cid, exc)
                    _forget_container_reference(cid, "expired")
                continue
            if await _ping_container(cid):
                continue
            logger.warning("Container %s failed health check during reconciliation", cid)
            try:
                _remove_container(cid)
            except Exception as exc:
                logger.warning("Failed to remove unresponsive container %s: %s", cid, exc)
                _forget_container_reference(cid, "unresponsive")
        trimmed = _trim_idle_pool_to_target_unlocked()
        if trimmed:
            logger.info("Trimmed surplus idle containers: %s", ", ".join(trimmed))
        _compact_pool()


async def _ping_container(cid: str) -> bool:
    """Quick health check — run ``print('ping')`` inside the container."""
    container = _container_objects.get(cid)
    if not container:
        return False
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _pool_executor,
            lambda: container.exec_run(
                ["python", "-c", "print('ping')"],
                stdout=True, stderr=True,
            ),
        )
        return result.exit_code == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    await _reconcile_pool_state()
    await _warm_pool(POOL_MIN)
    return {
        "status": "ok",
        "pool_size": len(_pooled_ids),
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
            _pooled_ids.discard(cid)
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
            await _warm_pool(POOL_MIN)
            return {"container_id": cid}
        else:
            logger.warning("Container %s failed health check, removing", cid)
            _remove_container(cid)

    # Pool exhausted — create a fresh container
    loop = asyncio.get_running_loop()
    try:
        cid = await loop.run_in_executor(_pool_executor, _create_container)
    except Exception as exc:
        logger.error("Failed to create container: %s", exc)
        raise HTTPException(status_code=503, detail=f"Cannot allocate container: {exc}")

    _container_meta[cid]["allocated_at"] = time.time()
    _container_meta[cid]["exec_count"] = 0
    await _warm_pool(POOL_MIN)
    return {"container_id": cid}


# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------
@app.post("/containers/{cid}/execute")
async def execute_script(cid: str, body: ExecuteRequest, token: str = Depends(verify_token)):
    """Write a script to the container and execute it, streaming output as SSE."""
    if body.mount_bundle is not None and body.mount_bundle.mounts:
        raise HTTPException(
            status_code=400,
            detail="Workspace Connector mounts require disposable parent execution",
        )
    if cid not in _container_objects:
        raise HTTPException(status_code=404, detail="Container not found")

    container = _container_objects[cid]
    meta = _container_meta[cid]
    loop = asyncio.get_running_loop()
    exec_timeout = min(body.timeout or 30, MAX_EXECUTION_TIMEOUT)

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
        await loop.run_in_executor(_pool_executor, _write_script)
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

    exec_future = loop.run_in_executor(_execution_executor, _exec)  # fire-and-forget

    meta["exec_count"] += 1

    # ---- 3. SSE streaming response ----
    async def _generate():
        timed_out = False
        try:
            while True:
                try:
                    event_type, data = await asyncio.wait_for(
                        queue.get(), timeout=exec_timeout + 5,
                    )
                except asyncio.TimeoutError:
                    timed_out = True
                    meta["unhealthy"] = True
                    yield "event: error\ndata: Execution timed out\n\n"
                    break

                if event_type == "done":
                    break
                elif event_type == "error":
                    yield f"event: error\ndata: {data}\n\n"
                else:
                    yield f"data: {data}\n\n"

            yield "event: done\n\n"
        except asyncio.CancelledError:
            meta["unhealthy"] = True
            raise
        finally:
            if not exec_future.done():
                exec_future.cancel()
            if timed_out:
                logger.warning("Container %s marked unhealthy after timeout", cid)

    return StreamingResponse(_generate(), media_type="text/event-stream")


@app.post("/parent-runs/execute")
async def execute_disposable_parent(
    body: ParentExecuteRequest,
    token: str = Depends(verify_token),
):
    """Create, execute, and always delete one run-bound parent sandbox."""
    if _disposable_parent_slots.locked():
        raise HTTPException(
            status_code=503,
            detail="Disposable parent concurrency limit reached",
        )
    await _disposable_parent_slots.acquire()
    try:
        _prune_parent_runs()
        if body.run_id in _parent_runs:
            raise HTTPException(status_code=409, detail="Parent run id already exists")
        state = ParentRunState(
            run_id=body.run_id,
            capability=body.capability,
            capability_digest=_capability_digest(body.capability),
        )
        state.task = asyncio.create_task(_own_disposable_parent_lifecycle(body, state))
        _parent_runs[body.run_id] = state
        return await _await_disposable_parent_lifecycle(state)
    finally:
        _disposable_parent_slots.release()


@app.post("/parent-runs/{run_id}/cancel")
async def cancel_disposable_parent(
    run_id: str,
    body: ParentRunControlRequest,
    token: str = Depends(verify_token),
):
    """Request cancellation and return only after authoritative deletion."""
    state = _authorize_parent_run(run_id, body.capability)
    state.cancel_requested = True
    if state.container is not None and not state.done.is_set():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            _control_executor,
            lambda: _interrupt_disposable_parent(state.container),
        )
    await _await_parent_run_done(state)
    return _terminal_parent_run_status(state)


@app.post("/parent-runs/{run_id}/status")
async def get_disposable_parent_status(
    run_id: str,
    body: ParentRunControlRequest,
    token: str = Depends(verify_token),
):
    """Return run-scoped parent status without exposing another run."""
    state = _authorize_parent_run(run_id, body.capability)
    if not state.done.is_set():
        return {
            "run_id": run_id,
            "status": "cancelling" if state.cancel_requested else "running",
            "deleted": False,
        }
    return _terminal_parent_run_status(state)


def _authorize_parent_run(run_id: str, capability: str) -> ParentRunState:
    state = _parent_runs.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Parent run not found")
    if not hmac.compare_digest(state.capability_digest, _capability_digest(capability)):
        raise HTTPException(status_code=403, detail="Parent run capability rejected")
    return state


def _prune_parent_runs() -> None:
    cutoff = time.monotonic() - PARENT_RUN_STATUS_TTL_SECONDS
    for run_id, state in list(_parent_runs.items()):
        if state.completed_at is not None and state.completed_at < cutoff:
            _parent_runs.pop(run_id, None)
    completed = sorted(
        (state for state in _parent_runs.values() if state.completed_at is not None),
        key=lambda state: state.completed_at or 0,
    )
    overflow = max(0, len(completed) - PARENT_RUN_STATUS_MAX_RECORDS)
    for state in completed[:overflow]:
        _parent_runs.pop(state.run_id, None)


async def _parent_run_pruner_loop() -> None:
    while True:
        await asyncio.sleep(min(PARENT_RUN_STATUS_TTL_SECONDS, 60))
        _prune_parent_runs()


def _capability_digest(capability: str) -> bytes:
    return hashlib.sha256(capability.encode("utf-8")).digest()


def _compact_parent_run_state(state: ParentRunState) -> None:
    result = state.result or {}
    proof_keys = (
        "container_id",
        "deleted",
        "active_container_ids",
        "cleanup_attempts",
        "cleanup_errors",
        "cancelled",
        "execution_failed",
        "exit_code",
    )
    state.result = {key: result[key] for key in proof_keys if key in result} or None
    state.task = None
    state.container = None
    state.capability = None
    state.error = None


async def _own_disposable_parent_lifecycle(
    body: ParentExecuteRequest,
    state: ParentRunState,
) -> dict:
    try:
        state.result = await _execute_disposable_parent_bounded(body, state)
        return state.result
    except BaseException as exc:
        state.error = exc
        raise
    finally:
        state.completed_at = time.monotonic()
        state.done.set()
        _compact_parent_run_state(state)
        _prune_parent_runs()


async def _await_disposable_parent_lifecycle(state: ParentRunState) -> dict:
    """Propagate cancellation only after authoritative create and cleanup finish."""
    lifecycle = state.task
    assert lifecycle is not None
    cancellation: asyncio.CancelledError | None = None
    while not lifecycle.done():
        try:
            await asyncio.shield(lifecycle)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
        except BaseException:
            pass
    try:
        result = lifecycle.result()
    except BaseException:
        if cancellation is not None:
            raise cancellation
        raise
    if cancellation is not None:
        raise cancellation
    return result


async def _await_parent_run_done(state: ParentRunState) -> None:
    waiter = asyncio.create_task(state.done.wait())
    cancellation: asyncio.CancelledError | None = None
    while not waiter.done():
        try:
            await asyncio.shield(waiter)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
    if cancellation is not None:
        raise cancellation


def _terminal_parent_run_status(state: ParentRunState) -> dict:
    if state.result is not None:
        status = "deleted" if _parent_cleanup_confirmed(state.result) else "cleanup_failed"
        return {"run_id": state.run_id, "status": status, **state.result}
    if isinstance(state.error, HTTPException):
        raise state.error
    raise HTTPException(status_code=500, detail="Parent run ended without cleanup proof")


def _parent_cleanup_confirmed(result: dict) -> bool:
    container_id = result.get("container_id")
    return (
        result.get("deleted") is True
        and isinstance(container_id, str)
        and bool(container_id)
        and result.get("cleanup_errors") == []
        and isinstance(result.get("active_container_ids"), list)
        and container_id not in result["active_container_ids"]
    )


def _interrupt_disposable_parent(container: Container) -> None:
    """Best-effort interruption; lifecycle cleanup remains authoritative."""
    for action in ("stop", "kill"):
        try:
            if action == "stop":
                container.stop(timeout=1)
            else:
                container.kill()
            return
        except Exception as exc:
            logger.warning(
                "Failed to %s disposable parent %s: %s",
                action,
                container.id[:12],
                exc,
            )


async def _execute_disposable_parent_bounded(
    body: ParentExecuteRequest,
    state: ParentRunState | None = None,
) -> dict:
    """Execute one disposable parent with bounded capture and forced cleanup."""
    loop = asyncio.get_running_loop()
    container: Container | None = None
    execution_error: HTTPException | None = None
    cleanup: dict | None = None
    exit_code = 130
    stdout = b""
    stderr = b""
    logger.info("Disposable parent run started run_id=%s", body.run_id)
    try:
        container = await loop.run_in_executor(
            _parent_executor,
            lambda: _create_disposable_parent(
                body.run_id,
                body.capability,
                body.mount_bundle,
            ),
        )
        if state is not None:
            state.container = container
        if state is not None and state.cancel_requested:
            raise HTTPException(status_code=409, detail="Parent run cancelled")
        encoded = base64.b64encode(body.script.encode("utf-8")).decode()

        def _execute():
            write = container.exec_run(
                ["sh", "-c", f"echo {encoded} | base64 -d > /workspace/script.py"],
                user="root",
            )
            if write.exit_code != 0:
                raise RuntimeError(f"failed to write parent script: {write.output!r}")
            result = container.exec_run(
                ["timeout", str(body.timeout), "python", "/runner.py"],
                stdout=True,
                stderr=True,
                stream=True,
                demux=True,
            )
            stdout = bytearray()
            stderr = bytearray()
            for chunk in result.output:
                if chunk is None:
                    continue
                out, err = chunk
                if out:
                    stdout.extend(out)
                if err:
                    stderr.extend(err)
                if (
                    len(stdout) > DISPOSABLE_PARENT_MAX_STDOUT_BYTES
                    or len(stderr) > DISPOSABLE_PARENT_MAX_STDERR_BYTES
                    or len(stdout) + len(stderr) > DISPOSABLE_PARENT_MAX_OUTPUT_BYTES
                ):
                    raise DisposableParentOutputLimitError
            return result.exit_code if isinstance(result.exit_code, int) else 0, bytes(stdout), bytes(stderr)

        exit_code, stdout, stderr = await loop.run_in_executor(_parent_executor, _execute)
        container_id = container.id[:12]
    except ValueError as exc:
        execution_error = HTTPException(status_code=400, detail=str(exc))
    except DisposableParentOutputLimitError:
        execution_error = HTTPException(
            status_code=413,
            detail="Disposable parent output limit exceeded",
        )
    except HTTPException as exc:
        execution_error = exc
    except Exception as exc:
        logger.exception("Disposable parent execution failed")
        execution_error = HTTPException(
            status_code=500,
            detail="Disposable parent execution failed",
        )
    finally:
        if container is not None:
            cleanup = await loop.run_in_executor(
                _control_executor,
                lambda: _cleanup_disposable_parent(container),
            )

    if cleanup is not None and (
        cleanup["cleanup_errors"]
        or cleanup["deleted"] is not True
        or cleanup["container_id"] in cleanup["active_container_ids"]
    ):
        if state is not None:
            state.result = cleanup
        logger.error("Disposable parent cleanup failed: %s", cleanup)
        raise HTTPException(
            status_code=500,
            detail={"error": "disposable parent cleanup failed", **cleanup},
        )
    if execution_error is not None:
        if state is not None and cleanup is not None:
            state.result = {
                **cleanup,
                "execution_failed": True,
                "exit_code": exit_code,
                "stdout": (stdout or b"").decode("utf-8", errors="replace"),
                "stderr": (stderr or b"").decode("utf-8", errors="replace"),
            }
        if state is not None and state.cancel_requested and cleanup is not None:
            return {
                **cleanup,
                "cancelled": True,
                "exit_code": exit_code,
                "stdout": (stdout or b"").decode("utf-8", errors="replace"),
                "stderr": (stderr or b"").decode("utf-8", errors="replace"),
            }
        raise execution_error
    if cleanup is None:
        raise HTTPException(status_code=500, detail="Disposable parent cleanup not attempted")

    logger.info(
        "Disposable parent run completed and deleted run_id=%s container_id=%s exit_code=%s",
        body.run_id,
        cleanup["container_id"],
        exit_code,
    )
    return {
        **cleanup,
        "exit_code": exit_code,
        "stdout": (stdout or b"").decode("utf-8", errors="replace"),
        "stderr": (stderr or b"").decode("utf-8", errors="replace"),
    }


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
    if cid in _pooled_ids:
        return {
            "container_id": cid,
            "recycled": True,
            "already_pooled": True,
            "trimmed": False,
        }

    # Expired -> replace with a new one
    if _is_expired(cid):
        _remove_container(cid)
        loop = asyncio.get_running_loop()
        try:
            new_cid = await loop.run_in_executor(_pool_executor, _create_container)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Failed to create replacement: {exc}")
        await _enqueue_idle(new_cid)
        return {"container_id": new_cid, "recycled": True, "expired": True}

    # Clean workspace
    container = _container_objects[cid]
    loop = asyncio.get_running_loop()
    cleanup = None
    try:
        cleanup = await loop.run_in_executor(
            _control_executor,
            lambda: container.exec_run(
                [
                    "sh",
                    "-c",
                    "rm -rf /workspace/* /workspace/.[!.]* /workspace/..?*",
                ],
                stdout=True, stderr=True,
                user="root",
            ),
        )
    except Exception as exc:
        logger.warning("Workspace cleanup failed for %s: %s", cid, exc)

    if cleanup is None or cleanup.exit_code != 0:
        try:
            _remove_container(cid)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Workspace cleanup failed and dirty container removal failed: {exc}",
            ) from exc
        try:
            new_cid = await loop.run_in_executor(_pool_executor, _create_container)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Workspace cleanup failed and replacement could not be created: {exc}",
            )
        await _enqueue_idle(new_cid)
        return {
            "container_id": new_cid,
            "recycled": True,
            "replaced_dirty": True,
        }

    # Return to pool
    _container_meta[cid]["allocated_at"] = None
    _container_meta[cid]["exec_count"] = 0
    trimmed = await _return_recycled_container(cid)

    return {"container_id": cid, "recycled": True, "trimmed": trimmed}


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
