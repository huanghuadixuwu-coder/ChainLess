"""Sandbox pool lifecycle and bounding tests."""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import sys
import threading
from pathlib import Path

import pytest
from docker.errors import NotFound

pytestmark = pytest.mark.asyncio


class ExecResult:
    exit_code = 0
    output = b"ping\n"


class FailedExecResult:
    exit_code = 1
    output = b""


class FakeContainer:
    def __init__(self, cid: str) -> None:
        self.id = cid
        self.removed = False
        self.exec_results: list[ExecResult] = []
        self.exec_calls: list[tuple[tuple, dict]] = []

    def exec_run(self, *args, **kwargs):
        if self.removed:
            raise NotFound("container not found")
        self.exec_calls.append((args, kwargs))
        return self.exec_results.pop(0) if self.exec_results else ExecResult()

    def stop(self, timeout: int = 5) -> None:
        return None

    def remove(self, force: bool = True) -> None:
        self.removed = True


class FakeContainers:
    def __init__(self) -> None:
        self.created = 0
        self.items: dict[str, FakeContainer] = {}

    def run(self, *args, **kwargs):
        self.created += 1
        container = FakeContainer(f"{self.created:012x}" + ("0" * 52))
        self.items[container.id[:12]] = container
        return container

    def get(self, cid: str) -> FakeContainer:
        container = self.items[cid]
        if container.removed:
            raise NotFound("container not found")
        return container


class FakeDockerClient:
    def __init__(self) -> None:
        self.containers = FakeContainers()


def _load_proxy(monkeypatch: pytest.MonkeyPatch):
    proxy_dir = Path("/repo/sandbox-proxy")
    sys.path.insert(0, str(proxy_dir))
    sys.modules.pop("main", None)
    sys.modules.pop("policy", None)
    proxy = importlib.import_module("main")
    monkeypatch.setattr(proxy, "docker_client", FakeDockerClient())
    monkeypatch.setattr(proxy, "_container_objects", {})
    monkeypatch.setattr(proxy, "_container_meta", {})
    monkeypatch.setattr(proxy, "_pooled_ids", set())
    monkeypatch.setattr(proxy, "_pool", asyncio.Queue())
    monkeypatch.setattr(proxy, "_pool_maintenance_lock", asyncio.Lock())
    monkeypatch.setattr(proxy, "POOL_MIN", 2)
    monkeypatch.setattr(proxy, "POOL_MAX", 2)
    return proxy


async def test_pool_warmup_is_bounded_and_recycle_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    await proxy._warm_pool(5)
    assert proxy._pool.qsize() == 2
    assert len(proxy._container_objects) == 2

    allocated = await proxy.allocate_container("token")
    cid = allocated["container_id"]
    assert proxy._pool.qsize() == 1

    await proxy.recycle_container(cid, "token")
    await proxy.recycle_container(cid, "token")
    assert proxy._pool.qsize() == 2
    assert len(proxy._pooled_ids) == 2


async def test_unhealthy_container_is_replaced_without_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    await proxy._warm_pool(1)
    allocated = await proxy.allocate_container("token")
    old_cid = allocated["container_id"]
    old_container = proxy._container_objects[old_cid]
    proxy._container_meta[old_cid]["unhealthy"] = True

    recycled = await proxy.recycle_container(old_cid, "token")
    assert recycled["expired"] is True
    assert recycled["container_id"] != old_cid
    assert old_container.removed is True
    assert old_cid not in proxy._container_objects
    assert len(proxy._container_objects) == 2
    assert proxy._pool.qsize() == 2


async def test_health_replenishes_pool_after_container_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    await proxy._warm_pool(2)
    lost_id = next(iter(proxy._container_objects))
    proxy._remove_container(lost_id)
    assert len(proxy._container_objects) == 1

    health = await proxy.health()

    assert health["total_containers"] == 2
    assert health["pool_size"] == 2


async def test_health_prunes_externally_removed_pool_container_and_replenishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    await proxy._warm_pool(2)
    lost_id = next(iter(proxy._container_objects))
    proxy._container_objects[lost_id].removed = True

    health = await proxy.health()

    assert lost_id not in proxy._container_objects
    assert lost_id not in proxy._pooled_ids
    assert health["total_containers"] == 2
    assert health["pool_size"] == 2
    assert proxy.docker_client.containers.created == 3


async def test_health_prunes_unpingable_pool_container_and_replenishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    await proxy._warm_pool(2)
    broken_id = next(iter(proxy._container_objects))
    broken = proxy._container_objects[broken_id]
    broken.exec_results.append(FailedExecResult())

    health = await proxy.health()

    assert broken_id not in proxy._container_objects
    assert broken_id not in proxy._pooled_ids
    assert broken.removed is True
    assert health["total_containers"] == 2
    assert health["pool_size"] == 2
    assert proxy.docker_client.containers.created == 3


async def test_health_prunes_expired_idle_container_and_replenishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    await proxy._warm_pool(2)
    expired_id = next(iter(proxy._container_objects))
    expired = proxy._container_objects[expired_id]
    proxy._container_meta[expired_id]["created_at"] = 0
    monkeypatch.setattr(proxy, "MAX_LIFETIME_SECONDS", 1)

    health = await proxy.health()

    assert expired_id not in proxy._container_objects
    assert expired_id not in proxy._pooled_ids
    assert expired.removed is True
    assert health["total_containers"] == 2
    assert health["pool_size"] == 2
    assert proxy.docker_client.containers.created == 3


async def test_health_trims_surplus_idle_pool_back_to_min(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    monkeypatch.setattr(proxy, "POOL_MAX", 4)
    await proxy._warm_pool(2)
    initial = list(proxy._container_objects.values())
    extra_id = proxy._create_container()
    all_containers = [*initial, proxy._container_objects[extra_id]]
    await proxy._enqueue_idle(extra_id)

    health = await proxy.health()

    assert health["total_containers"] == 2
    assert health["pool_size"] == 2
    assert sum(1 for container in all_containers if container.removed) == 1
    assert len(proxy._container_objects) == 2
    assert len(proxy._pooled_ids) == 2


async def test_recycle_trims_allocated_container_when_idle_pool_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    monkeypatch.setattr(proxy, "POOL_MAX", 4)
    await proxy._warm_pool(2)
    extra_id = proxy._create_container()
    extra = proxy._container_objects[extra_id]

    result = await proxy.recycle_container(extra_id, "token")

    assert result["trimmed"] is True
    assert extra.removed is True
    assert extra_id not in proxy._container_objects
    assert len(proxy._container_objects) == 2
    assert proxy._pool.qsize() == 2


async def test_long_script_execution_cannot_starve_child_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    pool_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    execution_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    execution_started = threading.Event()
    release_execution = threading.Event()
    monkeypatch.setattr(proxy, "_pool_executor", pool_executor)
    monkeypatch.setattr(proxy, "_execution_executor", execution_executor, raising=False)

    await proxy._warm_pool(2)
    first = (await proxy.allocate_container("token"))["container_id"]
    first_container = proxy._container_objects[first]
    original_exec_run = first_container.exec_run

    def blocking_exec_run(*args, **kwargs):
        command = args[0]
        if isinstance(command, list) and "/runner.py" in command:
            execution_started.set()
            assert release_execution.wait(timeout=2)
        return original_exec_run(*args, **kwargs)

    first_container.exec_run = blocking_exec_run
    response = await proxy.execute_script(
        first,
        proxy.ExecuteRequest(script="print(42)", timeout=1),
        "token",
    )
    assert await asyncio.to_thread(execution_started.wait, 1)

    allocated = await asyncio.wait_for(proxy.allocate_container("token"), timeout=0.5)
    await asyncio.wait_for(
        proxy.recycle_container(allocated["container_id"], "token"),
        timeout=0.5,
    )

    release_execution.set()
    await asyncio.wait_for(response.body_iterator.__anext__(), timeout=1)
    await asyncio.wait_for(proxy.recycle_container(first, "token"), timeout=0.5)
    pool_executor.shutdown(wait=True)
    execution_executor.shutdown(wait=True)

    assert allocated["container_id"] != first
    assert proxy._pooled_ids == set(proxy._container_objects)
    assert all(meta["allocated_at"] is None for meta in proxy._container_meta.values())


async def test_lifespan_shuts_down_all_bounded_executors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    monkeypatch.setattr(proxy, "POOL_MIN", 0)
    executors = [
        concurrent.futures.ThreadPoolExecutor(max_workers=1)
        for _ in range(4)
    ]
    monkeypatch.setattr(proxy, "_execution_executor", executors[0])
    monkeypatch.setattr(proxy, "_parent_executor", executors[1])
    monkeypatch.setattr(proxy, "_control_executor", executors[2])
    monkeypatch.setattr(proxy, "_pool_executor", executors[3])
    monkeypatch.setattr(proxy, "_cleanup_managed_containers", lambda: None)

    async with proxy.lifespan(proxy.app):
        pass

    for executor in executors:
        with pytest.raises(RuntimeError, match="cannot schedule new futures"):
            executor.submit(lambda: None)


async def test_recycle_cleans_entire_workspace_as_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    await proxy._warm_pool(1)
    cid = (await proxy.allocate_container("token"))["container_id"]
    container = proxy._container_objects[cid]

    await proxy.recycle_container(cid, "token")

    args, kwargs = container.exec_calls[-1]
    assert args[0] == [
        "sh",
        "-c",
        "rm -rf /workspace/* /workspace/.[!.]* /workspace/..?*",
    ]
    assert kwargs["user"] == "root"
    assert proxy._pool.qsize() == 2


async def test_recycle_replaces_container_when_workspace_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    await proxy._warm_pool(1)
    cid = (await proxy.allocate_container("token"))["container_id"]
    dirty = proxy._container_objects[cid]
    failed = ExecResult()
    failed.exit_code = 1
    dirty.exec_results.append(failed)

    result = await proxy.recycle_container(cid, "token")

    assert result["replaced_dirty"] is True
    assert result["container_id"] != cid
    assert dirty.removed is True
    assert cid not in proxy._container_objects


async def test_recycle_fails_closed_when_dirty_container_remove_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    await proxy._warm_pool(1)
    cid = (await proxy.allocate_container("token"))["container_id"]
    dirty = proxy._container_objects[cid]
    failed = ExecResult()
    failed.exit_code = 1
    dirty.exec_results.append(failed)

    def fail_remove(force: bool = True) -> None:
        raise RuntimeError("docker remove failed")

    dirty.remove = fail_remove

    with pytest.raises(proxy.HTTPException) as exc_info:
        await proxy.recycle_container(cid, "token")

    assert exc_info.value.status_code == 500
    assert "dirty container removal failed" in exc_info.value.detail
    assert cid in proxy._container_objects
    assert cid not in proxy._pooled_ids
    assert proxy.docker_client.containers.created == 2


async def test_recycle_fails_closed_when_dirty_container_still_exists_after_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy(monkeypatch)
    await proxy._warm_pool(1)
    cid = (await proxy.allocate_container("token"))["container_id"]
    dirty = proxy._container_objects[cid]
    failed = ExecResult()
    failed.exit_code = 1
    dirty.exec_results.append(failed)

    dirty.remove = lambda force=True: None

    with pytest.raises(proxy.HTTPException) as exc_info:
        await proxy.recycle_container(cid, "token")

    assert exc_info.value.status_code == 500
    assert "dirty container removal failed" in exc_info.value.detail
    assert cid in proxy._container_objects
    assert cid not in proxy._pooled_ids
    assert proxy.docker_client.containers.created == 2
