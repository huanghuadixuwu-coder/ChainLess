"""Deterministic lifecycle tests for the backend-owned sub-agent runtime."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import threading
import time
from pathlib import Path

import pytest

from app.core.agent.subagents import (
    DEFAULT_SUB_AGENT_TIMEOUT_SECONDS,
    BudgetExhausted,
    ChildRunInactive,
    DepthLimitExceeded,
    ParallelismLimitExceeded,
    ParentBudget,
    ParentRunCancelled,
    RunnerResult,
    SubAgentRunner,
    SubAgentRuntime,
    bind_sub_agent_runtime,
    spawn_sub_agent,
)

pytestmark = pytest.mark.asyncio

_TEST_WAIT_SECONDS = 3.0


async def _wait_event(event: asyncio.Event) -> None:
    await asyncio.wait_for(event.wait(), timeout=_TEST_WAIT_SECONDS)


async def _wait_until(predicate) -> None:
    async def wait_loop() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_loop(), timeout=_TEST_WAIT_SECONDS)


async def _wait_for_first_done(tasks: set[asyncio.Task]) -> set[asyncio.Task]:
    async def wait() -> set[asyncio.Task]:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        return done

    return await asyncio.wait_for(wait(), timeout=_TEST_WAIT_SECONDS)


async def _gather_bounded(*awaitables, return_exceptions: bool = False):
    return await asyncio.wait_for(
        asyncio.gather(*awaitables, return_exceptions=return_exceptions),
        timeout=_TEST_WAIT_SECONDS,
    )


async def _await_bounded(awaitable):
    return (await _gather_bounded(awaitable))[0]


def _expire_after(event: asyncio.Event):
    async def waiter(tasks: set[asyncio.Task]) -> set[asyncio.Task]:
        await _wait_event(event)
        return set()

    return waiter


def _expire_after_thread_event(event: threading.Event):
    async def waiter(tasks: set[asyncio.Task]) -> set[asyncio.Task]:
        await _wait_until(event.is_set)
        return set()

    return waiter


def _expire_on_wait_call(target_call: int):
    calls = 0

    async def waiter(tasks: set[asyncio.Task]) -> set[asyncio.Task]:
        nonlocal calls
        calls += 1
        if calls == target_call:
            await asyncio.sleep(0)
            return set()
        return await _wait_for_first_done(tasks)

    return waiter


async def test_parallel_children_succeed_with_isolated_runners(tmp_path: Path) -> None:
    started = 0
    release = asyncio.Event()
    runner_ids: list[int] = []

    def runner_factory():
        nonlocal started
        runner_id = len(runner_ids)
        runner_ids.append(runner_id)

        async def runner(prompt, context, execution):
            nonlocal started
            started += 1
            if started == 3:
                release.set()
            await _wait_event(release)
            await execution.consume_budget(2)
            return RunnerResult(f"{runner_id}:{prompt}:{context}", tokens_used=2)

        return runner

    runtime = SubAgentRuntime(runner_factory, artifact_root=tmp_path, child_budget=4)
    runtime.register_parent("parent", budget=20)

    with bind_sub_agent_runtime(runtime):
        results = await _gather_bounded(
            *[
                spawn_sub_agent(f"prompt-{index}", "ctx", parent_run_id="parent", depth=1)
                for index in range(3)
            ]
        )

    assert {result.status for result in results} == {"success"}
    assert len(set(runner_ids)) == 3
    assert runtime.parent_budget("parent").consumed == 6
    assert runtime.active_count("parent") == 0


async def test_depth_greater_than_one_is_rejected(tmp_path: Path) -> None:
    runtime = SubAgentRuntime(
        lambda: _successful_runner,
        artifact_root=tmp_path,
        child_budget=1,
    )
    runtime.register_parent("parent", budget=10)

    with bind_sub_agent_runtime(runtime):
        with pytest.raises(DepthLimitExceeded):
            await spawn_sub_agent("prompt", parent_run_id="parent", depth=2)


async def test_sixth_parallel_child_is_rejected_instead_of_queued(tmp_path: Path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    start_count = 0

    def runner_factory():
        async def runner(prompt, context, execution):
            nonlocal start_count
            start_count += 1
            if start_count == 5:
                started.set()
            await _wait_event(release)
            await execution.consume_budget(1)
            return RunnerResult(prompt, tokens_used=1)

        return runner

    runtime = SubAgentRuntime(runner_factory, artifact_root=tmp_path, child_budget=1)
    runtime.register_parent("parent", budget=10)

    with bind_sub_agent_runtime(runtime):
        tasks = [
            asyncio.create_task(
                spawn_sub_agent(str(index), parent_run_id="parent", depth=1)
            )
            for index in range(5)
        ]
        await _wait_event(started)

        with pytest.raises(ParallelismLimitExceeded):
            await spawn_sub_agent("sixth", parent_run_id="parent", depth=1)

        release.set()
        await _gather_bounded(*tasks)


async def test_sixth_parallel_child_across_parents_is_rejected(tmp_path: Path) -> None:
    all_started = asyncio.Event()
    release = asyncio.Event()
    start_count = 0

    def runner_factory():
        async def runner(prompt, context, execution):
            nonlocal start_count
            start_count += 1
            if start_count == 5:
                all_started.set()
            await _wait_event(release)
            await execution.consume_budget(1)
            return RunnerResult(prompt, tokens_used=1)

        return runner

    runtime = SubAgentRuntime(runner_factory, artifact_root=tmp_path, child_budget=1)
    runtime.register_parent("parent-a", budget=10)
    runtime.register_parent("parent-b", budget=10)

    with bind_sub_agent_runtime(runtime):
        tasks = [
            asyncio.create_task(
                spawn_sub_agent(
                    str(index),
                    parent_run_id="parent-a" if index < 3 else "parent-b",
                    depth=1,
                )
            )
            for index in range(5)
        ]
        await _wait_event(all_started)

        with pytest.raises(ParallelismLimitExceeded):
            await spawn_sub_agent("sixth", parent_run_id="parent-b", depth=1)

        release.set()
        await _gather_bounded(*tasks)


async def test_sixth_parallel_child_across_runtimes_is_rejected_and_slot_released(
    tmp_path: Path,
) -> None:
    all_started = asyncio.Event()
    release = asyncio.Event()
    start_count = 0

    def runner_factory():
        async def runner(prompt, context, execution):
            nonlocal start_count
            start_count += 1
            if start_count == 5:
                all_started.set()
            await _wait_event(release)
            await execution.consume_budget(1)
            return RunnerResult(prompt, tokens_used=1)

        return runner

    runtime_a = SubAgentRuntime(runner_factory, artifact_root=tmp_path, child_budget=1)
    runtime_b = SubAgentRuntime(runner_factory, artifact_root=tmp_path, child_budget=1)
    runtime_a.register_parent("parent-a", budget=10)
    runtime_b.register_parent("parent-b", budget=10)

    tasks = [
        asyncio.create_task(
            runtime_a.spawn_sub_agent(str(index), parent_run_id="parent-a", depth=1)
        )
        for index in range(3)
    ]
    tasks.extend(
        asyncio.create_task(
            runtime_b.spawn_sub_agent(str(index), parent_run_id="parent-b", depth=1)
        )
        for index in range(3, 5)
    )
    await _wait_event(all_started)

    with pytest.raises(ParallelismLimitExceeded):
        await runtime_b.spawn_sub_agent("sixth", parent_run_id="parent-b", depth=1)

    release.set()
    await _gather_bounded(*tasks)
    after_release = await runtime_b.spawn_sub_agent(
        "after-release",
        parent_run_id="parent-b",
        depth=1,
    )

    assert after_release.status == "success"


async def test_timeout_preserves_runner_partial_result(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def runner(prompt, context, execution):
        execution.set_partial_result("useful partial")
        started.set()
        await asyncio.sleep(10)
        return RunnerResult("unreachable", tokens_used=1)

    runtime = SubAgentRuntime(
        lambda: runner,
        artifact_root=tmp_path,
        _deadline_waiter=_expire_after(started),
        child_budget=3,
    )
    runtime.register_parent("parent", budget=3)

    with bind_sub_agent_runtime(runtime):
        result = await spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert result.status == "timeout"
    assert result.output == "useful partial"
    assert result.error == "timed out after 15s"


@pytest.mark.parametrize("terminal", ["timeout", "error"])
async def test_terminal_budget_penalty_is_charged_to_shared_parent_ledger(
    tmp_path: Path,
    terminal: str,
) -> None:
    charges: list[int] = []
    started = asyncio.Event()

    async def parent_consumer(amount: int) -> None:
        charges.append(amount)

    async def runner(prompt, context, execution):
        if terminal == "error":
            await execution.consume_budget(1)
            raise RuntimeError("boom")
        started.set()
        await asyncio.sleep(10)
        return RunnerResult("unreachable", tokens_used=0)

    runtime = SubAgentRuntime(
        lambda: runner,
        artifact_root=tmp_path,
        _deadline_waiter=_expire_after(started) if terminal == "timeout" else None,
        child_budget=3,
        parent_budget_consumer=parent_consumer,
    )
    runtime.register_parent("parent", budget=3)

    result = await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert result.status == terminal
    assert sum(charges) == 3
    assert runtime.parent_budget("parent").consumed == 3


async def test_timeout_is_authoritative_when_runner_swallows_cancellation(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    swallowed = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    late_budget_error = None

    async def runner(prompt, context, execution):
        nonlocal late_budget_error
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            swallowed.set()
            try:
                await execution.consume_budget(1)
            except Exception as exc:
                late_budget_error = exc
            await _wait_event(release)
        finally:
            finished.set()
        return RunnerResult("late success", tokens_used=0)

    runtime = SubAgentRuntime(
        lambda: runner,
        artifact_root=tmp_path,
        _deadline_waiter=_expire_after(started),
        child_budget=1,
    )
    runtime.register_parent("parent", budget=1)

    result = await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert result.status == "timeout"
    assert result.output == ""
    await _wait_event(swallowed)
    assert isinstance(late_budget_error, ChildRunInactive)
    assert runtime.active_count("parent") == 1
    assert runtime.global_active_count() == 1
    release.set()
    await _wait_event(finished)
    await _wait_until(lambda: runtime.active_count("parent") == 0)
    assert runtime.global_active_count() == 0
    assert runtime.parent_budget("parent").consumed == 1


async def test_shared_parent_budget_exhaustion_is_atomic(tmp_path: Path) -> None:
    release = asyncio.Event()
    started = asyncio.Event()

    async def runner(prompt, context, execution):
        started.set()
        await _wait_event(release)
        await execution.consume_budget(3)
        return RunnerResult(prompt, tokens_used=3)

    runtime = SubAgentRuntime(
        lambda: runner,
        artifact_root=tmp_path,
        child_budget=3,
    )
    runtime.register_parent("parent", budget=3)

    with bind_sub_agent_runtime(runtime):
        first = asyncio.create_task(
            spawn_sub_agent("first", parent_run_id="parent", depth=1)
        )
        await _wait_event(started)

        with pytest.raises(BudgetExhausted):
            await spawn_sub_agent("second", parent_run_id="parent", depth=1)

        budget = runtime.parent_budget("parent")
        assert budget.consumed + budget.reserved <= budget.limit
        release.set()
        await _await_bounded(first)

    budget = runtime.parent_budget("parent")
    assert budget.consumed == budget.limit == 3
    assert budget.reserved == 0


async def test_child_budget_is_rejected_during_run_and_accounted_atomically(
    tmp_path: Path,
) -> None:
    observed_budget = None

    async def runner(prompt, context, execution):
        nonlocal observed_budget
        await execution.consume_budget(2)
        observed_budget = runtime.parent_budget("parent")
        await execution.consume_budget(2)
        return RunnerResult("unreachable", tokens_used=4)

    runtime = SubAgentRuntime(
        lambda: runner,
        artifact_root=tmp_path,
        child_budget=3,
    )
    runtime.register_parent("parent", budget=3)

    with bind_sub_agent_runtime(runtime):
        result = await spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert observed_budget is not None
    assert observed_budget.consumed == 2
    assert observed_budget.reserved == 1
    assert observed_budget.consumed + observed_budget.reserved <= observed_budget.limit
    assert result.status == "error"
    assert result.error == "child budget exhausted: 2 requested, 1 remaining"
    budget = runtime.parent_budget("parent")
    assert budget.consumed == 3
    assert budget.reserved == 0
    assert budget.consumed + budget.reserved <= budget.limit


async def test_runner_result_cannot_hide_streamed_budget_consumption(
    tmp_path: Path,
) -> None:
    async def runner(prompt, context, execution):
        await execution.consume_budget(2)
        return RunnerResult("underreported", tokens_used=1)

    runtime = SubAgentRuntime(
        lambda: runner,
        artifact_root=tmp_path,
        child_budget=3,
    )
    runtime.register_parent("parent", budget=3)

    with bind_sub_agent_runtime(runtime):
        result = await spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert result.status == "error"
    assert result.tokens_used == 2
    assert result.error == "runner reported 1 tokens after consuming 2"
    budget = runtime.parent_budget("parent")
    assert budget.consumed == 2
    assert budget.reserved == 0


async def test_unaccounted_late_runner_result_is_rejected(tmp_path: Path) -> None:
    async def runner(prompt, context, execution):
        return RunnerResult("late-only", tokens_used=1)

    runtime = SubAgentRuntime(
        lambda: runner,
        artifact_root=tmp_path,
        child_budget=3,
    )
    runtime.register_parent("parent", budget=3)

    with bind_sub_agent_runtime(runtime):
        result = await spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert result.status == "error"
    assert result.error == "runner must consume budget during execution"
    assert runtime.parent_budget("parent").consumed == 3


async def test_zero_only_budget_consumption_is_unaccounted(tmp_path: Path) -> None:
    async def runner(prompt, context, execution):
        await execution.consume_budget(0)
        return RunnerResult("zero-only", tokens_used=0)

    runtime = SubAgentRuntime(
        lambda: runner,
        artifact_root=tmp_path,
        child_budget=3,
    )
    runtime.register_parent("parent", budget=3)

    result = await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert result.status == "error"
    assert result.error == "runner must consume budget during execution"
    assert runtime.parent_budget("parent").consumed == 3


async def test_success_timeout_and_error_results_are_written_per_run(
    tmp_path: Path,
) -> None:
    calls = 0

    def runner_factory():
        nonlocal calls
        calls += 1
        call = calls

        async def runner(prompt, context, execution):
            if call == 1:
                await execution.consume_budget(1)
                return RunnerResult("ok", tokens_used=1)
            if call == 2:
                execution.set_partial_result("partial")
                await asyncio.sleep(10)
            raise RuntimeError("boom")

        return runner

    runtime = SubAgentRuntime(
        runner_factory,
        artifact_root=tmp_path,
        _deadline_waiter=_expire_on_wait_call(2),
        child_budget=2,
    )
    runtime.register_parent("parent", budget=6)

    with bind_sub_agent_runtime(runtime):
        results = [
            await spawn_sub_agent(str(index), parent_run_id="parent", depth=1)
            for index in range(3)
        ]

    result_dir = tmp_path / "runs" / "parent" / "sub_results"
    files = sorted(result_dir.glob("*.json"))
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in files]

    assert len(files) == 3
    assert {payload["status"] for payload in payloads} == {
        "success",
        "timeout",
        "error",
    }
    assert {result.artifact_path for result in results} == {
        str(path) for path in files
    }
    await runtime.cancel_parent("parent")
    snapshots = await runtime.finalize_parent_artifacts("parent")
    assert {snapshot["status"] for snapshot in snapshots} == {
        "success",
        "timeout",
        "error",
    }
    assert not result_dir.exists()


async def test_terminal_parent_artifacts_are_observed_then_removed_by_runtime_owner(
    tmp_path: Path,
) -> None:
    runtime = SubAgentRuntime(
        lambda: _successful_runner,
        artifact_root=tmp_path,
        child_budget=1,
    )
    runtime.register_parent("parent", budget=2)
    first, second = await asyncio.gather(
        runtime.spawn_sub_agent("first", parent_run_id="parent", depth=1),
        runtime.spawn_sub_agent("second", parent_run_id="parent", depth=1),
    )
    result_dir = tmp_path / "runs" / "parent" / "sub_results"
    assert result_dir.exists()

    with pytest.raises(RuntimeError, match="while run is active"):
        await runtime.finalize_parent_artifacts("parent")

    await runtime.cancel_parent("parent")
    snapshots = await runtime.finalize_parent_artifacts("parent")

    assert {snapshot["run_id"] for snapshot in snapshots} == {
        first.run_id,
        second.run_id,
    }
    assert {snapshot["status"] for snapshot in snapshots} == {"success"}
    assert not result_dir.exists()
    assert not (tmp_path / "runs" / "parent").exists()
    assert await runtime.finalize_parent_artifacts("parent") == []


async def test_foreign_runtime_cannot_observe_or_remove_parent_artifacts(
    tmp_path: Path,
) -> None:
    owner = SubAgentRuntime(lambda: _successful_runner, artifact_root=tmp_path)
    foreign = SubAgentRuntime(lambda: _successful_runner, artifact_root=tmp_path)
    owner.register_parent("tenant-a-parent", budget=1)
    result = await owner.spawn_sub_agent(
        "owned",
        parent_run_id="tenant-a-parent",
        depth=1,
    )
    await owner.cancel_parent("tenant-a-parent")
    foreign.register_parent("tenant-a-parent", budget=1)
    await foreign.cancel_parent("tenant-a-parent")

    with pytest.raises(OSError, match="owner mismatch"):
        await foreign.finalize_parent_artifacts("tenant-a-parent")

    assert Path(result.artifact_path).exists()
    await owner.finalize_parent_artifacts("tenant-a-parent")
    assert not Path(result.artifact_path).exists()


async def test_artifact_cleanup_rejects_symlink_without_path_escape(
    tmp_path: Path,
) -> None:
    runtime = SubAgentRuntime(lambda: _successful_runner, artifact_root=tmp_path)
    runtime.register_parent("parent", budget=1)
    result = await runtime.spawn_sub_agent("owned", parent_run_id="parent", depth=1)
    await runtime.cancel_parent("parent")
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "keep.txt"
    outside_file.write_text("keep", encoding="utf-8")
    Path(result.artifact_path).unlink()
    Path(result.artifact_path).symlink_to(outside_file)

    with pytest.raises(OSError, match="unexpected non-file"):
        await runtime.finalize_parent_artifacts("parent")

    assert outside_file.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "symlink_component",
    ["runs", "parent", "sub_results", "target"],
)
async def test_result_write_rejects_existing_symlink_components_without_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    symlink_component: str,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    runs = artifact_root / "runs"
    parent = runs / "parent"
    sub_results = parent / "sub_results"
    target = sub_results / "fixed-child.json"

    if symlink_component == "runs":
        runs.symlink_to(outside, target_is_directory=True)
    else:
        runs.mkdir()
        if symlink_component == "parent":
            parent.symlink_to(outside, target_is_directory=True)
        else:
            parent.mkdir()
            if symlink_component == "sub_results":
                sub_results.symlink_to(outside, target_is_directory=True)
            else:
                sub_results.mkdir()
                target.symlink_to(outside / "escaped.json")

    monkeypatch.setattr(
        "app.core.agent.subagents.uuid.uuid4",
        lambda: type("FixedUuid", (), {"hex": "fixed-child"})(),
    )
    runtime = SubAgentRuntime(lambda: _successful_runner, artifact_root=artifact_root)
    runtime.register_parent("parent", budget=1)

    with pytest.raises(OSError):
        await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert not any(path.is_file() for path in outside.rglob("*"))


async def test_result_persistence_does_not_block_owner_loop_and_survives_repeated_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_started = threading.Event()
    release_write = threading.Event()
    original_write = SubAgentRuntime._write_result

    def blocking_write(path, result):
        write_started.set()
        release_write.wait()
        original_write(path, result)

    runtime = SubAgentRuntime(lambda: _successful_runner, artifact_root=tmp_path)
    runtime.register_parent("parent", budget=1)
    monkeypatch.setattr(runtime, "_write_result", blocking_write)
    spawn_task = asyncio.create_task(
        runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)
    )

    try:
        await _wait_until(write_started.is_set)
        assert not spawn_task.done()

        spawn_task.cancel()
        await asyncio.sleep(0)
        spawn_task.cancel()
        assert not spawn_task.done()
    finally:
        release_write.set()

    result = await _await_bounded(spawn_task)

    assert result.status == "success"
    assert json.loads(Path(result.artifact_path).read_text(encoding="utf-8"))[
        "status"
    ] == "success"


async def test_result_is_atomically_published_only_after_complete_temp_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rename_started = threading.Event()
    release_rename = threading.Event()
    original_rename = os.rename
    target = tmp_path / "runs" / "parent" / "sub_results" / "fixed-child.json"

    def blocking_rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        rename_started.set()
        release_rename.wait()
        return original_rename(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(
        "app.core.agent.subagents.uuid.uuid4",
        lambda: type("FixedUuid", (), {"hex": "fixed-child"})(),
    )
    monkeypatch.setattr("app.core.agent.subagents.os.rename", blocking_rename)
    runtime = SubAgentRuntime(lambda: _successful_runner, artifact_root=tmp_path)
    runtime.register_parent("parent", budget=1)
    spawn_task = asyncio.create_task(
        runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)
    )

    try:
        await _wait_until(rename_started.is_set)
        assert not target.exists()
        temp_files = list(target.parent.iterdir())
        assert len(temp_files) == 1
        assert temp_files[0].name.startswith(".fixed-child.json.")
        assert temp_files[0].name.endswith(".tmp")
    finally:
        release_rename.set()

    result = await _await_bounded(spawn_task)

    assert Path(result.artifact_path) == target
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "success"
    assert [path.name for path in target.parent.iterdir()] == ["fixed-child.json"]


async def test_result_publish_failure_removes_temp_and_never_exposes_final_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "runs" / "parent" / "sub_results" / "fixed-child.json"

    def failing_rename(*args, **kwargs):
        raise OSError("rename boom")

    monkeypatch.setattr(
        "app.core.agent.subagents.uuid.uuid4",
        lambda: type("FixedUuid", (), {"hex": "fixed-child"})(),
    )
    monkeypatch.setattr("app.core.agent.subagents.os.rename", failing_rename)
    runtime = SubAgentRuntime(lambda: _successful_runner, artifact_root=tmp_path)
    runtime.register_parent("parent", budget=1)

    with pytest.raises(OSError, match="rename boom"):
        await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert not target.exists()
    assert list(target.parent.iterdir()) == []
    await runtime.cancel_parent("parent")
    assert await runtime.finalize_parent_artifacts("parent") == []
    assert not (tmp_path / "runs" / "parent").exists()


async def test_relative_artifact_root_is_rejected() -> None:
    with pytest.raises(ValueError, match="absolute POSIX path"):
        SubAgentRuntime(lambda: _successful_runner, artifact_root="relative/artifacts")


async def test_parent_cancellation_cancels_children_and_invalidates_context(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    cancelled = 0

    def runner_factory():
        async def runner(prompt, context, execution):
            nonlocal cancelled
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled += 1
                raise

        return runner

    runtime = SubAgentRuntime(runner_factory, artifact_root=tmp_path, child_budget=1)
    runtime.register_parent("parent", budget=5)

    with bind_sub_agent_runtime(runtime):
        tasks = [
            asyncio.create_task(
                spawn_sub_agent(str(index), parent_run_id="parent", depth=1)
            )
            for index in range(3)
        ]
        await _wait_event(started)
        await _wait_until(lambda: runtime.active_count("parent") == 3)
        await runtime.cancel_parent("parent")
        results = await _gather_bounded(*tasks)

        with pytest.raises(ParentRunCancelled):
            await spawn_sub_agent("orphan", parent_run_id="parent", depth=1)

    assert cancelled == 3
    assert {result.status for result in results} == {"cancelled"}
    assert runtime.active_count("parent") == 0
    assert runtime.parent_budget("parent").reserved == 0


async def test_parent_cancellation_is_authoritative_when_runner_swallows_cancel(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    swallowed = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    late_budget_error = None

    async def runner(prompt, context, execution):
        nonlocal late_budget_error
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            swallowed.set()
            try:
                await execution.consume_budget(1)
            except Exception as exc:
                late_budget_error = exc
            await _wait_event(release)
        finally:
            finished.set()
        return RunnerResult("late success", tokens_used=0)

    runtime = SubAgentRuntime(lambda: runner, artifact_root=tmp_path, child_budget=1)
    runtime.register_parent("parent", budget=1)
    spawn_task = asyncio.create_task(
        runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)
    )
    await _wait_event(started)

    cancellation = asyncio.create_task(runtime.cancel_parent("parent"))
    await _wait_event(swallowed)
    assert not cancellation.done()
    assert runtime.active_count("parent") == 1
    release.set()
    await _await_bounded(cancellation)
    result = await _await_bounded(spawn_task)

    assert result.status == "cancelled"
    assert isinstance(late_budget_error, ChildRunInactive)
    await _wait_event(finished)
    assert runtime.active_count("parent") == 0
    budget = runtime.parent_budget("parent")
    assert budget.consumed == 0
    assert budget.reserved == 0


async def test_parent_quiescence_waits_for_cancelled_result_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_started = asyncio.Event()
    write_started = threading.Event()
    release_write = threading.Event()
    original_write = SubAgentRuntime._write_result

    async def runner(prompt, context, execution):
        runner_started.set()
        await asyncio.sleep(10)
        return RunnerResult("late success", tokens_used=0)

    def blocking_write(path, result):
        write_started.set()
        release_write.wait()
        original_write(path, result)

    runtime = SubAgentRuntime(lambda: runner, artifact_root=tmp_path, child_budget=1)
    runtime.register_parent("parent", budget=1)
    monkeypatch.setattr(runtime, "_write_result", blocking_write)
    spawn_task = asyncio.create_task(
        runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)
    )
    await _wait_event(runner_started)

    cancellation = asyncio.create_task(runtime.cancel_parent("parent"))
    try:
        await _wait_until(write_started.is_set)
        assert not cancellation.done()
    finally:
        release_write.set()

    await _await_bounded(cancellation)
    result = await _await_bounded(spawn_task)
    snapshots = await runtime.finalize_parent_artifacts("parent")

    assert result.status == "cancelled"
    assert [snapshot["status"] for snapshot in snapshots] == ["cancelled"]
    assert not (tmp_path / "runs" / "parent").exists()


async def test_retained_execution_context_is_invalid_after_success(
    tmp_path: Path,
) -> None:
    retained = None

    async def runner(prompt, context, execution):
        nonlocal retained
        retained = execution
        await execution.consume_budget(1)
        return RunnerResult("ok", tokens_used=1)

    runtime = SubAgentRuntime(lambda: runner, artifact_root=tmp_path, child_budget=2)
    runtime.register_parent("parent", budget=2)
    result = await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)
    before = runtime.parent_budget("parent")

    assert result.status == "success"
    assert retained is not None
    with pytest.raises(ChildRunInactive):
        await retained.consume_budget(1)
    with pytest.raises(ChildRunInactive):
        retained.set_partial_result("late")
    with pytest.raises(ChildRunInactive):
        _ = retained.budget_consumed
    with pytest.raises(ChildRunInactive):
        _ = retained.partial_result
    after = runtime.parent_budget("parent")
    assert after == before
    assert after.consumed + after.reserved <= after.limit


async def test_caller_cancellation_tombstones_parent_and_cancels_sibling(
    tmp_path: Path,
) -> None:
    both_started = asyncio.Event()
    started = 0
    cancelled = 0

    async def runner(prompt, context, execution):
        nonlocal started, cancelled
        started += 1
        if started == 2:
            both_started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled += 1
            raise

    runtime = SubAgentRuntime(lambda: runner, artifact_root=tmp_path, child_budget=1)
    runtime.register_parent("parent", budget=2)
    first = asyncio.create_task(
        runtime.spawn_sub_agent("first", parent_run_id="parent", depth=1)
    )
    sibling = asyncio.create_task(
        runtime.spawn_sub_agent("sibling", parent_run_id="parent", depth=1)
    )
    await _wait_event(both_started)

    first.cancel()
    results = await _gather_bounded(first, sibling)

    assert {result.status for result in results} == {"cancelled"}
    assert cancelled == 2
    with pytest.raises(ParentRunCancelled):
        await runtime.spawn_sub_agent("late", parent_run_id="parent", depth=1)
    with pytest.raises(ParentRunCancelled):
        runtime.register_parent("parent", budget=2)
    assert runtime.parent_budget("parent").reserved == 0


async def test_caller_cancellation_while_reserving_tombstones_parent_without_leaks(
    tmp_path: Path,
) -> None:
    sibling_started = asyncio.Event()

    async def runner(prompt, context, execution):
        sibling_started.set()
        await asyncio.sleep(10)

    runtime = SubAgentRuntime(lambda: runner, artifact_root=tmp_path, child_budget=1)
    runtime.register_parent("parent", budget=2)
    global_before = runtime.global_active_count()
    sibling = asyncio.create_task(
        runtime.spawn_sub_agent("sibling", parent_run_id="parent", depth=1)
    )
    await _wait_event(sibling_started)
    state = runtime._existing_parent_state("parent")
    await asyncio.wait_for(state.lock.acquire(), timeout=_TEST_WAIT_SECONDS)
    blocked = asyncio.create_task(
        runtime.spawn_sub_agent("blocked", parent_run_id="parent", depth=1)
    )
    await asyncio.sleep(0)

    try:
        blocked.cancel()
        state.lock.release()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(blocked, timeout=_TEST_WAIT_SECONDS)

        assert state.valid is False
        sibling_result = await asyncio.wait_for(sibling, timeout=_TEST_WAIT_SECONDS)
        assert sibling_result.status == "cancelled"
        assert runtime.active_count("parent") == 0
        assert runtime.global_active_count() == global_before
        assert runtime.parent_budget("parent") == ParentBudget(2, 0, 0)
        with pytest.raises(ParentRunCancelled):
            await runtime.spawn_sub_agent("late", parent_run_id="parent", depth=1)
    finally:
        if state.lock.locked():
            state.lock.release()
        if state.valid:
            await runtime.cancel_parent("parent")
        await _gather_bounded(sibling, return_exceptions=True)


async def test_repeated_caller_cancellation_while_reserving_cannot_interrupt_cleanup(
    tmp_path: Path,
) -> None:
    sibling_started = asyncio.Event()

    async def runner(prompt, context, execution):
        sibling_started.set()
        await asyncio.sleep(10)

    runtime = SubAgentRuntime(lambda: runner, artifact_root=tmp_path, child_budget=1)
    runtime.register_parent("parent", budget=2)
    global_before = runtime.global_active_count()
    sibling = asyncio.create_task(
        runtime.spawn_sub_agent("sibling", parent_run_id="parent", depth=1)
    )
    await _wait_event(sibling_started)
    state = runtime._existing_parent_state("parent")
    await asyncio.wait_for(state.lock.acquire(), timeout=_TEST_WAIT_SECONDS)
    blocked = asyncio.create_task(
        runtime.spawn_sub_agent("blocked", parent_run_id="parent", depth=1)
    )
    await asyncio.sleep(0)

    try:
        blocked.cancel()
        await asyncio.sleep(0)
        blocked.cancel()
        state.lock.release()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(blocked, timeout=_TEST_WAIT_SECONDS)

        assert state.valid is False
        sibling_result = await asyncio.wait_for(sibling, timeout=_TEST_WAIT_SECONDS)
        assert sibling_result.status == "cancelled"
        assert runtime.active_count("parent") == 0
        assert runtime.global_active_count() == global_before
        assert runtime.parent_budget("parent") == ParentBudget(2, 0, 0)
    finally:
        if state.lock.locked():
            state.lock.release()
        if state.valid:
            await runtime.cancel_parent("parent")
        await _gather_bounded(sibling, return_exceptions=True)


async def test_repeated_caller_cancellation_during_run_cannot_interrupt_cleanup(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()

    async def runner(prompt, context, execution):
        started.set()
        await asyncio.sleep(10)

    runtime = SubAgentRuntime(lambda: runner, artifact_root=tmp_path, child_budget=1)
    runtime.register_parent("parent", budget=1)
    global_before = runtime.global_active_count()
    spawn_task = asyncio.create_task(
        runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)
    )
    await _wait_event(started)
    state = runtime._existing_parent_state("parent")
    await asyncio.wait_for(state.lock.acquire(), timeout=_TEST_WAIT_SECONDS)

    try:
        spawn_task.cancel()
        await asyncio.sleep(0)
        spawn_task.cancel()
        state.lock.release()
        result = await asyncio.wait_for(spawn_task, timeout=_TEST_WAIT_SECONDS)

        assert result.status == "cancelled"
        assert state.valid is False
        assert runtime.active_count("parent") == 0
        assert runtime.global_active_count() == global_before
        assert runtime.parent_budget("parent") == ParentBudget(1, 0, 0)
    finally:
        if state.lock.locked():
            state.lock.release()
        if state.valid:
            await runtime.cancel_parent("parent")
        await _gather_bounded(spawn_task, return_exceptions=True)


async def test_concurrent_caller_cancellations_are_idempotent_and_write_results(
    tmp_path: Path,
) -> None:
    both_started = asyncio.Event()
    started = 0

    async def runner(prompt, context, execution):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.sleep(10)

    runtime = SubAgentRuntime(lambda: runner, artifact_root=tmp_path, child_budget=1)
    runtime.register_parent("parent", budget=2)
    first = asyncio.create_task(
        runtime.spawn_sub_agent("first", parent_run_id="parent", depth=1)
    )
    second = asyncio.create_task(
        runtime.spawn_sub_agent("second", parent_run_id="parent", depth=1)
    )
    await _wait_event(both_started)

    first.cancel()
    second.cancel()
    results = await _gather_bounded(first, second)
    await runtime.cancel_parent("parent")

    assert {result.status for result in results} == {"cancelled"}
    result_dir = tmp_path / "runs" / "parent" / "sub_results"
    payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in result_dir.glob("*.json")
    ]
    assert len(payloads) == 2
    assert {payload["status"] for payload in payloads} == {"cancelled"}
    with pytest.raises(ParentRunCancelled):
        await runtime.spawn_sub_agent("late", parent_run_id="parent", depth=1)
    with pytest.raises(ParentRunCancelled):
        runtime.register_parent("parent", budget=2)


async def test_runner_factory_failure_fully_cleans_up_child(tmp_path: Path) -> None:
    def failing_factory():
        raise RuntimeError("factory boom")

    runtime = SubAgentRuntime(failing_factory, artifact_root=tmp_path, child_budget=2)
    runtime.register_parent("parent", budget=2)
    global_before = runtime.global_active_count()

    result = await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert result.status == "error"
    assert result.error == "factory boom"
    assert runtime.active_count("parent") == 0
    assert runtime.global_active_count() == global_before
    budget = runtime.parent_budget("parent")
    assert budget.consumed == 0
    assert budget.reserved == 0
    assert budget.consumed + budget.reserved <= budget.limit


@pytest.mark.parametrize("factory_result", [None, 42])
async def test_non_callable_factory_result_is_creation_error_without_budget_charge(
    tmp_path: Path,
    factory_result,
) -> None:
    runtime = SubAgentRuntime(
        lambda: factory_result,
        artifact_root=tmp_path,
        child_budget=2,
    )
    runtime.register_parent("parent", budget=2)
    global_before = runtime.global_active_count()

    result = await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert result.status == "error"
    assert result.error == "runner factory must return a callable runner"
    assert runtime.active_count("parent") == 0
    assert runtime.global_active_count() == global_before
    assert runtime.parent_budget("parent") == ParentBudget(2, 0, 0)


async def test_sync_callable_runners_are_creation_errors_without_invocation_or_leaks(
    tmp_path: Path,
) -> None:
    called: list[str] = []

    def sync_runner(prompt, context, execution):
        called.append("function")
        time.sleep(0.05)
        return RunnerResult("sync function", tokens_used=0)

    class SyncCallableRunner:
        def __call__(self, prompt, context, execution):
            called.append("object")
            time.sleep(0.05)
            return RunnerResult("sync object", tokens_used=0)

    global_before = SubAgentRuntime.global_active_count()
    for index, runner in enumerate((sync_runner, SyncCallableRunner())):
        runtime = SubAgentRuntime(
            lambda runner=runner: runner,
            artifact_root=tmp_path / str(index),
            child_budget=2,
        )
        runtime.register_parent("parent", budget=2)

        result = await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

        assert result.status == "error"
        assert result.error == "runner factory must return an async callable runner"
        assert runtime.active_count("parent") == 0
        assert runtime.parent_budget("parent") == ParentBudget(2, 0, 0)

    assert called == []
    assert SubAgentRuntime.global_active_count() == global_before


async def test_async_callable_object_runner_is_supported(tmp_path: Path) -> None:
    class AsyncCallableRunner:
        async def __call__(self, prompt, context, execution):
            await execution.consume_budget(1)
            return RunnerResult(prompt, tokens_used=1)

    runtime = SubAgentRuntime(
        lambda: AsyncCallableRunner(),
        artifact_root=tmp_path,
        child_budget=2,
    )
    runtime.register_parent("parent", budget=2)

    result = await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    assert result.status == "success"
    assert result.output == "prompt"
    assert runtime.active_count("parent") == 0
    assert runtime.parent_budget("parent") == ParentBudget(2, 1, 0)


async def test_runner_task_creation_failure_fully_cleans_up_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_coroutines = []

    def failing_create_task(coroutine):
        captured_coroutines.append(coroutine)
        raise RuntimeError("task creation boom")

    runtime = SubAgentRuntime(lambda: _successful_runner, artifact_root=tmp_path)
    runtime.register_parent("parent", budget=2)
    global_before = runtime.global_active_count()
    monkeypatch.setattr(asyncio, "create_task", failing_create_task)

    result = await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

    try:
        assert result.status == "error"
        assert result.error == "task creation boom"
        assert runtime.active_count("parent") == 0
        assert runtime.global_active_count() == global_before
        assert runtime.parent_budget("parent") == ParentBudget(2, 0, 0)
        await runtime.wait_for_quiescence("parent")
        assert captured_coroutines[0].cr_frame is None
    finally:
        for coroutine in captured_coroutines:
            coroutine.close()


async def test_blocking_sync_factory_times_out_without_blocking_owner_loop(
    tmp_path: Path,
) -> None:
    factory_started = threading.Event()
    release_factory = threading.Event()
    loop_progressed = asyncio.Event()

    def blocking_factory():
        factory_started.set()
        release_factory.wait()
        return _successful_runner

    async def prove_loop_progress():
        await _wait_until(factory_started.is_set)
        loop_progressed.set()

    runtime = SubAgentRuntime(
        blocking_factory,
        artifact_root=tmp_path,
        _deadline_waiter=_expire_after_thread_event(factory_started),
        child_budget=1,
    )
    runtime.register_parent("parent", budget=1)
    progress_task = asyncio.create_task(prove_loop_progress())

    try:
        result = await runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)

        assert result.status == "timeout"
        assert loop_progressed.is_set()
        assert runtime.active_count("parent") == 1
    finally:
        release_factory.set()
        await _await_bounded(progress_task)
        await _wait_until(lambda: runtime.active_count("parent") == 0)

    assert runtime.global_active_count() == 0
    assert runtime.parent_budget("parent").reserved == 0


@pytest.mark.parametrize("factory_kind", ["async", "awaitable"])
@pytest.mark.parametrize("terminal_status", ["timeout", "cancelled"])
async def test_late_factory_runner_is_not_invoked_after_child_terminalizes(
    tmp_path: Path,
    factory_kind: str,
    terminal_status: str,
) -> None:
    factory_started = asyncio.Event()
    runner_calls: list[str] = []

    async def runner(prompt, context, execution):
        runner_calls.append(prompt)
        return RunnerResult("late success", tokens_used=0)

    async def create_runner():
        factory_started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return runner

    if factory_kind == "async":
        runner_factory = create_runner
    else:
        runner_factory = lambda: create_runner()

    runtime = SubAgentRuntime(
        runner_factory,
        artifact_root=tmp_path,
        _deadline_waiter=(
            _expire_after(factory_started)
            if terminal_status == "timeout"
            else _wait_for_first_done
        ),
        child_budget=1,
    )
    runtime.register_parent("parent", budget=1)
    global_before = runtime.global_active_count()
    spawn_task = asyncio.create_task(
        runtime.spawn_sub_agent("prompt", parent_run_id="parent", depth=1)
    )
    await _wait_event(factory_started)

    if terminal_status == "cancelled":
        await runtime.cancel_parent("parent")
    result = await _await_bounded(spawn_task)
    await _wait_until(lambda: runtime.active_count("parent") == 0)

    assert result.status == terminal_status
    assert runner_calls == []
    assert runtime.global_active_count() == global_before
    assert runtime.parent_budget("parent") == ParentBudget(
        1,
        1 if terminal_status == "timeout" else 0,
        0,
    )


async def test_five_stubborn_timed_out_children_hold_global_slots_until_termination(
    tmp_path: Path,
) -> None:
    releases = [threading.Event() for _ in range(6)]
    factory_started = [threading.Event() for _ in range(6)]
    factory_index = 0

    def blocking_factory():
        nonlocal factory_index
        index = factory_index
        factory_index += 1
        factory_started[index].set()
        releases[index].wait()
        return _successful_runner

    runtimes = [
        SubAgentRuntime(
            blocking_factory,
            artifact_root=tmp_path / str(index),
            _deadline_waiter=(
                _wait_for_first_done
                if index == 5
                else _expire_after_thread_event(factory_started[index])
            ),
            child_budget=1,
        )
        for index in range(6)
    ]
    for index, runtime in enumerate(runtimes):
        runtime.register_parent(f"parent-{index}", budget=1)

    accepted = None
    try:
        results = await _gather_bounded(
            *[
                runtime.spawn_sub_agent(
                    "prompt",
                    parent_run_id=f"parent-{index}",
                    depth=1,
                )
                for index, runtime in enumerate(runtimes[:5])
            ]
        )

        assert {result.status for result in results} == {"timeout"}
        assert runtimes[0].global_active_count() == 5
        with pytest.raises(ParallelismLimitExceeded):
            await runtimes[5].spawn_sub_agent(
                "sixth",
                parent_run_id="parent-5",
                depth=1,
            )

        releases[0].set()
        await _wait_until(lambda: runtimes[0].global_active_count() < 5)
        accepted = asyncio.create_task(
            runtimes[5].spawn_sub_agent(
                "accepted",
                parent_run_id="parent-5",
                depth=1,
            )
        )
        await _wait_until(lambda: runtimes[0].global_active_count() == 5)
        releases[1].set()
        releases[2].set()
        releases[3].set()
        releases[4].set()
        releases[5].set()
        result = await _await_bounded(accepted)

        assert result.status == "success"
    finally:
        for release in releases:
            release.set()
        if accepted is not None:
            await _gather_bounded(accepted, return_exceptions=True)
        await _wait_until(lambda: runtimes[0].global_active_count() == 0)


async def test_runner_protocol_is_async_and_cooperative() -> None:
    assert inspect.iscoroutinefunction(_successful_runner)
    assert "async backend-owned protocol" in (SubAgentRunner.__doc__ or "")
    assert "asyncio.to_thread" in (SubAgentRunner.__doc__ or "")


async def test_cancelled_parent_id_cannot_be_registered_again(tmp_path: Path) -> None:
    runtime = SubAgentRuntime(lambda: _successful_runner, artifact_root=tmp_path)
    runtime.register_parent("parent", budget=10)

    await runtime.cancel_parent("parent")

    with pytest.raises(ParentRunCancelled):
        runtime.register_parent("parent", budget=10)


@pytest.mark.parametrize(
    "run_id",
    [
        ".",
        "..",
        "../escape",
        "..\\escape",
        "nested/run",
        "nested\\run",
    ],
)
async def test_run_id_cannot_escape_run_scoped_artifact_root(
    tmp_path: Path,
    run_id: str,
) -> None:
    runtime = SubAgentRuntime(lambda: _successful_runner, artifact_root=tmp_path)

    with pytest.raises(ValueError):
        runtime.register_parent(run_id, budget=10)


async def test_default_timeout_is_fifteen_seconds_without_waiting(tmp_path: Path) -> None:
    assert DEFAULT_SUB_AGENT_TIMEOUT_SECONDS == 15.0
    assert "timeout_seconds" not in inspect.signature(SubAgentRuntime).parameters
    with pytest.raises(TypeError):
        SubAgentRuntime(
            lambda: _successful_runner,
            artifact_root=tmp_path,
            timeout_seconds=1.0,
        )


async def _successful_runner(prompt, context, execution):
    await execution.consume_budget(1)
    return RunnerResult(prompt, tokens_used=1)
