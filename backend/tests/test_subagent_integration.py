"""Real runtime integration between Code-as-Action, UDS, and child agents."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.config import settings
from app.core.agent.code_executor import (
    CODE_AS_ACTION_TOOL,
    execute_code_as_action,
    stream_code_as_action,
)
from app.core.agent.subagents import SubAgentRuntime


async def _rpc(socket_path: Path, capability: str, prompt: str) -> dict:
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(
        json.dumps(
            {
                "capability": capability,
                "method": "spawn_sub_agent",
                "params": {"prompt": prompt, "context": "answer briefly"},
            }
        ).encode("utf-8")
        + b"\n"
    )
    await writer.drain()
    response = json.loads((await reader.readline()).decode("utf-8"))
    writer.close()
    await writer.wait_closed()
    return response


@pytest.mark.asyncio
async def test_aggregate_code_result_excludes_internal_artifact_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream(*args, **kwargs):
        yield {"type": "sandbox_output", "stream": "stdout", "data": "visible"}
        yield {
            "type": "sandbox_output",
            "stream": "artifact",
            "data": '{"artifact_path":"/workspace/internal"}',
        }

    monkeypatch.setattr(
        "app.core.agent.code_executor.stream_code_as_action",
        fake_stream,
    )

    output = await execute_code_as_action(
        "script",
        object(),
        gateway=object(),
        tenant_id="tenant-a",
        parent_budget=1,
    )

    assert output == "visible"


@pytest.mark.asyncio
async def test_code_as_action_uses_real_parallel_child_agent_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Linux AF_UNIX paths are short; keep this below the platform limit.
    control_root = Path("/tmp/chainless-w4-control")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)

    child_tool_names: list[list[str]] = []

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            child_tool_names.append(
                [tool.get("function", {}).get("name", "") for tool in tools]
            )
            prompt = messages[-1]["content"]
            yield {"type": "text", "content": f"child:{prompt}"}

    class Sandbox:
        allocated: list[str] = []
        recycled: list[str] = []

        async def allocate(self) -> str:
            cid = f"child-sandbox-{len(self.allocated) + 1}"
            self.allocated.append(cid)
            return cid

        async def recycle(self, cid: str) -> str:
            self.recycled.append(cid)
            return cid

        async def execute_disposable_parent(
            self,
            *,
            run_id: str,
            capability: str,
            script: str,
            timeout: int = 30,
        ) -> dict:
            socket_path = control_root / run_id / "subagent.sock"
            first, second = await asyncio.gather(
                _rpc(socket_path, capability, "alpha"),
                _rpc(socket_path, capability, "beta"),
            )
            return {
                "container_id": "real-disposable-parent",
                "deleted": True,
                "active_container_ids": [],
                "cleanup_errors": [],
                "stdout": json.dumps([first, second]),
                "stderr": "",
            }

    events = [
        event
        async for event in stream_code_as_action(
            "parallel child calls happen inside the disposable parent",
            Sandbox(),
            gateway=Gateway(),
            tenant_id="tenant-a",
            parent_budget=20_000,
        )
    ]

    output = next(
        event["data"]
        for event in events
        if event["type"] == "sandbox_output"
        and event["stream"] == "stdout"
        and event["container_id"] == "real-disposable-parent"
    )
    responses = json.loads(output)
    assert all(response.get("ok") is True for response in responses), responses
    assert [response["result"]["status"] for response in responses] == [
        "success",
        "success",
    ]
    assert {response["result"]["output"] for response in responses} == {
        "child:alpha",
        "child:beta",
    }
    assert child_tool_names == [[], []]
    assert sorted(Sandbox.allocated) == ["child-sandbox-1", "child-sandbox-2"]
    assert sorted(Sandbox.recycled) == ["child-sandbox-1", "child-sandbox-2"]
    assert all(event["type"] in {"sandbox", "sandbox_output"} for event in events)
    assert sum(event.get("phase") == "sub_agent_started" for event in events) == 2
    assert sum(event.get("phase") == "sub_agent_completed" for event in events) == 2
    assert {"child:alpha", "child:beta"} <= {
        event.get("data") for event in events if event["type"] == "sandbox_output"
    }
    artifact_events = [
        json.loads(event["data"])
        for event in events
        if event.get("type") == "sandbox_output"
        and event.get("stream") == "artifact"
    ]
    assert len(artifact_events) == 2
    assert {artifact["status"] for artifact in artifact_events} == {"success"}
    assert {artifact["output"] for artifact in artifact_events} == {
        "child:alpha",
        "child:beta",
    }
    assert all(not Path(artifact["artifact_path"]).exists() for artifact in artifact_events)
    assert SubAgentRuntime.global_active_count() == 0
    assert list(control_root.rglob("subagent.sock")) == []


@pytest.mark.asyncio
async def test_parent_cancellation_revokes_socket_and_cancels_real_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = Path("/tmp/chainless-w4-cancel")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)

    child_started = asyncio.Event()
    child_cancelled = asyncio.Event()

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            child_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                child_cancelled.set()
            if False:
                yield {}

    class Sandbox:
        async def allocate(self) -> str:
            return "blocking-child-sandbox"

        async def recycle(self, cid: str) -> str:
            return cid

        async def execute_disposable_parent(self, *, run_id, capability, script, timeout=30):
            socket_path = control_root / run_id / "subagent.sock"
            await _rpc(socket_path, capability, "block")
            raise AssertionError("cancelled parent execution unexpectedly returned")

    stream = stream_code_as_action(
        "spawn one blocking child",
        Sandbox(),
        gateway=Gateway(),
        tenant_id="tenant-a",
        parent_budget=20_000,
    )
    allocated = await anext(stream)
    assert allocated["phase"] == "allocated"

    parent_task = asyncio.create_task(anext(stream))
    await child_started.wait()
    parent_task.cancel()
    await asyncio.gather(parent_task, return_exceptions=True)
    await stream.aclose()

    assert child_cancelled.is_set()
    assert SubAgentRuntime.global_active_count() == 0
    assert list(control_root.rglob("subagent.sock")) == []


@pytest.mark.asyncio
async def test_parent_cancellation_waits_for_slow_child_recycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = Path("/tmp/chainless-w4-slow-recycle")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)

    child_started = asyncio.Event()
    recycle_started = asyncio.Event()
    allow_recycle = asyncio.Event()
    recycled: list[str] = []

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            child_started.set()
            await asyncio.Event().wait()
            if False:
                yield {}

    class Sandbox:
        async def allocate(self) -> str:
            return "slow-recycle-child"

        async def recycle(self, cid: str) -> str:
            recycle_started.set()
            await allow_recycle.wait()
            recycled.append(cid)
            return cid

        async def execute_disposable_parent(self, *, run_id, capability, script, timeout=30):
            await _rpc(control_root / run_id / "subagent.sock", capability, "block")
            raise AssertionError("cancelled parent execution unexpectedly returned")

    stream = stream_code_as_action(
        "spawn one blocking child",
        Sandbox(),
        gateway=Gateway(),
        tenant_id="tenant-a",
        parent_budget=20_000,
    )
    assert (await anext(stream))["phase"] == "allocated"

    async def drain_stream() -> None:
        async for _ in stream:
            pass

    stream_task = asyncio.create_task(drain_stream())
    await child_started.wait()

    stream_task.cancel()
    await recycle_started.wait()
    await asyncio.sleep(0)
    assert not stream_task.done()
    assert SubAgentRuntime.global_active_count() == 1

    allow_recycle.set()
    await asyncio.gather(stream_task, return_exceptions=True)
    await stream.aclose()

    assert recycled == ["slow-recycle-child"]
    assert SubAgentRuntime.global_active_count() == 0
    assert list(control_root.rglob("subagent.sock")) == []


@pytest.mark.asyncio
async def test_parent_return_cancels_child_before_parent_terminal_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = Path("/tmp/chainless-w4-parent-return")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)

    child_started = asyncio.Event()
    child_cancelled = asyncio.Event()
    recycled: list[str] = []
    rpc_tasks: list[asyncio.Task] = []

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            child_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                child_cancelled.set()
            if False:
                yield {}

    class Sandbox:
        async def allocate(self) -> str:
            return "parent-return-child"

        async def recycle(self, cid: str) -> str:
            recycled.append(cid)
            return cid

        async def execute_disposable_parent(self, *, run_id, capability, script, timeout=30):
            rpc_tasks.append(
                asyncio.create_task(
                    _rpc(
                        control_root / run_id / "subagent.sock",
                        capability,
                        "outlive parent",
                    )
                )
            )
            await child_started.wait()
            return {
                "container_id": "early-return-parent",
                "stdout": "parent returned",
                "stderr": "",
            }

    events = [
        event
        async for event in stream_code_as_action(
            "spawn child and return immediately",
            Sandbox(),
            gateway=Gateway(),
            tenant_id="tenant-a",
            parent_budget=20_000,
        )
    ]
    await asyncio.gather(*rpc_tasks, return_exceptions=True)

    phases = [
        event["phase"]
        for event in events
        if event["type"] == "sandbox" and "phase" in event
    ]
    assert phases.index("sub_agent_cancelled") < phases.index("completed")
    assert phases.index("completed") < phases.index("deleted")
    assert child_cancelled.is_set()
    assert recycled == ["parent-return-child"]
    assert SubAgentRuntime.global_active_count() == 0
    assert list(control_root.rglob("subagent.sock")) == []


@pytest.mark.asyncio
async def test_parent_error_cancels_child_before_deleted_and_preserves_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = Path("/tmp/chainless-w4-parent-error")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)

    child_started = asyncio.Event()
    child_cancelled = asyncio.Event()
    recycled: list[str] = []
    rpc_tasks: list[asyncio.Task] = []
    expected_error = RuntimeError("parent execution failed")
    expected_error.disposable_parent_deleted = True

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            child_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                child_cancelled.set()
            if False:
                yield {}

    class Sandbox:
        async def allocate(self) -> str:
            return "parent-error-child"

        async def recycle(self, cid: str) -> str:
            recycled.append(cid)
            return cid

        async def execute_disposable_parent(self, *, run_id, capability, script, timeout=30):
            rpc_tasks.append(
                asyncio.create_task(
                    _rpc(
                        control_root / run_id / "subagent.sock",
                        capability,
                        "outlive failed parent",
                    )
                )
            )
            await child_started.wait()
            raise expected_error

    events: list[dict] = []
    with pytest.raises(RuntimeError, match="parent execution failed") as exc_info:
        async for event in stream_code_as_action(
            "spawn child and fail immediately",
            Sandbox(),
            gateway=Gateway(),
            tenant_id="tenant-a",
            parent_budget=20_000,
        ):
            events.append(event)
    await asyncio.gather(*rpc_tasks, return_exceptions=True)
    assert exc_info.value is expected_error

    phases = [
        event["phase"]
        for event in events
        if event["type"] == "sandbox" and "phase" in event
    ]
    assert phases.index("sub_agent_cancelled") < phases.index("deleted")
    assert any(
        event.get("type") == "sandbox_output"
        and event.get("stream") == "error"
        and event.get("data") == "parent execution failed"
        for event in events
    )
    assert child_cancelled.is_set()
    assert recycled == ["parent-error-child"]
    assert SubAgentRuntime.global_active_count() == 0
    assert list(control_root.rglob("subagent.sock")) == []


@pytest.mark.asyncio
async def test_parent_error_without_cleanup_proof_does_not_report_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = Path("/tmp/chainless-w4-parent-unconfirmed")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)
    expected_error = RuntimeError("parent execution failed")
    expected_error.disposable_parent_deleted = False
    expected_error.disposable_parent_cleanup_error = RuntimeError(
        "disposable parent cleanup not confirmed"
    )

    class Sandbox:
        async def execute_disposable_parent(self, **kwargs):
            raise expected_error

    events: list[dict] = []
    with pytest.raises(RuntimeError, match="parent execution failed") as exc_info:
        async for event in stream_code_as_action(
            "fail without cleanup proof",
            Sandbox(),
            gateway=object(),
            tenant_id="tenant-a",
            parent_budget=20_000,
        ):
            events.append(event)

    assert exc_info.value is expected_error
    assert not any(event.get("phase") == "deleted" for event in events)
    assert any(
        event.get("stream") == "error"
        and "cleanup not confirmed" in event.get("data", "")
        for event in events
    )


@pytest.mark.asyncio
async def test_runtime_timeout_streams_timeout_terminal_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.agent import subagents

    control_root = Path("/tmp/chainless-w4-child-timeout")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)
    child_started = asyncio.Event()

    async def immediate_deadline(tasks):
        await child_started.wait()
        return set()

    monkeypatch.setattr(subagents, "_wait_for_product_deadline", immediate_deadline)

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            child_started.set()
            await asyncio.Event().wait()
            if False:
                yield {}

    class Sandbox:
        async def allocate(self) -> str:
            return "timeout-child"

        async def recycle(self, cid: str) -> str:
            return cid

        async def execute_disposable_parent(self, *, run_id, capability, **kwargs):
            response = await _rpc(
                control_root / run_id / "subagent.sock",
                capability,
                "time out",
            )
            assert response["result"]["status"] == "timeout"
            return {
                "container_id": "timeout-parent",
                "deleted": True,
                "active_container_ids": [],
                "cleanup_errors": [],
                "stdout": json.dumps(response),
                "stderr": "",
            }

    events = [
        event
        async for event in stream_code_as_action(
            "spawn timeout child",
            Sandbox(),
            gateway=Gateway(),
            tenant_id="tenant-a",
            parent_budget=20_000,
        )
    ]
    phases = [event.get("phase") for event in events if event["type"] == "sandbox"]
    assert "sub_agent_timeout" in phases
    assert "sub_agent_cancelled" not in phases
    artifacts = [
        json.loads(event["data"])
        for event in events
        if event.get("stream") == "artifact"
    ]
    assert [artifact["status"] for artifact in artifacts] == ["timeout"]
    assert all(not Path(artifact["artifact_path"]).exists() for artifact in artifacts)


@pytest.mark.asyncio
async def test_parent_cancellation_surfaces_unconfirmed_proxy_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = Path("/tmp/chainless-w4-parent-cleanup-error")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)
    parent_started = asyncio.Event()

    class Sandbox:
        async def execute_disposable_parent(self, **kwargs):
            parent_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise RuntimeError("disposable parent cleanup not confirmed")

    stream = stream_code_as_action(
        "block parent",
        Sandbox(),
        gateway=object(),
        tenant_id="tenant-a",
        parent_budget=20_000,
    )
    assert (await anext(stream))["phase"] == "allocated"
    next_event = asyncio.create_task(anext(stream))
    await parent_started.wait()
    next_event.cancel()
    with pytest.raises(RuntimeError, match="cleanup not confirmed"):
        await next_event

    assert SubAgentRuntime.global_active_count() == 0
    assert list(control_root.rglob("subagent.sock")) == []


@pytest.mark.asyncio
async def test_sub_agent_cannot_forge_unadvertised_tool_call() -> None:
    from app.core.agent.engine import run_agent

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            assert tools == []
            yield {
                "type": "tool_call",
                "index": 0,
                "id": "forged",
                "name": "shell_exec",
                "arguments": '{"malformed destructive payload"',
            }

    events = [
        event
        async for event in run_agent(
            Gateway(),
            object(),
            "default",
            [{"role": "user", "content": "forge"}],
            tools=[],
            is_sub_agent=True,
        )
    ]
    assert any(
        event["type"] == "tool_error" and "not authorized" in event["error"]
        for event in events
    )
    assert not any(
        event["type"] in {"tool_call_start", "confirmation_required"}
        for event in events
    )


@pytest.mark.asyncio
async def test_closing_after_allocated_still_revokes_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = Path("/tmp/chainless-w4-early-close")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)

    stream = stream_code_as_action(
        "never executed",
        object(),
        gateway=object(),
        tenant_id="tenant-a",
        parent_budget=20_000,
    )
    assert (await anext(stream))["phase"] == "allocated"
    await stream.aclose()

    assert SubAgentRuntime.global_active_count() == 0
    assert list(control_root.rglob("subagent.sock")) == []


@pytest.mark.asyncio
async def test_child_error_streams_canonical_terminal_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = Path("/tmp/chainless-w4-error")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            raise RuntimeError("child llm failed")
            if False:
                yield {}

    class Sandbox:
        async def allocate(self) -> str:
            return "error-child-sandbox"

        async def recycle(self, cid: str) -> str:
            return cid

        async def execute_disposable_parent(self, *, run_id, capability, script, timeout=30):
            response = await _rpc(
                control_root / run_id / "subagent.sock",
                capability,
                "fail",
            )
            return {
                "container_id": "error-parent",
                "deleted": True,
                "active_container_ids": [],
                "cleanup_errors": [],
                "stdout": json.dumps(response),
                "stderr": "",
            }

    events = [
        event
        async for event in stream_code_as_action(
            "spawn failing child",
            Sandbox(),
            gateway=Gateway(),
            tenant_id="tenant-a",
            parent_budget=20_000,
        )
    ]
    assert any(
        event["type"] == "sandbox"
        and event.get("phase") == "sub_agent_error"
        and event.get("container_id") == "error-child-sandbox"
        for event in events
    )
    artifacts = [
        json.loads(event["data"])
        for event in events
        if event.get("stream") == "artifact"
    ]
    assert [artifact["status"] for artifact in artifacts] == ["error"]
    assert all(not Path(artifact["artifact_path"]).exists() for artifact in artifacts)


@pytest.mark.asyncio
async def test_child_recycle_failure_streams_canonical_error_terminal_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = Path("/tmp/chainless-w4-recycle-error")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)

    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {"type": "text", "content": "finished before recycle"}

    class Sandbox:
        async def allocate(self) -> str:
            return "recycle-error-child"

        async def recycle(self, cid: str) -> str:
            raise RuntimeError("recycle failed")

        async def execute_disposable_parent(self, *, run_id, capability, script, timeout=30):
            response = await _rpc(
                control_root / run_id / "subagent.sock",
                capability,
                "fail recycle",
            )
            return {
                "container_id": "recycle-error-parent",
                "deleted": True,
                "active_container_ids": [],
                "cleanup_errors": [],
                "stdout": json.dumps(response),
                "stderr": "",
            }

    events = [
        event
        async for event in stream_code_as_action(
            "spawn child whose recycle fails",
            Sandbox(),
            gateway=Gateway(),
            tenant_id="tenant-a",
            parent_budget=20_000,
        )
    ]
    assert any(
        event.get("phase") == "sub_agent_error"
        and event.get("container_id") == "recycle-error-child"
        for event in events
    )
    assert any(
        event.get("stream") == "error"
        and "child sandbox cleanup failed: recycle failed" in event.get("data", "")
        for event in events
    )
    assert not any(event.get("phase") == "sub_agent_completed" for event in events)


@pytest.mark.asyncio
async def test_child_allocation_cancellation_waits_and_recycles() -> None:
    from app.core.agent.code_executor import _ChildSandboxContext

    allow_allocation = asyncio.Event()

    class Manager:
        recycled: list[str] = []

        async def allocate(self) -> str:
            await allow_allocation.wait()
            return "late-child"

        async def recycle(self, cid: str) -> str:
            self.recycled.append(cid)
            return cid

    manager = Manager()
    child = _ChildSandboxContext(manager)
    task = asyncio.create_task(child.start())
    await asyncio.sleep(0)
    task.cancel()
    allow_allocation.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.recycled == ["late-child"]


@pytest.mark.asyncio
async def test_child_allocation_repeated_cancellation_still_recycles() -> None:
    from app.core.agent.code_executor import _ChildSandboxContext

    allow_allocation = asyncio.Event()

    class Manager:
        recycled: list[str] = []

        async def allocate(self) -> str:
            await allow_allocation.wait()
            return "late-child"

        async def recycle(self, cid: str) -> str:
            self.recycled.append(cid)
            return cid

    manager = Manager()
    task = asyncio.create_task(_ChildSandboxContext(manager).start())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    allow_allocation.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.recycled == ["late-child"]


@pytest.mark.asyncio
async def test_child_allocation_error_streams_canonical_terminal_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = Path("/tmp/chainless-w4-allocation-error")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)

    class Sandbox:
        async def allocate(self) -> str:
            raise RuntimeError("allocation failed")

        async def execute_disposable_parent(self, *, run_id, capability, script, timeout=30):
            response = await _rpc(
                control_root / run_id / "subagent.sock",
                capability,
                "fail allocation",
            )
            return {
                "container_id": "allocation-error-parent",
                "stdout": json.dumps(response),
                "stderr": "",
            }

    events = [
        event
        async for event in stream_code_as_action(
            "spawn child whose allocation fails",
            Sandbox(),
            gateway=object(),
            tenant_id="tenant-a",
            parent_budget=20_000,
        )
    ]
    assert any(event.get("phase") == "sub_agent_allocating" for event in events)
    assert any(event.get("phase") == "sub_agent_error" for event in events)


@pytest.mark.asyncio
async def test_child_consumption_reduces_parent_turn_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.agent import engine

    control_root = Path("/tmp/chainless-w4-shared-budget")
    monkeypatch.setattr(settings, "subagent_control_root", str(control_root))
    monkeypatch.setattr(settings, "subagent_control_gid", 0)
    monkeypatch.setattr(engine, "MAX_TOKENS_PER_TURN", 3)

    class Gateway:
        parent_calls = 0

        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            if tools:
                self.parent_calls += 1
                yield {
                    "type": "tool_call",
                    "index": 0,
                    "id": "code",
                    "name": "code_as_action",
                    "arguments": '{"script": "spawn child"}',
                }
                return
            yield {"type": "text", "content": "child-one"}
            yield {"type": "text", "content": "child-two"}

    class Sandbox:
        async def allocate(self) -> str:
            return "budget-child"

        async def recycle(self, cid: str) -> str:
            return cid

        async def execute_disposable_parent(self, *, run_id, capability, script, timeout=30):
            response = await _rpc(
                control_root / run_id / "subagent.sock",
                capability,
                "consume budget",
            )
            return {
                "container_id": "budget-parent",
                "stdout": json.dumps(response),
                "stderr": "",
            }

    gateway = Gateway()
    events = [
        event
        async for event in engine.run_agent(
            gateway,
            Sandbox(),
            "default",
            [{"role": "user", "content": "run code"}],
            tools=[CODE_AS_ACTION_TOOL],
            tenant_id="tenant-a",
        )
    ]
    assert gateway.parent_calls == 1
    assert any(event.get("code") == "TOKEN_BUDGET_EXHAUSTED" for event in events)
    assert events[-1] == {"type": "done", "tokens_used": 3}
