"""Security boundary tests for run-scoped sub-agent control sockets."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest

from app.core.agent.subagent_control import CapabilityAuthority, CapabilityError
from app.core.sandbox.manager import SandboxManager

CONTROL_GID = 10001
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


async def _rpc(socket_path: Path, payload: dict) -> dict:
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(json.dumps(payload).encode("utf-8") + b"\n")
    await writer.drain()
    response = json.loads((await reader.readline()).decode("utf-8"))
    writer.close()
    await writer.wait_closed()
    return response


async def _open_rpc(socket_path: Path, payload: dict) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(json.dumps(payload).encode("utf-8") + b"\n")
    await writer.drain()
    return reader, writer


async def _wait_until(predicate, *, timeout: float = 0.5) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout=timeout)


@pytest.mark.asyncio
async def test_capability_is_random_scoped_short_lived_and_parent_bound(
    tmp_path: Path,
) -> None:
    now = [100.0]
    calls: list[tuple[str, str, str, str, int]] = []

    async def handler(prompt, context, *, tenant_id, parent_run_id, depth):
        calls.append((prompt, context, tenant_id, parent_run_id, depth))
        return {"output": f"{prompt}:{context}"}

    authority = CapabilityAuthority(handler, control_root=tmp_path, clock=lambda: now[0])
    authority.activate_parent("tenant-a", "run-a")
    token = authority.issue_capability("tenant-a", "run-a", ttl_seconds=5)
    other = authority.issue_capability("tenant-a", "run-a", ttl_seconds=5)
    assert token != other
    assert "tenant-a" not in token
    assert "run-a" not in token

    async with authority.serve_run("tenant-a", "run-a") as socket_path:
        accepted = await _rpc(
            socket_path,
            {
                "capability": token,
                "method": "spawn_sub_agent",
                "params": {"prompt": "p", "context": "c"},
            },
        )
        assert accepted == {"ok": True, "result": {"output": "p:c"}}
        assert calls == [("p", "c", "tenant-a", "run-a", 1)]

        now[0] = 106.0
        expired = await _rpc(
            socket_path,
            {
                "capability": token,
                "method": "spawn_sub_agent",
                "params": {"prompt": "late", "context": ""},
            },
        )
        assert expired == {"ok": False, "error": "capability rejected"}


@pytest.mark.asyncio
async def test_foreign_revoked_arbitrary_and_client_authority_fail_closed(
    tmp_path: Path,
) -> None:
    async def handler(prompt, context, *, tenant_id, parent_run_id, depth):
        return {"output": prompt}

    authority = CapabilityAuthority(handler, control_root=tmp_path)
    authority.activate_parent("tenant-a", "run-a")
    authority.activate_parent("tenant-b", "run-b")
    token_a = authority.issue_capability("tenant-a", "run-a")

    async with authority.serve_run("tenant-b", "run-b") as socket_b:
        assert (
            await _rpc(
                socket_b,
                {
                    "capability": token_a,
                    "method": "spawn_sub_agent",
                    "params": {"prompt": "foreign", "context": ""},
                },
            )
        ) == {"ok": False, "error": "capability rejected"}

    async with authority.serve_run("tenant-a", "run-a") as socket_a:
        for payload in (
            {"capability": token_a, "method": "get_secrets", "params": {}},
            {
                "capability": token_a,
                "method": "spawn_sub_agent",
                "params": {"prompt": "x", "context": ""},
                "tenant_id": "tenant-b",
            },
            {
                "capability": token_a,
                "method": "spawn_sub_agent",
                "params": {"prompt": "x", "context": ""},
                "parent_run_id": "run-b",
            },
            {
                "capability": token_a,
                "method": "spawn_sub_agent",
                "params": {"prompt": "x", "context": ""},
                "depth": 0,
            },
            {
                "capability": token_a,
                "method": "spawn_sub_agent",
                "params": {"prompt": "x", "context": ""},
                "operation": "get_secrets",
            },
            {
                "capability": token_a,
                "method": "spawn_sub_agent",
                "params": {"prompt": "x", "context": ""},
                "unexpected": True,
            },
            {
                "capability": token_a,
                "method": "spawn_sub_agent",
                "params": {"prompt": "x", "context": "", "tenant_id": "tenant-b"},
            },
            {
                "capability": token_a,
                "method": "spawn_sub_agent",
                "params": {"prompt": "x", "context": "", "parent_run_id": "run-b"},
            },
            {
                "capability": token_a,
                "method": "spawn_sub_agent",
                "params": {"prompt": "x", "context": "", "depth": 0},
            },
        ):
            assert await _rpc(socket_a, payload) == {
                "ok": False,
                "error": "request rejected",
            }

        await authority.revoke_parent("tenant-a", "run-a")
        assert (
            await _rpc(
                socket_a,
                {
                    "capability": token_a,
                    "method": "spawn_sub_agent",
                    "params": {"prompt": "revoked", "context": ""},
                },
            )
        ) == {"ok": False, "error": "capability rejected"}

    with pytest.raises(CapabilityError):
        authority.issue_capability("tenant-a", "run-a")


@pytest.mark.asyncio
async def test_serve_run_exit_revokes_parent_and_old_capabilities(tmp_path: Path) -> None:
    async def handler(prompt, context, **scope):
        return {"output": prompt}

    authority = CapabilityAuthority(handler, control_root=tmp_path)
    authority.activate_parent("tenant-a", "run-a")
    old_capability = authority.issue_capability("tenant-a", "run-a")

    with pytest.raises(RuntimeError, match="parent failed"):
        async with authority.serve_run("tenant-a", "run-a"):
            raise RuntimeError("parent failed")

    with pytest.raises(CapabilityError):
        authority.issue_capability("tenant-a", "run-a")

    authority.activate_parent("tenant-a", "run-a")
    async with authority.serve_run("tenant-a", "run-a") as socket_path:
        assert await _rpc(
            socket_path,
            {
                "capability": old_capability,
                "method": "spawn_sub_agent",
                "params": {"prompt": "stale", "context": ""},
            },
        ) == {"ok": False, "error": "capability rejected"}


@pytest.mark.asyncio
async def test_serve_run_cancellation_revokes_parent_and_capabilities(tmp_path: Path) -> None:
    async def handler(prompt, context, **scope):
        return {"output": prompt}

    authority = CapabilityAuthority(handler, control_root=tmp_path)
    authority.activate_parent("tenant-a", "run-cancelled")
    authority.issue_capability("tenant-a", "run-cancelled")
    entered = asyncio.Event()

    async def serve_until_cancelled() -> None:
        async with authority.serve_run("tenant-a", "run-cancelled"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(serve_until_cancelled())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with pytest.raises(CapabilityError):
        authority.issue_capability("tenant-a", "run-cancelled")


@pytest.mark.asyncio
async def test_serve_run_repeated_cancellation_cannot_interrupt_authoritative_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler_entered = asyncio.Event()
    handler_exited = asyncio.Event()
    cleanup_entered = asyncio.Event()
    allow_cleanup = asyncio.Event()

    async def handler(prompt, context, **scope):
        handler_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            handler_exited.set()

    authority = CapabilityAuthority(
        handler,
        control_root=tmp_path,
        cancellation_grace_seconds=0.2,
    )
    authority.activate_parent("tenant-a", "run-repeat-cancel")
    token = authority.issue_capability("tenant-a", "run-repeat-cancel")
    original_revoke_parent = authority.revoke_parent

    async def delayed_revoke_parent(tenant_id: str, parent_run_id: str) -> None:
        cleanup_entered.set()
        await allow_cleanup.wait()
        await original_revoke_parent(tenant_id, parent_run_id)

    monkeypatch.setattr(authority, "revoke_parent", delayed_revoke_parent)
    socket_path: Path | None = None
    rpc: asyncio.Task | None = None

    async def serve_until_cancelled() -> None:
        nonlocal socket_path, rpc
        async with authority.serve_run("tenant-a", "run-repeat-cancel") as path:
            socket_path = path
            rpc = asyncio.create_task(
                _rpc(
                    path,
                    {
                        "capability": token,
                        "method": "spawn_sub_agent",
                        "params": {"prompt": "block", "context": ""},
                    },
                )
            )
            await handler_entered.wait()
            await asyncio.Event().wait()

    task = asyncio.create_task(serve_until_cancelled())
    await handler_entered.wait()
    task.cancel()
    await cleanup_entered.wait()
    task.cancel()
    allow_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert socket_path is not None
    assert rpc is not None
    assert await rpc == {"ok": False, "error": "spawn cancelled"}
    assert handler_exited.is_set()
    assert not socket_path.exists()
    assert not socket_path.parent.exists()
    assert authority._active_parents == set()
    assert authority._capabilities == {}
    assert authority._clients_by_parent == {}
    assert authority._connections_by_parent == {}
    assert authority._handlers_by_parent == {}
    assert authority._reapers_by_parent == {}
    assert authority.active_connection_count == 0


@pytest.mark.asyncio
async def test_revoke_parent_cancels_authorized_inflight_handler_and_waits_for_exit(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    exited = asyncio.Event()

    async def handler(prompt, context, **scope):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    authority = CapabilityAuthority(handler, control_root=tmp_path, cancellation_grace_seconds=0.2)
    authority.activate_parent("tenant-a", "run-revoke")
    token = authority.issue_capability("tenant-a", "run-revoke")

    async with authority.serve_run("tenant-a", "run-revoke") as socket_path:
        rpc = asyncio.create_task(
            _rpc(
                socket_path,
                {
                    "capability": token,
                    "method": "spawn_sub_agent",
                    "params": {"prompt": "block", "context": ""},
                },
            )
        )
        await entered.wait()
        await authority.revoke_parent("tenant-a", "run-revoke")
        assert exited.is_set()
        assert authority.inflight_handler_count == 0
        assert await rpc == {"ok": False, "error": "spawn cancelled"}


@pytest.mark.asyncio
async def test_serve_run_exit_repeatedly_cancels_handler_that_swallows_first_cancel(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    swallowed = asyncio.Event()
    side_effects: list[str] = []

    async def handler(prompt, context, **scope):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            swallowed.set()
            await asyncio.Event().wait()
        side_effects.append("escaped")

    authority = CapabilityAuthority(handler, control_root=tmp_path, cancellation_grace_seconds=0.2)
    authority.activate_parent("tenant-a", "run-stubborn")
    token = authority.issue_capability("tenant-a", "run-stubborn")

    async with authority.serve_run("tenant-a", "run-stubborn") as socket_path:
        rpc = asyncio.create_task(
            _rpc(
                socket_path,
                {
                    "capability": token,
                    "method": "spawn_sub_agent",
                    "params": {"prompt": "block", "context": ""},
                },
            )
        )
        await entered.wait()

    await asyncio.wait_for(swallowed.wait(), timeout=0.5)
    assert await rpc == {"ok": False, "error": "spawn cancelled"}
    await asyncio.sleep(0.05)
    assert side_effects == []
    assert authority.inflight_handler_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", ["revoke", "serve_exit"])
async def test_authority_reaper_retains_and_repeatedly_cancels_uncooperative_handler(
    tmp_path: Path,
    shutdown: str,
) -> None:
    entered = asyncio.Event()
    cancelled_twice = asyncio.Event()
    allow_exit = asyncio.Event()
    cancel_count = 0
    side_effects: list[str] = []

    async def handler(prompt, context, **scope):
        nonlocal cancel_count
        entered.set()
        while True:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancel_count += 1
                if cancel_count >= 2:
                    cancelled_twice.set()
                if allow_exit.is_set():
                    return
        side_effects.append("escaped")

    authority = CapabilityAuthority(
        handler,
        control_root=tmp_path,
        cancellation_grace_seconds=0.05,
    )
    authority.activate_parent("tenant-a", f"run-{shutdown}")
    token = authority.issue_capability("tenant-a", f"run-{shutdown}")
    server = authority.serve_run("tenant-a", f"run-{shutdown}")
    socket_path = await server.__aenter__()
    rpc = asyncio.create_task(
        _rpc(
            socket_path,
            {
                "capability": token,
                "method": "spawn_sub_agent",
                "params": {"prompt": "block", "context": ""},
            },
        )
    )
    await entered.wait()

    server_exited = False
    try:
        if shutdown == "revoke":
            await asyncio.wait_for(
                authority.revoke_parent("tenant-a", f"run-{shutdown}"),
                timeout=0.2,
            )
        else:
            await asyncio.wait_for(server.__aexit__(None, None, None), timeout=0.2)
            server_exited = True

        await asyncio.wait_for(cancelled_twice.wait(), timeout=0.2)
        assert authority.inflight_handler_count == 1
        assert authority.reaper_count == 1
        assert side_effects == []
    finally:
        allow_exit.set()
        await _wait_until(
            lambda: authority.inflight_handler_count == 0 and authority.reaper_count == 0
        )
        if not server_exited:
            await server.__aexit__(None, None, None)
        await authority.aclose()

    assert await rpc == {"ok": False, "error": "spawn cancelled"}
    assert authority.reaper_count == 0
    assert side_effects == []


@pytest.mark.asyncio
async def test_aclose_fails_closed_and_retains_reaper_until_handler_exits(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    allow_exit = asyncio.Event()
    cancelled_after_close = asyncio.Event()
    cancel_count = 0

    async def handler(prompt, context, **scope):
        nonlocal cancel_count
        entered.set()
        while True:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancel_count += 1
                if cancel_count >= 2:
                    cancelled_after_close.set()
                if allow_exit.is_set():
                    return

    authority = CapabilityAuthority(
        handler,
        control_root=tmp_path,
        cancellation_grace_seconds=0.05,
    )
    authority.activate_parent("tenant-a", "run-aclose-stubborn")
    token = authority.issue_capability("tenant-a", "run-aclose-stubborn")
    run_task = asyncio.create_task(
        authority._run_handler(
            authority._capabilities[token],
            "block",
            "",
        )
    )
    await entered.wait()

    try:
        with pytest.raises(RuntimeError, match="authority close incomplete"):
            await authority.aclose()

        await asyncio.wait_for(cancelled_after_close.wait(), timeout=0.2)
        assert authority._closed is False
        assert authority.inflight_handler_count == 1
        assert authority.reaper_count == 1

        allow_exit.set()
        await _wait_until(
            lambda: authority.inflight_handler_count == 0 and authority.reaper_count == 0
        )
        await authority.aclose()
        assert authority._closed is True
        await authority.aclose()
    finally:
        allow_exit.set()
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
        await authority.aclose()

    assert authority.inflight_handler_count == 0
    assert authority.reaper_count == 0


@pytest.mark.asyncio
async def test_concurrent_aclose_is_idempotent_when_handlers_cooperate(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    exited = asyncio.Event()

    async def handler(prompt, context, **scope):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    authority = CapabilityAuthority(
        handler,
        control_root=tmp_path,
        cancellation_grace_seconds=0.2,
    )
    authority.activate_parent("tenant-a", "run-aclose-cooperative")
    token = authority.issue_capability("tenant-a", "run-aclose-cooperative")
    run_task = asyncio.create_task(
        authority._run_handler(
            authority._capabilities[token],
            "block",
            "",
        )
    )
    await entered.wait()

    await asyncio.gather(authority.aclose(), authority.aclose(), authority.aclose())
    await asyncio.gather(run_task, return_exceptions=True)
    await authority.aclose()

    assert exited.is_set()
    assert authority.inflight_handler_count == 0
    assert authority.reaper_count == 0


@pytest.mark.asyncio
async def test_successful_aclose_permanently_revokes_authority(
    tmp_path: Path,
) -> None:
    async def handler(prompt, context, **scope):
        return {"output": prompt}

    authority = CapabilityAuthority(handler, control_root=tmp_path)
    authority.activate_parent("tenant-a", "run-a")
    authority.activate_parent("tenant-b", "run-b")
    token_a = authority.issue_capability("tenant-a", "run-a")
    authority.issue_capability("tenant-b", "run-b")

    await asyncio.gather(authority.aclose(), authority.aclose(), authority.aclose())

    assert authority._closed is True
    assert authority._active_parents == set()
    assert authority._capabilities == {}
    with pytest.raises(CapabilityError, match="authority is closed"):
        authority.activate_parent("tenant-a", "run-new")
    with pytest.raises(CapabilityError, match="authority is closed"):
        authority.issue_capability("tenant-a", "run-a")
    with pytest.raises(CapabilityError, match="authority is closed"):
        authority._authorize(
            token_a,
            tenant_id="tenant-a",
            parent_run_id="run-a",
            operation="spawn_sub_agent",
        )
    with pytest.raises(CapabilityError, match="authority is closed"):
        async with authority.serve_run("tenant-a", "run-a"):
            pytest.fail("closed authority must not serve a run")

    await authority.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("result_kind", ["task", "future", "custom"])
async def test_spawn_handler_arbitrary_awaitable_is_owned_and_cancelled(
    tmp_path: Path,
    result_kind: str,
) -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def operation() -> object:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    class CustomAwaitable:
        def __await__(self):
            return operation().__await__()

    def handler(prompt, context, **scope):
        if result_kind == "task":
            return asyncio.create_task(operation())
        if result_kind == "future":
            future = asyncio.get_running_loop().create_future()

            async def mark_entered() -> None:
                entered.set()

            asyncio.create_task(mark_entered())
            future.add_done_callback(lambda _: cancelled.set())
            return future
        return CustomAwaitable()

    authority = CapabilityAuthority(
        handler,
        control_root=tmp_path,
        cancellation_grace_seconds=0.2,
    )
    authority.activate_parent("tenant-a", f"run-{result_kind}")
    token = authority.issue_capability("tenant-a", f"run-{result_kind}")
    run_task = asyncio.create_task(
        authority._run_handler(authority._capabilities[token], "block", "")
    )
    await entered.wait()

    assert authority.inflight_handler_count == 1
    await authority.revoke_parent("tenant-a", f"run-{result_kind}")
    await asyncio.gather(run_task, return_exceptions=True)

    assert cancelled.is_set()
    assert authority.inflight_handler_count == 0
    assert authority.reaper_count == 0
    await authority.aclose()


@pytest.mark.asyncio
async def test_spawn_handler_sync_result_remains_supported(tmp_path: Path) -> None:
    def handler(prompt, context, **scope):
        return {"output": prompt}

    authority = CapabilityAuthority(handler, control_root=tmp_path)
    authority.activate_parent("tenant-a", "run-sync")
    token = authority.issue_capability("tenant-a", "run-sync")

    assert await authority._run_handler(
        authority._capabilities[token],
        "sync",
        "",
    ) == {"output": "sync"}
    assert authority.inflight_handler_count == 0

    await authority.aclose()


@pytest.mark.asyncio
async def test_uds_connection_limits_fail_closed_and_release_slots(tmp_path: Path) -> None:
    async def handler(prompt, context, **scope):
        return {"output": prompt}

    authority = CapabilityAuthority(
        handler,
        control_root=tmp_path,
        max_connections_per_run=1,
        max_connections_global=1,
        read_timeout_seconds=0.2,
    )
    authority.activate_parent("tenant-a", "run-limited")

    async with authority.serve_run("tenant-a", "run-limited") as socket_path:
        first_reader, first_writer = await asyncio.open_unix_connection(str(socket_path))
        second_reader, second_writer = await asyncio.open_unix_connection(str(socket_path))
        assert json.loads((await asyncio.wait_for(second_reader.readline(), timeout=0.5))) == {
            "ok": False,
            "error": "connection limit exceeded",
        }
        assert await second_reader.readline() == b""
        second_writer.close()
        await second_writer.wait_closed()

        first_writer.close()
        await first_writer.wait_closed()
        assert await first_reader.readline() == b""

        third_reader, third_writer = await asyncio.open_unix_connection(str(socket_path))
        assert authority.active_connection_count == 1
        third_writer.close()
        await third_writer.wait_closed()
        assert await third_reader.readline() == b""

    assert authority.active_connection_count == 0


@pytest.mark.asyncio
async def test_uds_slowloris_and_handler_timeout_fail_closed_without_fd_leak(
    tmp_path: Path,
) -> None:
    handler_cancelled = asyncio.Event()

    async def handler(prompt, context, **scope):
        try:
            await asyncio.Event().wait()
        finally:
            handler_cancelled.set()

    authority = CapabilityAuthority(
        handler,
        control_root=tmp_path,
        read_timeout_seconds=0.05,
        handler_timeout_seconds=0.05,
        cancellation_grace_seconds=0.2,
    )
    authority.activate_parent("tenant-a", "run-timeouts")
    token = authority.issue_capability("tenant-a", "run-timeouts")

    async with authority.serve_run("tenant-a", "run-timeouts") as socket_path:
        slow_reader, slow_writer = await asyncio.open_unix_connection(str(socket_path))
        slow_writer.write(b'{"capability":')
        await slow_writer.drain()
        assert json.loads((await asyncio.wait_for(slow_reader.readline(), timeout=0.5))) == {
            "ok": False,
            "error": "request timeout",
        }
        assert await slow_reader.readline() == b""
        slow_writer.close()
        await slow_writer.wait_closed()

        assert await _rpc(
            socket_path,
            {
                "capability": token,
                "method": "spawn_sub_agent",
                "params": {"prompt": "block", "context": ""},
            },
        ) == {"ok": False, "error": "spawn timeout"}
        assert handler_cancelled.is_set()
        assert authority.inflight_handler_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_phase",
    [
        "run_dir_chown",
        "run_dir_chmod",
        "start_server",
        "socket_chown",
        "socket_chmod",
    ],
)
async def test_serve_run_establishment_failure_revokes_and_cleans_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    async def handler(prompt, context, **scope):
        return {"output": prompt}

    class FakeServer:
        def __init__(self) -> None:
            self.closed = False
            self.waited_closed = False

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            self.waited_closed = True

    authority = CapabilityAuthority(handler, control_root=tmp_path)
    authority.activate_parent("tenant-a", "setup-fails")
    old_capability = authority.issue_capability("tenant-a", "setup-fails")
    run_dir = tmp_path / "setup-fails"
    socket_path = run_dir / "subagent.sock"
    fake_server = FakeServer()
    real_chown = os.chown
    real_chmod = os.chmod
    chown_calls = 0
    chmod_calls = 0

    def fail_selected_chown(path, uid, gid):
        nonlocal chown_calls
        chown_calls += 1
        phase = "run_dir_chown" if chown_calls == 1 else "socket_chown"
        if failure_phase == phase:
            raise RuntimeError(f"{phase} failed")
        real_chown(path, uid, gid)

    def fail_selected_chmod(path, mode):
        nonlocal chmod_calls
        chmod_calls += 1
        phase = "run_dir_chmod" if chmod_calls == 1 else "socket_chmod"
        if failure_phase == phase:
            raise RuntimeError(f"{phase} failed")
        real_chmod(path, mode)

    async def start_server(*args, **kwargs):
        socket_path.touch()
        if failure_phase == "start_server":
            raise RuntimeError("start_server failed")
        return fake_server

    monkeypatch.setattr(os, "chown", fail_selected_chown)
    monkeypatch.setattr(os, "chmod", fail_selected_chmod)
    monkeypatch.setattr(asyncio, "start_unix_server", start_server)

    with pytest.raises(RuntimeError, match="failed"):
        async with authority.serve_run("tenant-a", "setup-fails"):
            pytest.fail("serve_run must not yield after an establishment failure")

    assert fake_server.closed is (failure_phase in {"socket_chown", "socket_chmod"})
    assert fake_server.waited_closed is fake_server.closed
    assert not socket_path.exists()
    assert not run_dir.exists()
    with pytest.raises(CapabilityError):
        authority.issue_capability("tenant-a", "setup-fails")

    authority.activate_parent("tenant-a", "setup-fails")
    with pytest.raises(CapabilityError):
        authority._authorize(
            old_capability,
            tenant_id="tenant-a",
            parent_run_id="setup-fails",
            operation="spawn_sub_agent",
        )


@pytest.mark.asyncio
async def test_control_socket_is_run_scoped_and_removed_after_server_exit(
    tmp_path: Path,
) -> None:
    async def handler(prompt, context, **scope):
        return {"output": prompt}

    authority = CapabilityAuthority(handler, control_root=tmp_path, control_gid=CONTROL_GID)
    authority.activate_parent("tenant-a", "safe-run")

    async with authority.serve_run("tenant-a", "safe-run") as socket_path:
        assert socket_path == tmp_path / "safe-run" / "subagent.sock"
        assert socket_path.is_socket()
        assert socket_path.parent.stat().st_gid == CONTROL_GID
        assert socket_path.parent.stat().st_mode & 0o777 == 0o710
        assert socket_path.stat().st_gid == CONTROL_GID
        assert socket_path.stat().st_mode & 0o777 == 0o660

    assert not socket_path.exists()


@pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
def test_parent_run_id_rejects_control_root_path_escape(
    tmp_path: Path,
    run_id: object,
) -> None:
    async def handler(prompt, context, **scope):
        return {"output": prompt}

    authority = CapabilityAuthority(handler, control_root=tmp_path)

    with pytest.raises(ValueError, match="invalid tenant or parent run scope"):
        authority.activate_parent("tenant-a", run_id)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("run_id", ["safe-run", "run_1.2", "RUN-123"])
def test_parent_run_id_keeps_safe_ids(run_id: str) -> None:
    async def handler(prompt, context, **scope):
        return {"output": prompt}

    authority = CapabilityAuthority(handler)

    authority.activate_parent("tenant-a", run_id)
    assert ("tenant-a", run_id) in authority._active_parents


@pytest.mark.asyncio
async def test_control_socket_denies_world_and_non_group_user(tmp_path: Path) -> None:
    if os.geteuid() != 0:
        pytest.skip("requires root to prove kernel permission denial with a dropped UID/GID")

    async def handler(prompt, context, **scope):
        return {"output": prompt}

    authority = CapabilityAuthority(handler, control_root=tmp_path, control_gid=CONTROL_GID)
    authority.activate_parent("tenant-a", "denied-run")

    async with authority.serve_run("tenant-a", "denied-run") as socket_path:
        assert socket_path.parent.stat().st_mode & 0o007 == 0
        assert socket_path.stat().st_mode & 0o007 == 0
        probe = (
            "import socket,sys\n"
            "s=socket.socket(socket.AF_UNIX)\n"
            "try:\n"
            " s.connect(sys.argv[1])\n"
            "except PermissionError:\n"
            " raise SystemExit(0)\n"
            "raise SystemExit(1)\n"
        )

        def drop_to_non_group_user() -> None:
            os.setgroups([])
            os.setgid(CONTROL_GID + 1)
            os.setuid(CONTROL_GID + 1)

        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", probe, str(socket_path)],
            capture_output=True,
            text=True,
            preexec_fn=drop_to_non_group_user,
            check=False,
        )
        assert result.returncode == 0, result.stderr


@pytest.mark.live_docker
@pytest.mark.asyncio
async def test_live_cross_container_uds_and_disposable_cleanup(tmp_path: Path) -> None:
    if os.environ.get("CHAINLESS_LIVE_DOCKER") != "1":
        pytest.skip("set CHAINLESS_LIVE_DOCKER=1 inside the Compose backend-test service")

    async def handler(prompt, context, *, tenant_id, parent_run_id, depth):
        return {"output": f"uds:{prompt}:{context}:{tenant_id}:{parent_run_id}:{depth}"}

    control_root = Path(os.environ["SUBAGENT_CONTROL_ROOT"])
    authority = CapabilityAuthority(
        handler,
        control_root=control_root,
        control_gid=int(os.environ["SUBAGENT_CONTROL_GID"]),
    )
    run_id = f"uds-{uuid.uuid4().hex}"
    authority.activate_parent("tenant-live", run_id)
    capability = authority.issue_capability("tenant-live", run_id)
    proxy_url = os.environ["SANDBOX_PROXY_URL"].rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['PROXY_AUTH_TOKEN']}"}
    script = "print(spawn_sub_agent('hello', 'ctx')['output'])"

    async with authority.serve_run("tenant-live", run_id):
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{proxy_url}/parent-runs/execute",
                headers=headers,
                json={
                    "run_id": run_id,
                    "capability": capability,
                    "script": script,
                    "timeout": 20,
                },
            )
            response.raise_for_status()
            payload = response.json()
            assert payload["exit_code"] == 0, payload
            assert f"uds:hello:ctx:tenant-live:{run_id}:1" in payload["stdout"], payload
            assert payload["deleted"] is True, payload
            assert payload["container_id"] not in payload["active_container_ids"], payload

    assert not (control_root / run_id / "subagent.sock").exists()


@pytest.mark.live_docker
@pytest.mark.asyncio
async def test_live_cross_http_parent_cancel_returns_after_disposable_delete() -> None:
    if os.environ.get("CHAINLESS_LIVE_DOCKER") != "1":
        pytest.skip("set CHAINLESS_LIVE_DOCKER=1 inside the Compose backend-test service")

    class LiveSettings:
        sandbox_proxy_url = os.environ["SANDBOX_PROXY_URL"]
        proxy_auth_token = os.environ["PROXY_AUTH_TOKEN"]
        sandbox_pool_min = 0
        sandbox_pool_max = 0

    run_id = f"cancel-{uuid.uuid4().hex}"
    capability = "c" * 32
    run_dir = Path(os.environ["SUBAGENT_CONTROL_ROOT"]) / run_id
    run_dir.mkdir(mode=0o710)
    manager = SandboxManager(LiveSettings())
    task = asyncio.create_task(
        manager.execute_disposable_parent(
            run_id=run_id,
            capability=capability,
            script="import time\ntime.sleep(30)",
            timeout=40,
        )
    )
    headers = {"Authorization": f"Bearer {LiveSettings.proxy_auth_token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(100):
            response = await client.post(
                f"{LiveSettings.sandbox_proxy_url}/parent-runs/{run_id}/status",
                headers=headers,
                json={"capability": capability},
            )
            if response.status_code == 200:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("parent run never became visible through status")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{LiveSettings.sandbox_proxy_url}/parent-runs/{run_id}/status",
            headers=headers,
            json={"capability": capability},
        )
        response.raise_for_status()
        payload = response.json()
    assert payload["deleted"] is True
    assert payload["container_id"] not in payload["active_container_ids"]
    await manager.close()
    run_dir.rmdir()


@pytest.mark.live_docker
@pytest.mark.asyncio
async def test_live_parent_execute_failure_still_confirms_disposable_delete() -> None:
    if os.environ.get("CHAINLESS_LIVE_DOCKER") != "1":
        pytest.skip("set CHAINLESS_LIVE_DOCKER=1 inside the Compose backend-test service")

    class LiveSettings:
        sandbox_proxy_url = os.environ["SANDBOX_PROXY_URL"]
        proxy_auth_token = os.environ["PROXY_AUTH_TOKEN"]
        sandbox_pool_min = 0
        sandbox_pool_max = 0

    run_id = f"failed-{uuid.uuid4().hex}"
    capability = "f" * 32
    run_dir = Path(os.environ["SUBAGENT_CONTROL_ROOT"]) / run_id
    run_dir.mkdir(mode=0o710)
    manager = SandboxManager(LiveSettings())
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await manager.execute_disposable_parent(
                run_id=run_id,
                capability=capability,
                script="print('x' * 600000)",
                timeout=20,
            )
        assert exc_info.value.response.status_code == 413
        assert exc_info.value.disposable_parent_deleted is True
        cleanup = exc_info.value.disposable_parent_cleanup_status
        assert cleanup["deleted"] is True
        assert cleanup["container_id"] not in cleanup["active_container_ids"]
    finally:
        await manager.close()
        run_dir.rmdir()


def test_runner_has_no_generic_http_or_platform_secret_injection() -> None:
    runner = Path("/repo/sandbox/runner.py").read_text(encoding="utf-8")
    assert "/run/chainless/subagent.sock" in runner
    assert "urllib" not in runner
    assert "requests" not in runner
    assert "httpx" not in runner
    assert "GLM_API_KEY" not in runner
    assert "DATABASE_URL" not in runner
    assert "DOCKER_HOST" not in runner
