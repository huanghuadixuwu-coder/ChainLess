"""Canonical runtime owner for temporary application-level sub-agents."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import stat
import threading
import uuid
import weakref
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Iterator, Literal, Protocol

MAX_SUB_AGENT_DEPTH = 1
MAX_ACTIVE_SUB_AGENTS = 5
DEFAULT_SUB_AGENT_TIMEOUT_SECONDS = 15.0
DEFAULT_CHILD_BUDGET = 10_000

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_GLOBAL_ACTIVE_CHILDREN: weakref.WeakSet[_ChildState] = weakref.WeakSet()
_GLOBAL_ACTIVE_LOCK = threading.Lock()


class SubAgentError(RuntimeError):
    """Base error for sub-agent lifecycle policy violations."""


class DepthLimitExceeded(SubAgentError):
    """Raised when a child attempts to exceed the supported depth."""


class ParallelismLimitExceeded(SubAgentError):
    """Raised rather than queueing a sixth active child."""


class BudgetExhausted(SubAgentError):
    """Raised when the shared parent budget cannot fund another child."""


class ParentRunCancelled(SubAgentError):
    """Raised when a parent run is absent or no longer valid."""


class ChildRunInactive(SubAgentError):
    """Raised when retained child context is used after terminalization."""


@dataclass(frozen=True)
class RunnerResult:
    """Result returned by a runner after in-run budget consumption.

    Backend-owned runners must call ``await execution.consume_budget(...)``
    while work streams. ``tokens_used`` reconciles that authoritative ledger;
    it cannot create or replace accounting after execution returns.
    """

    output: str
    tokens_used: int


@dataclass(frozen=True)
class SubAgentResult:
    """Transport-independent result of one temporary child run."""

    run_id: str
    parent_run_id: str
    status: Literal["success", "timeout", "error", "cancelled"]
    output: str = ""
    tokens_used: int = 0
    error: str | None = None
    artifact_path: str = ""


@dataclass(frozen=True)
class ParentBudget:
    """Read-only snapshot of shared parent budget accounting."""

    limit: int
    consumed: int
    reserved: int


@dataclass
class SubAgentExecutionContext:
    """Per-child context that becomes unusable at the terminal deadline."""

    run_id: str
    parent_run_id: str
    budget_limit: int
    _consume_budget: Callable[[int], Awaitable[None]]
    _consumed: Callable[[], int]
    _set_partial_result: Callable[[str], None]
    _get_partial_result: Callable[[], str]
    _get_terminal_status: Callable[[], Literal["timeout", "cancelled"] | None]

    async def consume_budget(self, amount: int) -> None:
        """Atomically charge streamed work against this child's reservation."""
        await self._consume_budget(amount)

    @property
    def budget_consumed(self) -> int:
        return self._consumed()

    def set_partial_result(self, output: str) -> None:
        self._set_partial_result(output)

    @property
    def partial_result(self) -> str:
        return self._get_partial_result()

    @property
    def terminal_status(self) -> Literal["timeout", "cancelled"] | None:
        """Return the runtime-owned terminal reason once cancellation begins."""
        return self._get_terminal_status()


class SubAgentRunner(Protocol):
    """async backend-owned protocol with mandatory in-run budget accounting.

    Implementations must remain cooperative and must not run synchronous
    blocking work on the owner event loop. Blocking work belongs in
    ``asyncio.to_thread``, a process worker, or the sandbox. A coroutine that
    blocks the event loop cannot be preempted by asyncio and is outside this
    runtime owner's contract.
    """

    async def __call__(
        self,
        prompt: str,
        context: str,
        execution: SubAgentExecutionContext,
    ) -> RunnerResult: ...


RunnerFactory = Callable[[], SubAgentRunner | Awaitable[SubAgentRunner]]
BudgetConsumer = Callable[[int], Awaitable[None]]
DeadlineWaiter = Callable[
    [set[asyncio.Task]],
    Awaitable[set[asyncio.Task]],
]


class _FactoryCreationError(RuntimeError):
    pass


@dataclass(eq=False)
class _ChildState:
    run_id: str
    budget_limit: int
    consumed: int = 0
    valid: bool = True
    runner_terminated: bool = False
    streaming_accounting_used: bool = False
    terminal_status: Literal["timeout", "cancelled"] | None = None
    terminal_event: asyncio.Event = field(default_factory=asyncio.Event)
    runner_task: asyncio.Task[RunnerResult] | None = None
    partial_result: str = ""

    @property
    def remaining(self) -> int:
        return self.budget_limit - self.consumed


@dataclass
class _ParentState:
    budget_limit: int
    consumed: int = 0
    reserved: int = 0
    pending_results: int = 0
    valid: bool = True
    active_children: dict[str, _ChildState] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    quiescent: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.quiescent.set()


class SubAgentRuntime:
    """Owns parent contexts, child lifecycle, budgets, and result artifacts."""

    def __init__(
        self,
        runner_factory: RunnerFactory,
        *,
        artifact_root: str | Path = "/workspace",
        child_budget: int = DEFAULT_CHILD_BUDGET,
        parent_budget_consumer: BudgetConsumer | None = None,
        _deadline_waiter: DeadlineWaiter | None = None,
    ) -> None:
        if child_budget <= 0:
            raise ValueError("child_budget must be positive")
        self._runner_factory = runner_factory
        self._artifact_root = Path(artifact_root)
        if not self._artifact_root.is_absolute():
            raise ValueError(
                "artifact_root must be an absolute POSIX path; "
                "only POSIX/Linux Docker runtime is supported"
            )
        self._child_budget = child_budget
        self._parent_budget_consumer = parent_budget_consumer
        self._deadline_waiter = _deadline_waiter or _wait_for_product_deadline
        self._parents: dict[str, _ParentState] = {}
        self._tombstones: set[str] = set()
        self._finalized_artifacts: set[str] = set()
        self._artifact_owner_tokens: dict[str, str] = {}
        self._artifact_owner_lock = threading.Lock()

    @staticmethod
    def global_active_count() -> int:
        """Return process-global slots held by runners that have not terminated."""
        with _GLOBAL_ACTIVE_LOCK:
            return len(_GLOBAL_ACTIVE_CHILDREN)

    def register_parent(self, parent_run_id: str, *, budget: int) -> None:
        """Create a fresh parent context before exposing spawn capability."""
        _validate_run_id(parent_run_id)
        if budget <= 0:
            raise ValueError("budget must be positive")
        if parent_run_id in self._tombstones:
            raise ParentRunCancelled(
                f"parent run cannot be revived after cancellation: {parent_run_id}"
            )
        if parent_run_id in self._parents and self._parents[parent_run_id].valid:
            raise ValueError(f"parent run already registered: {parent_run_id}")
        self._parents[parent_run_id] = _ParentState(budget_limit=budget)
        self._artifact_owner_tokens[parent_run_id] = uuid.uuid4().hex

    async def spawn_sub_agent(
        self,
        prompt: str,
        context: str = "",
        *,
        parent_run_id: str,
        depth: int,
    ) -> SubAgentResult:
        """Spawn one bounded child under an explicitly registered parent."""
        if depth > MAX_SUB_AGENT_DEPTH:
            raise DepthLimitExceeded(
                f"sub-agent depth {depth} exceeds maximum {MAX_SUB_AGENT_DEPTH}"
            )
        if depth < 1:
            raise DepthLimitExceeded("sub-agent depth must be 1")

        state = self._parent_state(parent_run_id)
        run_id = uuid.uuid4().hex
        try:
            child = await self._reserve_child(state, run_id)
        except asyncio.CancelledError:
            await _await_authoritative_cleanup(self.cancel_parent(parent_run_id))
            raise
        artifact_path = self._artifact_path(parent_run_id, run_id)
        execution = SubAgentExecutionContext(
            run_id,
            parent_run_id,
            child.budget_limit,
            lambda amount: self._consume_child_budget(state, child, amount),
            lambda: self._read_consumed(child),
            lambda output: self._set_partial_result(child, output),
            lambda: self._read_partial_result(child),
            lambda: child.terminal_status,
        )

        lifecycle_coroutine = self._run_factory_and_runner(
            prompt,
            context,
            execution,
            child,
        )
        try:
            child.runner_task = asyncio.create_task(lifecycle_coroutine)
            child.runner_task.add_done_callback(
                lambda task: self._runner_finished(state, child, task)
            )
        except Exception as exc:
            lifecycle_coroutine.close()
            await self._terminalize_child(state, child, charge_remaining=False)
            state.active_children.pop(child.run_id, None)
            if not state.active_children and state.pending_results == 0:
                state.quiescent.set()
            self._release_global_slot(child)
            result = self._result(
                child,
                parent_run_id,
                artifact_path,
                "error",
                child.partial_result,
                str(exc),
            )
            await self._persist_terminal_result(state, artifact_path, result)
            return result

        terminal_wait = asyncio.create_task(child.terminal_event.wait())
        caller_cancelled_parent = False
        try:
            done = await self._deadline_waiter({child.runner_task, terminal_wait})

            if child.terminal_status is not None:
                result = self._terminal_signal_result(
                    child, parent_run_id, artifact_path
                )
            elif not done:
                await self._terminalize_child(
                    state,
                    child,
                    status="timeout",
                    charge_remaining=True,
                )
                child.runner_task.cancel()
                result = self._terminal_signal_result(
                    child, parent_run_id, artifact_path
                )
            else:
                result = await self._runner_result(
                    state, child, parent_run_id, artifact_path
                )
        except asyncio.CancelledError:
            await _await_authoritative_cleanup(
                self._begin_parent_cancellation(parent_run_id)
            )
            caller_cancelled_parent = True
            result = self._terminal_signal_result(
                child, parent_run_id, artifact_path
            )
        finally:
            terminal_wait.cancel()
            await asyncio.gather(terminal_wait, return_exceptions=True)

        try:
            await self._persist_terminal_result(state, artifact_path, result)
        finally:
            if caller_cancelled_parent:
                await _await_authoritative_cleanup(
                    self.wait_for_quiescence(parent_run_id)
                )
        return result

    async def _persist_terminal_result(
        self,
        state: _ParentState,
        path: Path,
        result: SubAgentResult,
    ) -> None:
        try:
            await self._persist_result(path, result)
        finally:
            async with state.lock:
                state.pending_results -= 1
                if not state.active_children and state.pending_results == 0:
                    state.quiescent.set()

    async def _persist_result(self, path: Path, result: SubAgentResult) -> None:
        await _await_authoritative_completion(
            asyncio.to_thread(self._ensure_artifact_owner, result.parent_run_id)
        )
        await _await_authoritative_completion(
            asyncio.to_thread(self._write_result, path, result)
        )

    async def _run_factory_and_runner(
        self,
        prompt: str,
        context: str,
        execution: SubAgentExecutionContext,
        child: _ChildState,
    ) -> RunnerResult:
        try:
            if inspect.iscoroutinefunction(self._runner_factory):
                runner = await self._runner_factory()
            else:
                factory_task = asyncio.create_task(asyncio.to_thread(self._runner_factory))
                try:
                    runner = await asyncio.shield(factory_task)
                except asyncio.CancelledError:
                    await factory_task
                    raise
            if inspect.isawaitable(runner):
                runner = await runner
            if not callable(runner):
                raise _FactoryCreationError(
                    "runner factory must return a callable runner"
                )
            if not (
                inspect.iscoroutinefunction(runner)
                or inspect.iscoroutinefunction(getattr(runner, "__call__", None))
            ):
                raise _FactoryCreationError(
                    "runner factory must return an async callable runner"
                )
        except asyncio.CancelledError:
            raise
        except _FactoryCreationError:
            raise
        except Exception as exc:
            raise _FactoryCreationError(str(exc)) from exc
        self._assert_child_active(child)
        return await runner(prompt, context, execution)

    async def cancel_parent(self, parent_run_id: str) -> None:
        """Tombstone a parent and wait for runners and terminal results."""
        await self._begin_parent_cancellation(parent_run_id)
        await self.wait_for_quiescence(parent_run_id)

    async def _begin_parent_cancellation(self, parent_run_id: str) -> None:
        """Invalidate one parent and signal children without self-waiting."""
        state = self._existing_parent_state(parent_run_id)
        async with state.lock:
            state.valid = False
            self._tombstones.add(parent_run_id)
            children = list(state.active_children.values())
            for child in children:
                self._terminalize_child_locked(
                    state,
                    child,
                    status="cancelled",
                    charge_remaining=False,
                )
        for child in children:
            if child.runner_task is not None:
                child.runner_task.cancel()

    async def wait_for_quiescence(self, parent_run_id: str) -> None:
        """Wait until child runners terminate and terminal results are persisted."""
        state = self._existing_parent_state(parent_run_id)
        await _await_authoritative_completion(state.quiescent.wait())

    async def finalize_parent_artifacts(self, parent_run_id: str) -> list[dict]:
        """Observe and remove one terminal parent's run-scoped result artifacts.

        The backend runtime is the sole lifecycle owner. Callers receive a
        snapshot for logs/events, while the on-disk run directory is removed
        before this method returns.
        """
        _validate_run_id(parent_run_id)
        state = self._existing_parent_state(parent_run_id)
        if state.valid:
            raise RuntimeError("parent artifacts cannot be finalized while run is active")
        await self.wait_for_quiescence(parent_run_id)
        if parent_run_id in self._finalized_artifacts:
            return []
        snapshots = await _await_authoritative_result(
            asyncio.to_thread(self._read_and_remove_parent_artifacts, parent_run_id)
        )
        self._finalized_artifacts.add(parent_run_id)
        return snapshots

    def active_count(self, parent_run_id: str) -> int:
        return len(self._existing_parent_state(parent_run_id).active_children)

    def parent_budget(self, parent_run_id: str) -> ParentBudget:
        state = self._existing_parent_state(parent_run_id)
        return ParentBudget(state.budget_limit, state.consumed, state.reserved)

    async def _runner_result(
        self,
        state: _ParentState,
        child: _ChildState,
        parent_run_id: str,
        artifact_path: Path,
    ) -> SubAgentResult:
        try:
            runner_result = child.runner_task.result()
            if runner_result.tokens_used < 0:
                raise ValueError("runner tokens_used must not be negative")
            if not child.streaming_accounting_used:
                raise RuntimeError("runner must consume budget during execution")
            if runner_result.tokens_used != child.consumed:
                await self._terminalize_child(state, child, charge_remaining=False)
                return self._result(
                    child,
                    parent_run_id,
                    artifact_path,
                    "error",
                    child.partial_result,
                    (
                        f"runner reported {runner_result.tokens_used} tokens "
                        f"after consuming {child.consumed}"
                    ),
                )
            await self._terminalize_child(state, child, charge_remaining=False)
            return self._result(
                child,
                parent_run_id,
                artifact_path,
                "success",
                runner_result.output,
            )
        except Exception as exc:
            await self._terminalize_child(
                state,
                child,
                charge_remaining=not isinstance(exc, _FactoryCreationError),
            )
            return self._result(
                child,
                parent_run_id,
                artifact_path,
                "error",
                child.partial_result,
                str(exc),
            )

    def _terminal_signal_result(
        self,
        child: _ChildState,
        parent_run_id: str,
        artifact_path: Path,
    ) -> SubAgentResult:
        if child.terminal_status == "timeout":
            return self._result(
                child,
                parent_run_id,
                artifact_path,
                "timeout",
                child.partial_result,
                f"timed out after {_format_seconds(DEFAULT_SUB_AGENT_TIMEOUT_SECONDS)}s",
            )
        return self._result(
            child,
            parent_run_id,
            artifact_path,
            "cancelled",
            child.partial_result,
            "parent run cancelled",
        )

    @staticmethod
    def _result(
        child: _ChildState,
        parent_run_id: str,
        artifact_path: Path,
        status: Literal["success", "timeout", "error", "cancelled"],
        output: str = "",
        error: str | None = None,
    ) -> SubAgentResult:
        return SubAgentResult(
            run_id=child.run_id,
            parent_run_id=parent_run_id,
            status=status,
            output=output,
            tokens_used=child.consumed,
            error=error,
            artifact_path=str(artifact_path),
        )

    def _parent_state(self, parent_run_id: str) -> _ParentState:
        state = self._existing_parent_state(parent_run_id)
        if not state.valid:
            raise ParentRunCancelled(f"parent run is not active: {parent_run_id}")
        return state

    def _existing_parent_state(self, parent_run_id: str) -> _ParentState:
        state = self._parents.get(parent_run_id)
        if state is None:
            raise ParentRunCancelled(f"parent run does not exist: {parent_run_id}")
        return state

    async def _reserve_child(
        self,
        state: _ParentState,
        run_id: str,
    ) -> _ChildState:
        async with state.lock:
            if not state.valid:
                raise ParentRunCancelled("parent run is not active")
            available = state.budget_limit - state.consumed - state.reserved
            if available <= 0:
                raise BudgetExhausted("parent budget exhausted")
            child = _ChildState(run_id, min(self._child_budget, available))
            with _GLOBAL_ACTIVE_LOCK:
                if len(_GLOBAL_ACTIVE_CHILDREN) >= MAX_ACTIVE_SUB_AGENTS:
                    raise ParallelismLimitExceeded(
                        f"maximum active sub-agents is {MAX_ACTIVE_SUB_AGENTS}"
                    )
                _GLOBAL_ACTIVE_CHILDREN.add(child)
            state.reserved += child.budget_limit
            state.pending_results += 1
            state.active_children[run_id] = child
            state.quiescent.clear()
            return child

    async def _consume_child_budget(
        self,
        state: _ParentState,
        child: _ChildState,
        amount: int,
    ) -> None:
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError("budget consumption amount must be a non-negative integer")
        async with state.lock:
            if not child.valid or child.runner_terminated:
                raise ChildRunInactive("child run is no longer active")
            if amount > child.remaining:
                raise BudgetExhausted(
                    f"child budget exhausted: {amount} requested, "
                    f"{child.remaining} remaining"
                )
            state.reserved -= amount
            state.consumed += amount
            child.consumed += amount
            if amount > 0:
                child.streaming_accounting_used = True
        if self._parent_budget_consumer is not None and amount > 0:
            await _await_authoritative_completion(self._parent_budget_consumer(amount))

    @staticmethod
    def _assert_child_active(child: _ChildState) -> None:
        if not child.valid or child.runner_terminated:
            raise ChildRunInactive("child run is no longer active")

    def _read_consumed(self, child: _ChildState) -> int:
        self._assert_child_active(child)
        return child.consumed

    def _set_partial_result(self, child: _ChildState, output: str) -> None:
        self._assert_child_active(child)
        child.partial_result = output

    def _read_partial_result(self, child: _ChildState) -> str:
        self._assert_child_active(child)
        return child.partial_result

    async def _terminalize_child(
        self,
        state: _ParentState,
        child: _ChildState,
        *,
        status: Literal["timeout", "cancelled"] | None = None,
        charge_remaining: bool,
    ) -> None:
        terminal_charge = 0
        async with state.lock:
            terminal_charge = self._terminalize_child_locked(
                state,
                child,
                status=status,
                charge_remaining=charge_remaining,
            )
        if self._parent_budget_consumer is not None and terminal_charge > 0:
            await _await_authoritative_completion(
                self._parent_budget_consumer(terminal_charge)
            )

    @staticmethod
    def _terminalize_child_locked(
        state: _ParentState,
        child: _ChildState,
        *,
        status: Literal["timeout", "cancelled"] | None,
        charge_remaining: bool,
    ) -> int:
        if not child.valid:
            return 0
        child.valid = False
        child.terminal_status = status
        terminal_charge = child.remaining if charge_remaining else 0
        if charge_remaining:
            state.reserved -= child.remaining
            state.consumed += child.remaining
            child.consumed = child.budget_limit
        else:
            state.reserved -= child.remaining
        if status is not None:
            child.terminal_event.set()
        return terminal_charge

    def _runner_finished(
        self,
        state: _ParentState,
        child: _ChildState,
        task: asyncio.Task[RunnerResult],
    ) -> None:
        child.runner_terminated = True
        if not task.cancelled():
            task.exception()
        state.active_children.pop(child.run_id, None)
        if not state.active_children and state.pending_results == 0:
            state.quiescent.set()
        self._release_global_slot(child)

    @staticmethod
    def _release_global_slot(child: _ChildState) -> None:
        with _GLOBAL_ACTIVE_LOCK:
            _GLOBAL_ACTIVE_CHILDREN.discard(child)

    def _artifact_path(self, parent_run_id: str, run_id: str) -> Path:
        _validate_run_id(parent_run_id)
        return (
            self._artifact_root
            / "runs"
            / parent_run_id
            / "sub_results"
            / f"{run_id}.json"
        )

    def _read_and_remove_parent_artifacts(self, parent_run_id: str) -> list[dict]:
        try:
            root_fd = os.open(self._artifact_root, os.O_RDONLY | os.O_DIRECTORY)
        except FileNotFoundError:
            return []
        opened: list[int] = [root_fd]
        snapshots: list[dict] = []
        try:
            try:
                runs_fd = os.open(
                    "runs",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=root_fd,
                )
            except FileNotFoundError:
                return []
            opened.append(runs_fd)
            try:
                parent_fd = os.open(
                    parent_run_id,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=runs_fd,
                )
            except FileNotFoundError:
                return []
            opened.append(parent_fd)
            owner_token = self._artifact_owner_tokens[parent_run_id]
            try:
                owner_fd = os.open(
                    ".subagent-owner",
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError as exc:
                raise OSError("result artifact owner marker is missing") from exc
            with os.fdopen(owner_fd, "r", encoding="ascii") as handle:
                if handle.read() != owner_token:
                    raise OSError("result artifact owner mismatch")

            try:
                results_fd = os.open(
                    "sub_results",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                results_fd = None
            if results_fd is not None:
                opened.append(results_fd)
                for name in sorted(os.listdir(results_fd)):
                    entry = os.stat(name, dir_fd=results_fd, follow_symlinks=False)
                    if not stat.S_ISREG(entry.st_mode):
                        raise OSError(f"unexpected non-file result artifact: {name}")
                    file_fd = os.open(
                        name,
                        os.O_RDONLY | os.O_NOFOLLOW,
                        dir_fd=results_fd,
                    )
                    with os.fdopen(file_fd, "r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                    if (
                        not isinstance(payload, dict)
                        or payload.get("parent_run_id") != parent_run_id
                        or name != f"{payload.get('run_id')}.json"
                        or payload.get("artifact_path")
                        != str(
                            self._artifact_path(parent_run_id, payload.get("run_id", ""))
                        )
                    ):
                        raise OSError(f"invalid result artifact ownership: {name}")
                    snapshots.append(payload)

                for name in sorted(os.listdir(results_fd)):
                    os.unlink(name, dir_fd=results_fd)
                os.rmdir("sub_results", dir_fd=parent_fd)

            os.unlink(".subagent-owner", dir_fd=parent_fd)
            try:
                os.rmdir(parent_run_id, dir_fd=runs_fd)
            except OSError:
                pass
            try:
                os.rmdir("runs", dir_fd=root_fd)
            except OSError:
                pass
            return snapshots
        finally:
            for directory_fd in reversed(opened):
                try:
                    os.close(directory_fd)
                except OSError:
                    pass

    def _ensure_artifact_owner(self, parent_run_id: str) -> None:
        with self._artifact_owner_lock:
            self._ensure_artifact_owner_locked(parent_run_id)

    def _ensure_artifact_owner_locked(self, parent_run_id: str) -> None:
        token = self._artifact_owner_tokens[parent_run_id].encode("ascii")
        directory_fd = os.open(
            self._artifact_root.anchor,
            os.O_RDONLY | os.O_DIRECTORY,
        )
        try:
            for component in (*self._artifact_root.parts[1:], "runs", parent_run_id):
                directory_fd = _open_or_create_directory(component, directory_fd)
            try:
                owner_fd = os.open(
                    ".subagent-owner",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                owner_fd = os.open(
                    ".subagent-owner",
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                with os.fdopen(owner_fd, "rb") as handle:
                    if handle.read() != token:
                        raise OSError("result artifact owner mismatch")
            else:
                try:
                    _write_all(owner_fd, token)
                    os.fsync(owner_fd)
                finally:
                    os.close(owner_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _write_result(path: Path, result: SubAgentResult) -> None:
        directory_fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        temp_name = f".{path.name}.{uuid.uuid4().hex}.tmp"
        temp_created = False
        try:
            for component in path.parent.parts[1:]:
                directory_fd = _open_or_create_directory(component, directory_fd)
            file_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            temp_created = True
            try:
                payload = json.dumps(asdict(result), sort_keys=True).encode("utf-8")
                _write_all(file_fd, payload)
                os.fsync(file_fd)
            finally:
                os.close(file_fd)
            try:
                target_stat = os.stat(
                    path.name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                if stat.S_ISLNK(target_stat.st_mode):
                    raise OSError("result artifact target must not be a symlink")
            os.rename(
                temp_name,
                path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            temp_created = False
        except BaseException:
            if temp_created:
                try:
                    os.unlink(temp_name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
            raise
        finally:
            os.close(directory_fd)


_current_runtime: ContextVar[SubAgentRuntime | None] = ContextVar(
    "sub_agent_runtime",
    default=None,
)


@contextmanager
def bind_sub_agent_runtime(runtime: SubAgentRuntime) -> Iterator[None]:
    """Bind the explicit runtime owner for one request/control context."""
    token = _current_runtime.set(runtime)
    try:
        yield
    finally:
        _current_runtime.reset(token)


async def spawn_sub_agent(
    prompt: str,
    context: str = "",
    *,
    parent_run_id: str,
    depth: int,
) -> SubAgentResult:
    """Public transport-independent child-spawn contract."""
    runtime = _current_runtime.get()
    if runtime is None:
        raise RuntimeError("no SubAgentRuntime is bound")
    return await runtime.spawn_sub_agent(
        prompt,
        context,
        parent_run_id=parent_run_id,
        depth=depth,
    )


def _validate_run_id(run_id: str) -> None:
    if run_id in {".", ".."} or not run_id or not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id must contain only letters, numbers, '.', '_', or '-'")


def _open_or_create_directory(component: str, parent_fd: int) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        child_fd = os.open(component, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(component, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        child_fd = os.open(component, flags, dir_fd=parent_fd)
    os.close(parent_fd)
    return child_fd


def _write_all(file_fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(file_fd, payload[offset:])
        if written == 0:
            raise OSError("result artifact write made no progress")
        offset += written


def _format_seconds(seconds: float) -> str:
    return str(int(seconds)) if float(seconds).is_integer() else str(seconds)


async def _wait_for_product_deadline(tasks: set[asyncio.Task]) -> set[asyncio.Task]:
    done, _ = await asyncio.wait(
        tasks,
        timeout=DEFAULT_SUB_AGENT_TIMEOUT_SECONDS,
        return_when=asyncio.FIRST_COMPLETED,
    )
    return done


async def _await_authoritative_cleanup(cleanup: Awaitable[None]) -> None:
    await _await_authoritative_completion(cleanup)


async def _await_authoritative_completion(awaitable: Awaitable[None]) -> None:
    task = asyncio.ensure_future(awaitable)
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    await task


async def _await_authoritative_result(awaitable):
    task = asyncio.create_task(awaitable)
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()
