"""Sandbox container security configuration tests."""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from app.core.sandbox.manager import SandboxManager

UNSAFE_RUN_IDS = [
    None,
    "",
    ".",
    "..",
    "../escape",
    "..\\escape",
    "/escape",
    "\\escape",
    "safe/../escape",
    "safe\\..\\escape",
]


class FakeContainer:
    def __init__(self, cid: str = "a" * 64) -> None:
        self.id = cid
        self.removed = False
        self.running = True
        self.remove_failures = 0
        self.stop_calls = 0
        self.kill_calls = 0

    def stop(self, timeout: int = 5) -> None:
        self.stop_calls += 1
        self.running = False

    def kill(self) -> None:
        self.kill_calls += 1
        self.running = False

    def remove(self, force: bool = True) -> None:
        if self.remove_failures > 0:
            self.remove_failures -= 1
            raise RuntimeError("remove failed")
        self.removed = True
        self.running = False

    def exec_run(self, *args, **kwargs):
        if kwargs.get("stream"):
            class StreamResult:
                exit_code = 0
                output = iter([(b"ok\n", None)])

            return StreamResult()

        class Result:
            exit_code = 0
            output = (b"ok\n", b"")

        return Result()


class FakeContainers:
    def __init__(self) -> None:
        self.args: tuple | None = None
        self.kwargs: dict | None = None
        self.list_calls: list[dict] = []
        self.container = FakeContainer()
        self.retain_removed_in_active_list = False

    def run(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        return self.container

    def list(self, *args, **kwargs):
        self.list_calls.append({"args": args, "kwargs": kwargs})
        if self.container.removed and not self.retain_removed_in_active_list:
            return []
        return [self.container]


class FakeDockerClient:
    def __init__(self) -> None:
        self.containers = FakeContainers()


def _load_proxy():
    proxy_dir = Path("/repo/sandbox-proxy")
    sys.path.insert(0, str(proxy_dir))
    sys.modules.pop("main", None)
    sys.modules.pop("policy", None)
    return importlib.import_module("main")


def _parent_body(proxy):
    return proxy.ParentExecuteRequest(
        run_id="safe-run",
        capability="x" * 20,
        script="print('ok')",
        timeout=5,
    )


def test_created_container_has_mandatory_security_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "_container_objects", {})
    monkeypatch.setattr(proxy, "_container_meta", {})
    monkeypatch.setattr(proxy, "_pooled_ids", set())
    monkeypatch.setattr(proxy, "_pool", asyncio.Queue())
    monkeypatch.setenv("SANDBOX_NETWORK_MODE", "none")

    proxy._create_container()

    kwargs = fake.containers.kwargs
    args = fake.containers.args
    assert args is not None
    assert kwargs is not None
    assert args[0] == proxy.SANDBOX_IMAGE
    assert kwargs["network_mode"] == "none"
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["labels"] == {
        "chainless.sandbox.managed": "true",
        "chainless.sandbox.proxy_owner": proxy.PROXY_OWNER,
    }
    assert kwargs["pids_limit"] > 0
    assert kwargs["mem_limit"]
    assert kwargs["cpu_quota"] > 0
    assert kwargs["tmpfs"] == {"/workspace": "size=64m,mode=1777"}
    assert "no-new-privileges:true" in kwargs["security_opt"]
    assert all(option != "seccomp=unconfined" for option in kwargs["security_opt"])


def test_only_sandbox_proxy_has_docker_socket() -> None:
    compose = Path("/repo/docker-compose.yml").read_text(encoding="utf-8")
    assert compose.count("/var/run/docker.sock:/var/run/docker.sock") == 1
    proxy_section = compose.split("  sandbox-proxy:", 1)[1].split("  backend:", 1)[0]
    assert "/var/run/docker.sock:/var/run/docker.sock" in proxy_section


def test_disposable_parent_container_mounts_only_run_control_subpath(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setenv("SANDBOX_NETWORK_MODE", "none")

    container = proxy._create_disposable_parent("safe-run", "capability")

    kwargs = fake.containers.kwargs
    args = fake.containers.args
    assert args is not None
    assert kwargs is not None
    assert args[0] == proxy.SANDBOX_IMAGE
    assert kwargs["network_mode"] == "none"
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["group_add"] == [str(proxy.SUBAGENT_CONTROL_GID)]
    assert kwargs.get("user") is None
    assert "no-new-privileges:true" in kwargs["security_opt"]
    assert kwargs["environment"] == {"CHAINLESS_SUBAGENT_CAPABILITY": "capability"}
    assert kwargs["labels"]["chainless.sandbox.proxy_owner"] == proxy.PROXY_OWNER
    assert kwargs["labels"]["chainless.sandbox.disposable"] == "true"
    assert kwargs["labels"]["chainless.sandbox.parent_run"] == "safe-run"
    assert len(kwargs["mounts"]) == 1
    mount = kwargs["mounts"][0]
    assert mount["Source"] == proxy.SUBAGENT_CONTROL_VOLUME
    assert mount["Target"] == "/run/chainless"
    assert mount["VolumeOptions"]["Subpath"] == "safe-run"
    assert container.id[:12] not in proxy._container_objects


def test_proxy_cleanup_queries_are_scoped_to_owner_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "PROXY_OWNER", "owner-a")

    proxy._cleanup_managed_containers()
    fake.containers.container.removed = False
    proxy._cleanup_disposable_parent(fake.containers.container)

    managed_filters = fake.containers.list_calls[0]["kwargs"]["filters"]
    disposable_filters = fake.containers.list_calls[1]["kwargs"]["filters"]
    assert managed_filters == {
        "label": [
            "chainless.sandbox.managed=true",
            "chainless.sandbox.proxy_owner=owner-a",
        ]
    }
    assert disposable_filters == {
        "label": [
            "chainless.sandbox.disposable=true",
            "chainless.sandbox.proxy_owner=owner-a",
        ]
    }


@pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
def test_disposable_parent_rejects_control_volume_subpath_escape(run_id: object) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    proxy.docker_client = fake

    with pytest.raises(ValueError):
        proxy._create_disposable_parent(run_id, "capability")

    assert fake.containers.args is None
    assert fake.containers.kwargs is None


@pytest.mark.asyncio
async def test_disposable_parent_first_remove_failure_fails_closed_after_best_effort_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    fake.containers.container.remove_failures = 1
    monkeypatch.setattr(proxy, "docker_client", fake)

    with pytest.raises(HTTPException) as exc_info:
        await proxy.execute_disposable_parent(
            proxy.ParentExecuteRequest(
                run_id="safe-run",
                capability="x" * 20,
                script="print('ok')",
                timeout=5,
            ),
            "token",
        )

    detail = exc_info.value.detail
    assert exc_info.value.status_code == 500
    assert detail["error"] == "disposable parent cleanup failed"
    assert detail["container_id"] == fake.containers.container.id[:12]
    assert detail["deleted"] is True
    assert detail["active_container_ids"] == []
    assert detail["cleanup_attempts"] == ["remove", "stop", "kill", "remove"]
    assert fake.containers.container.stop_calls == 1
    assert fake.containers.container.kill_calls == 1


@pytest.mark.asyncio
async def test_disposable_parent_continued_remove_failure_reports_observable_orphan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    fake.containers.container.remove_failures = 2
    monkeypatch.setattr(proxy, "docker_client", fake)

    with pytest.raises(HTTPException) as exc_info:
        await proxy.execute_disposable_parent(
            proxy.ParentExecuteRequest(
                run_id="safe-run",
                capability="x" * 20,
                script="print('ok')",
                timeout=5,
            ),
            "token",
        )

    detail = exc_info.value.detail
    cid = fake.containers.container.id[:12]
    assert exc_info.value.status_code == 500
    assert detail["deleted"] is False
    assert detail["active_container_ids"] == [cid]
    assert detail["cleanup_attempts"] == ["remove", "stop", "kill", "remove"]
    assert detail["cleanup_errors"] == ["remove failed", "remove failed"]
    assert fake.containers.container.running is False


@pytest.mark.asyncio
async def test_disposable_parent_remove_success_with_active_container_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    fake.containers.retain_removed_in_active_list = True
    monkeypatch.setattr(proxy, "docker_client", fake)

    with pytest.raises(HTTPException) as exc_info:
        await proxy.execute_disposable_parent(
            proxy.ParentExecuteRequest(
                run_id="safe-run",
                capability="x" * 20,
                script="print('ok')",
                timeout=5,
            ),
            "token",
        )

    detail = exc_info.value.detail
    cid = fake.containers.container.id[:12]
    assert exc_info.value.status_code == 500
    assert detail["error"] == "disposable parent cleanup failed"
    assert detail["deleted"] is True
    assert detail["active_container_ids"] == [cid]
    assert detail["cleanup_errors"] == []
    status = await proxy.get_disposable_parent_status(
        "safe-run",
        proxy.ParentRunControlRequest(capability="x" * 20),
        "token",
    )
    assert status["status"] == "cleanup_failed"


@pytest.mark.asyncio
async def test_disposable_parent_has_strict_global_limit_independent_of_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    started = asyncio.Event()
    release = asyncio.Event()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "DISPOSABLE_PARENT_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(proxy, "_disposable_parent_slots", asyncio.Semaphore(1))

    async def blocking_execute(*args, **kwargs):
        started.set()
        await release.wait()
        return {
            "container_id": "a" * 12,
            "deleted": True,
            "active_container_ids": [],
            "cleanup_attempts": ["remove"],
            "cleanup_errors": [],
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(proxy, "_execute_disposable_parent_bounded", blocking_execute)
    body = proxy.ParentExecuteRequest(
        run_id="safe-run",
        capability="x" * 20,
        script="print('ok')",
        timeout=5,
    )
    first = asyncio.create_task(proxy.execute_disposable_parent(body, "token"))
    await started.wait()

    with pytest.raises(HTTPException) as exc_info:
        await proxy.execute_disposable_parent(body, "token")
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Disposable parent concurrency limit reached"

    release.set()
    await first


@pytest.mark.asyncio
async def test_disposable_parent_cancellation_before_create_does_not_leak_slot_or_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    created = False
    monkeypatch.setattr(proxy, "_disposable_parent_slots", asyncio.Semaphore(1))

    def create(*args):
        nonlocal created
        created = True
        return FakeContainer()

    monkeypatch.setattr(proxy, "_create_disposable_parent", create)
    task = asyncio.create_task(proxy.execute_disposable_parent(_parent_body(proxy), "token"))
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert created is False
    assert proxy._disposable_parent_slots.locked() is False


@pytest.mark.asyncio
async def test_disposable_parent_cancellation_during_create_waits_for_cleanup_and_slot_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    create_started = threading.Event()
    finish_create = threading.Event()
    cleanup_finished = threading.Event()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "_disposable_parent_slots", asyncio.Semaphore(1))

    def create(*args):
        create_started.set()
        assert finish_create.wait(timeout=1)
        return fake.containers.container

    real_cleanup = proxy._cleanup_disposable_parent

    def cleanup(container):
        result = real_cleanup(container)
        cleanup_finished.set()
        return result

    monkeypatch.setattr(proxy, "_create_disposable_parent", create)
    monkeypatch.setattr(proxy, "_cleanup_disposable_parent", cleanup)
    task = asyncio.create_task(proxy.execute_disposable_parent(_parent_body(proxy), "token"))
    assert await asyncio.to_thread(create_started.wait, 1)
    task.cancel()
    await asyncio.sleep(0.05)

    try:
        assert task.done() is False
        assert proxy._disposable_parent_slots.locked() is True
    finally:
        finish_create.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleanup_finished.is_set()
    assert fake.containers.container.removed is True
    assert proxy._disposable_parent_slots.locked() is False


@pytest.mark.asyncio
async def test_parent_run_cancel_and_status_wait_for_authoritative_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    create_started = threading.Event()
    finish_create = threading.Event()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "_disposable_parent_slots", asyncio.Semaphore(1))

    def create(*args):
        create_started.set()
        assert finish_create.wait(timeout=1)
        return fake.containers.container

    monkeypatch.setattr(proxy, "_create_disposable_parent", create)
    body = _parent_body(proxy)
    execute_task = asyncio.create_task(proxy.execute_disposable_parent(body, "token"))
    assert await asyncio.to_thread(create_started.wait, 1)

    with pytest.raises(HTTPException) as exc_info:
        await proxy.get_disposable_parent_status(
            body.run_id,
            proxy.ParentRunControlRequest(capability="y" * 20),
            "token",
        )
    assert exc_info.value.status_code == 403

    cancel_task = asyncio.create_task(
        proxy.cancel_disposable_parent(
            body.run_id,
            proxy.ParentRunControlRequest(capability=body.capability),
            "token",
        )
    )
    await asyncio.sleep(0.05)
    assert cancel_task.done() is False
    finish_create.set()

    cancelled = await cancel_task
    executed = await execute_task
    status = await proxy.get_disposable_parent_status(
        body.run_id,
        proxy.ParentRunControlRequest(capability=body.capability),
        "token",
    )
    assert cancelled["cancelled"] is True
    assert cancelled["deleted"] is True
    assert cancelled["active_container_ids"] == []
    assert executed["deleted"] is True
    assert executed["cancelled"] is True
    assert status == cancelled


@pytest.mark.asyncio
async def test_disposable_parent_cancelled_create_failure_releases_slot_without_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    create_started = threading.Event()
    finish_create = threading.Event()
    cleanup_called = False
    monkeypatch.setattr(proxy, "_disposable_parent_slots", asyncio.Semaphore(1))

    def create(*args):
        create_started.set()
        assert finish_create.wait(timeout=1)
        raise RuntimeError("create failed")

    def cleanup(container):
        nonlocal cleanup_called
        cleanup_called = True

    monkeypatch.setattr(proxy, "_create_disposable_parent", create)
    monkeypatch.setattr(proxy, "_cleanup_disposable_parent", cleanup)
    task = asyncio.create_task(proxy.execute_disposable_parent(_parent_body(proxy), "token"))
    assert await asyncio.to_thread(create_started.wait, 1)
    task.cancel()
    await asyncio.sleep(0.05)

    try:
        assert task.done() is False
        assert proxy._disposable_parent_slots.locked() is True
    finally:
        finish_create.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleanup_called is False
    assert proxy._disposable_parent_slots.locked() is False


@pytest.mark.asyncio
async def test_disposable_parent_cancellation_after_create_waits_for_execution_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    execute_started = threading.Event()
    finish_execute = threading.Event()
    cleanup_finished = threading.Event()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "_disposable_parent_slots", asyncio.Semaphore(1))
    calls = 0

    def exec_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            execute_started.set()
            assert finish_execute.wait(timeout=1)
        return FakeContainer().exec_run(*args, **kwargs)

    real_cleanup = proxy._cleanup_disposable_parent

    def cleanup(container):
        result = real_cleanup(container)
        cleanup_finished.set()
        return result

    fake.containers.container.exec_run = exec_run
    monkeypatch.setattr(proxy, "_cleanup_disposable_parent", cleanup)
    task = asyncio.create_task(proxy.execute_disposable_parent(_parent_body(proxy), "token"))
    assert await asyncio.to_thread(execute_started.wait, 1)
    task.cancel()
    await asyncio.sleep(0.05)

    try:
        assert task.done() is False
        assert proxy._disposable_parent_slots.locked() is True
    finally:
        finish_execute.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleanup_finished.is_set()
    assert fake.containers.container.removed is True
    assert proxy._disposable_parent_slots.locked() is False


@pytest.mark.asyncio
async def test_disposable_parent_cancellation_during_remove_waits_before_releasing_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    cleanup_started = threading.Event()
    finish_cleanup = threading.Event()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "_disposable_parent_slots", asyncio.Semaphore(1))
    real_cleanup = proxy._cleanup_disposable_parent

    def cleanup(container):
        cleanup_started.set()
        assert finish_cleanup.wait(timeout=1)
        return real_cleanup(container)

    monkeypatch.setattr(proxy, "_cleanup_disposable_parent", cleanup)
    task = asyncio.create_task(proxy.execute_disposable_parent(_parent_body(proxy), "token"))
    assert await asyncio.to_thread(cleanup_started.wait, 1)
    task.cancel()
    await asyncio.sleep(0.05)

    try:
        assert task.done() is False
        assert proxy._disposable_parent_slots.locked() is True
    finally:
        finish_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.containers.container.removed is True
    assert proxy._disposable_parent_slots.locked() is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunks",
    [
        [(b"a" * 9, None)],
        [(None, b"b" * 9)],
        [(b"a" * 5, None), (None, b"b" * 5)],
    ],
)
async def test_disposable_parent_output_limits_fail_closed_and_force_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[tuple[bytes | None, bytes | None]],
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "DISPOSABLE_PARENT_MAX_STDOUT_BYTES", 8)
    monkeypatch.setattr(proxy, "DISPOSABLE_PARENT_MAX_STDERR_BYTES", 8)
    monkeypatch.setattr(proxy, "DISPOSABLE_PARENT_MAX_OUTPUT_BYTES", 9)

    class Result:
        exit_code = 0
        output = iter(chunks)

    calls = 0

    def exec_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return FakeContainer().exec_run()
        return Result()

    fake.containers.container.exec_run = exec_run
    with pytest.raises(HTTPException) as exc_info:
        await proxy.execute_disposable_parent(
            proxy.ParentExecuteRequest(
                run_id="safe-run",
                capability="x" * 20,
                script="print('large')",
                timeout=5,
            ),
            "token",
        )

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "Disposable parent output limit exceeded"
    assert fake.containers.container.removed is True


@pytest.mark.asyncio
async def test_disposable_parent_execution_failure_retains_authoritative_cleanup_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "_parent_runs", {})

    def fail_execute(*args, **kwargs):
        raise RuntimeError("docker exec failed")

    fake.containers.container.exec_run = fail_execute
    body = _parent_body(proxy)
    with pytest.raises(HTTPException) as exc_info:
        await proxy.execute_disposable_parent(body, "token")
    assert exc_info.value.status_code == 500

    status = await proxy.get_disposable_parent_status(
        body.run_id,
        proxy.ParentRunControlRequest(capability=body.capability),
        "token",
    )
    assert status["status"] == "deleted"
    assert status["execution_failed"] is True
    assert status["deleted"] is True
    assert status["container_id"] not in status["active_container_ids"]


@pytest.mark.asyncio
async def test_parent_execution_saturation_cannot_starve_control_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    execute_started = threading.Event()
    release_execute = threading.Event()
    interrupted = threading.Event()
    parent_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    control_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "_parent_executor", parent_executor)
    monkeypatch.setattr(proxy, "_control_executor", control_executor)
    monkeypatch.setattr(proxy, "_parent_runs", {})

    calls = 0

    def blocking_exec(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            execute_started.set()
            assert release_execute.wait(timeout=2)
        return FakeContainer().exec_run(*args, **kwargs)

    def interrupt(container):
        interrupted.set()
        release_execute.set()

    fake.containers.container.exec_run = blocking_exec
    monkeypatch.setattr(proxy, "_interrupt_disposable_parent", interrupt)
    body = _parent_body(proxy)
    execute_task = asyncio.create_task(proxy.execute_disposable_parent(body, "token"))
    assert await asyncio.to_thread(execute_started.wait, 1)

    cancel_result = await asyncio.wait_for(
        proxy.cancel_disposable_parent(
            body.run_id,
            proxy.ParentRunControlRequest(capability=body.capability),
            "token",
        ),
        timeout=1,
    )
    execute_result = await execute_task
    parent_executor.shutdown(wait=True)
    control_executor.shutdown(wait=True)

    assert interrupted.is_set()
    assert cancel_result["deleted"] is True
    assert execute_result["deleted"] is True


@pytest.mark.asyncio
async def test_terminal_parent_state_is_compact_and_capability_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    fake = FakeDockerClient()
    monkeypatch.setattr(proxy, "docker_client", fake)
    monkeypatch.setattr(proxy, "_parent_runs", {})
    body = _parent_body(proxy)

    result = await proxy.execute_disposable_parent(body, "token")
    state = proxy._parent_runs[body.run_id]

    assert result["stdout"] == "ok\n"
    assert state.task is None
    assert state.container is None
    assert state.capability is None
    assert state.error is None
    assert state.result is not None
    assert "stdout" not in state.result
    assert "stderr" not in state.result
    status = await proxy.get_disposable_parent_status(
        body.run_id,
        proxy.ParentRunControlRequest(capability=body.capability),
        "token",
    )
    assert status["deleted"] is True


def test_terminal_parent_status_retention_is_ttl_and_capacity_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _load_proxy()
    now = time.monotonic()
    runs = {}
    for index in range(4):
        capability = f"{index}" * 20
        state = proxy.ParentRunState(
            run_id=f"run-{index}",
            capability=None,
            capability_digest=proxy._capability_digest(capability),
            completed_at=now - (4 - index),
            result={"container_id": f"cid-{index}", "deleted": True, "active_container_ids": [], "cleanup_errors": []},
        )
        state.done.set()
        runs[state.run_id] = state
    monkeypatch.setattr(proxy, "_parent_runs", runs)
    monkeypatch.setattr(proxy, "PARENT_RUN_STATUS_MAX_RECORDS", 2)
    monkeypatch.setattr(proxy, "PARENT_RUN_STATUS_TTL_SECONDS", 10)

    proxy._prune_parent_runs()
    assert set(proxy._parent_runs) == {"run-2", "run-3"}

    monkeypatch.setattr(proxy, "PARENT_RUN_STATUS_TTL_SECONDS", 0)
    proxy._prune_parent_runs()
    assert proxy._parent_runs == {}


@pytest.mark.asyncio
async def test_sandbox_manager_proxy_health_uses_bounded_timeout() -> None:
    class Settings:
        sandbox_proxy_url = "http://sandbox-proxy:8080"
        proxy_auth_token = "token"
        sandbox_pool_min = 0
        sandbox_pool_max = 1

    manager = SandboxManager(Settings())
    captured: dict = {}

    async def request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})

        class Response:
            def json(self):
                return {"pool_size": 2, "total_containers": 3}

        return Response()

    manager._request = request

    health = await manager.get_proxy_health()

    assert captured["method"] == "GET"
    assert captured["path"] == "/health"
    assert captured["timeout"].read < 1
    assert captured["timeout"].connect < 1
    assert health == {"pool_size": 2, "total_containers": 3}
    assert manager.pool_size == 2


@pytest.mark.asyncio
async def test_sandbox_manager_rejects_unconfirmed_disposable_parent_cleanup() -> None:
    class Settings:
        sandbox_proxy_url = "http://sandbox-proxy:8080"
        proxy_auth_token = "token"
        sandbox_pool_min = 0
        sandbox_pool_max = 1

    manager = SandboxManager(Settings())
    payloads = [
        {
            "container_id": "removed-after-retry",
            "deleted": True,
            "active_container_ids": [],
            "cleanup_errors": ["remove failed"],
        },
        {
            "container_id": "orphaned",
            "deleted": False,
            "active_container_ids": ["orphaned"],
            "cleanup_errors": ["remove failed", "remove failed"],
        },
    ]

    async def request(*args, **kwargs):
        class Response:
            def json(self):
                return payloads.pop(0)

        return Response()

    manager._request = request
    for _ in range(2):
        with pytest.raises(RuntimeError, match="disposable parent cleanup not confirmed"):
            await manager.execute_disposable_parent(
                run_id="safe-run",
                capability="x" * 20,
                script="print('ok')",
            )


@pytest.mark.asyncio
async def test_sandbox_manager_execute_error_queries_and_records_cleanup_proof() -> None:
    class Settings:
        sandbox_proxy_url = "http://sandbox-proxy:8080"
        proxy_auth_token = "token"
        sandbox_pool_min = 0
        sandbox_pool_max = 1

    manager = SandboxManager(Settings())
    expected_error = RuntimeError("execute failed")
    calls: list[str] = []

    async def request(method, path, **kwargs):
        calls.append(path)
        if path == "/parent-runs/execute":
            raise expected_error

        class Response:
            def json(self):
                return {
                    "container_id": "deleted-parent",
                    "deleted": True,
                    "active_container_ids": [],
                    "cleanup_errors": [],
                }

        return Response()

    manager._request = request
    with pytest.raises(RuntimeError, match="execute failed") as exc_info:
        await manager.execute_disposable_parent(
            run_id="safe-run",
            capability="x" * 20,
            script="raise RuntimeError",
        )

    assert exc_info.value is expected_error
    assert expected_error.disposable_parent_deleted is True
    assert calls == ["/parent-runs/execute", "/parent-runs/safe-run/status"]


@pytest.mark.asyncio
async def test_sandbox_manager_execute_error_records_unconfirmed_cleanup() -> None:
    class Settings:
        sandbox_proxy_url = "http://sandbox-proxy:8080"
        proxy_auth_token = "token"
        sandbox_pool_min = 0
        sandbox_pool_max = 1

    manager = SandboxManager(Settings())
    expected_error = RuntimeError("execute failed")

    async def request(method, path, **kwargs):
        if path == "/parent-runs/execute":
            raise expected_error

        class Response:
            def json(self):
                return {
                    "container_id": "orphan",
                    "deleted": False,
                    "active_container_ids": ["orphan"],
                    "cleanup_errors": ["remove failed"],
                }

        return Response()

    manager._request = request
    with pytest.raises(RuntimeError, match="execute failed") as exc_info:
        await manager.execute_disposable_parent(
            run_id="safe-run",
            capability="x" * 20,
            script="raise RuntimeError",
        )

    assert exc_info.value is expected_error
    assert expected_error.disposable_parent_deleted is False
    assert "cleanup not confirmed" in str(
        expected_error.disposable_parent_cleanup_error
    )


@pytest.mark.asyncio
async def test_sandbox_manager_cancellation_waits_for_proxy_cancel_and_status() -> None:
    class Settings:
        sandbox_proxy_url = "http://sandbox-proxy:8080"
        proxy_auth_token = "token"
        sandbox_pool_min = 0
        sandbox_pool_max = 1

    manager = SandboxManager(Settings())
    execute_started = asyncio.Event()
    calls: list[str] = []
    deleted = {
        "container_id": "deleted-parent",
        "deleted": True,
        "active_container_ids": [],
        "cleanup_errors": [],
    }

    async def request(method, path, **kwargs):
        calls.append(path)
        if path == "/parent-runs/execute":
            execute_started.set()
            await asyncio.Event().wait()

        class Response:
            def json(self):
                return deleted

        return Response()

    manager._request = request
    task = asyncio.create_task(
        manager.execute_disposable_parent(
            run_id="safe-run",
            capability="x" * 20,
            script="while True: pass",
        )
    )
    await execute_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls == [
        "/parent-runs/execute",
        "/parent-runs/safe-run/cancel",
        "/parent-runs/safe-run/status",
    ]


def test_compose_uses_one_explicit_sandbox_image_contract() -> None:
    production = Path("/repo/docker-compose.yml").read_text(encoding="utf-8")
    test = Path("/repo/docker-compose.test.yml").read_text(encoding="utf-8")
    proxy = Path("/repo/sandbox-proxy/main.py").read_text(encoding="utf-8")

    assert 'SANDBOX_IMAGE = os.environ["SANDBOX_IMAGE"]' in proxy
    assert "chainless_sandbox:latest" not in proxy
    assert production.count("SANDBOX_IMAGE: ${SANDBOX_IMAGE:-chainless-sandbox:latest}") == 1
    assert "image: ${SANDBOX_IMAGE:-chainless-sandbox:latest}" in production
    assert test.count("SANDBOX_IMAGE: chainless-sandbox:latest") == 2


def test_compose_uses_one_explicit_subagent_control_gid_contract() -> None:
    production = Path("/repo/docker-compose.yml").read_text(encoding="utf-8")
    test = Path("/repo/docker-compose.test.yml").read_text(encoding="utf-8")
    sandbox_dockerfile = Path("/repo/sandbox/Dockerfile").read_text(encoding="utf-8")

    assert production.count("SUBAGENT_CONTROL_GID: ${SUBAGENT_CONTROL_GID:-10001}") == 3
    assert test.count("SUBAGENT_CONTROL_GID: 10001") == 2
    assert "ARG SUBAGENT_CONTROL_GID=10001" in sandbox_dockerfile
    assert "groupadd -g ${SUBAGENT_CONTROL_GID} subagent-control" in sandbox_dockerfile
    assert "usermod" not in sandbox_dockerfile


def test_compose_explicitly_configures_slice2_security_limits() -> None:
    production = yaml.safe_load(Path("/repo/docker-compose.yml").read_text(encoding="utf-8"))
    test = yaml.safe_load(Path("/repo/docker-compose.test.yml").read_text(encoding="utf-8"))
    backend_env = production["services"]["backend"]["environment"]
    test_backend_env = test["services"]["backend-test"]["environment"]
    live_backend_env = test["services"]["backend-test-live"]["environment"]
    proxy_env = production["services"]["sandbox-proxy"]["environment"]
    test_proxy_env = test["services"]["sandbox-proxy-test"]["environment"]

    for name in (
        "SUBAGENT_MAX_CONNECTIONS_PER_RUN",
        "SUBAGENT_MAX_CONNECTIONS_GLOBAL",
        "SUBAGENT_READ_TIMEOUT_SECONDS",
        "SUBAGENT_HANDLER_TIMEOUT_SECONDS",
        "SUBAGENT_CANCELLATION_GRACE_SECONDS",
    ):
        assert name in backend_env
        assert name in test_backend_env
        assert name in live_backend_env

    for name in (
        "SANDBOX_PROXY_OWNER",
        "DISPOSABLE_PARENT_MAX_CONCURRENCY",
        "DISPOSABLE_PARENT_MAX_STDOUT_BYTES",
        "DISPOSABLE_PARENT_MAX_STDERR_BYTES",
        "DISPOSABLE_PARENT_MAX_OUTPUT_BYTES",
        "PARENT_RUN_STATUS_TTL_SECONDS",
        "PARENT_RUN_STATUS_MAX_RECORDS",
    ):
        assert name in proxy_env
        assert name in test_proxy_env
    assert proxy_env["SANDBOX_PROXY_OWNER"] == "${SANDBOX_PROXY_OWNER:-chainless-production}"
    assert test_proxy_env["SANDBOX_PROXY_OWNER"] == "chainless-test"
