"""Code-as-Action executor with backend-owned dynamic sub-agent control."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict
from typing import AsyncIterator, Any

from app.config import settings
from app.core.agent.subagent_control import CapabilityAuthority
from app.core.agent.subagents import RunnerResult, SubAgentRuntime
from app.core.observability import increment_runtime_metric

MAX_SUB_AGENTS = 5
SUB_AGENT_TIMEOUT = 15
MAX_EXIT_FAILURE_DETAIL_CHARS = 1000
logger = logging.getLogger(__name__)

# Tool definition for the LLM function-calling API.
CODE_AS_ACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "code_as_action",
        "description": (
            "Write and execute Python code in an isolated sandbox container. "
            "Use this for any programming task, calculation, data processing, "
            "or script execution. The script is run in a fresh Python environment "
            "and stdout/stderr are captured."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "The complete Python script to execute",
                },
            },
            "required": ["script"],
        },
    },
}


async def stream_code_as_action(
    script: str,
    sandbox_manager,
    *,
    gateway,
    tenant_id: str,
    provider: str = "default",
    parent_budget: Any,
    mount_bundle: dict | None = None,
) -> AsyncIterator[dict]:
    """Execute one disposable parent with a genuine backend child runtime."""
    if not tenant_id:
        raise ValueError("tenant_id is required for Code-as-Action")
    parent_budget_limit = getattr(parent_budget, "remaining", parent_budget)
    if parent_budget_limit <= 0:
        raise ValueError("parent_budget must be positive")

    parent_run_id = uuid.uuid4().hex
    child_events: asyncio.Queue[dict] = asyncio.Queue()

    async def child_runner(prompt, context, execution) -> RunnerResult:
        from app.core.agent.engine import run_agent

        child_sandbox = _ChildSandboxContext(sandbox_manager)
        child_container_id = execution.run_id
        child_messages: list[dict] = []
        if context:
            child_messages.append({"role": "system", "content": context})
        child_messages.append({"role": "user", "content": prompt})

        await child_events.put(
            {
                "type": "sandbox",
                "phase": "sub_agent_allocating",
                "container_id": child_container_id,
            }
        )
        output_parts: list[str] = []
        tokens_used = 0
        phase = "sub_agent_completed"
        try:
            child_container_id = await child_sandbox.start()
            await child_events.put(
                {
                    "type": "sandbox",
                    "phase": "sub_agent_started",
                    "container_id": child_container_id,
                }
            )
            async for event in run_agent(
                gateway,
                child_sandbox,
                provider,
                child_messages,
                tools=[],
                is_sub_agent=True,
                tenant_id=tenant_id,
                sub_agent_execution=execution,
            ):
                if event["type"] == "text":
                    content = event.get("content", "")
                    output_parts.append(content)
                    execution.set_partial_result("".join(output_parts))
                    await child_events.put(
                        {
                            "type": "sandbox_output",
                            "stream": "stdout",
                            "data": content,
                            "container_id": child_container_id,
                        }
                    )
                elif event["type"] == "tool_result":
                    output_parts.append(str(event.get("result", "")))
                    execution.set_partial_result("\n".join(output_parts))
                elif event["type"] == "error":
                    raise RuntimeError(event.get("message", "sub-agent execution failed"))
                elif event["type"] == "done":
                    tokens_used = event.get("tokens_used", execution.budget_consumed)
            return RunnerResult(output="\n".join(output_parts), tokens_used=tokens_used)
        except asyncio.CancelledError:
            phase = (
                "sub_agent_timeout"
                if execution.terminal_status == "timeout"
                else "sub_agent_cancelled"
            )
            raise
        except Exception:
            phase = "sub_agent_error"
            raise
        finally:
            try:
                await child_sandbox.close()
            except BaseException as cleanup_error:
                await child_events.put(
                    {
                        "type": "sandbox_output",
                        "stream": "error",
                        "data": f"child sandbox cleanup failed: {cleanup_error}",
                        "container_id": child_container_id,
                    }
                )
                await child_events.put(
                    {
                        "type": "sandbox",
                        "phase": "sub_agent_error",
                        "container_id": child_container_id,
                    }
                )
                raise
            await child_events.put(
                {
                    "type": "sandbox",
                    "phase": phase,
                    "container_id": child_container_id,
                }
            )

    budget_consumer = getattr(parent_budget, "consume", None)
    runtime = SubAgentRuntime(
        lambda: child_runner,
        parent_budget_consumer=budget_consumer,
    )
    runtime.register_parent(parent_run_id, budget=parent_budget_limit)

    async def spawn_handler(prompt, context, *, tenant_id, parent_run_id, depth):
        result = await runtime.spawn_sub_agent(
            prompt,
            context,
            parent_run_id=parent_run_id,
            depth=depth,
        )
        return asdict(result)

    authority = CapabilityAuthority(
        spawn_handler,
        control_root=settings.subagent_control_root,
        control_gid=settings.subagent_control_gid,
        max_connections_per_run=settings.subagent_max_connections_per_run,
        max_connections_global=settings.subagent_max_connections_global,
        read_timeout_seconds=settings.subagent_read_timeout_seconds,
        handler_timeout_seconds=settings.subagent_handler_timeout_seconds,
        cancellation_grace_seconds=settings.subagent_cancellation_grace_seconds,
    )
    authority.activate_parent(tenant_id, parent_run_id)
    capability = authority.issue_capability(
        tenant_id,
        parent_run_id,
        ttl_seconds=settings.subagent_capability_ttl_seconds,
    )

    parent_task: asyncio.Task | None = None
    runtime_quiesced = False
    artifacts_finalized = False
    parent_error: Exception | None = None
    try:
        yield {
            "type": "sandbox",
            "phase": "allocated",
            "container_id": parent_run_id,
        }
        async with authority.serve_run(tenant_id, parent_run_id):
            parent_kwargs = {
                "run_id": parent_run_id,
                "capability": capability,
                "script": script,
            }
            if mount_bundle is not None:
                parent_kwargs["mount_bundle"] = mount_bundle
            parent_task = asyncio.create_task(
                sandbox_manager.execute_disposable_parent(**parent_kwargs)
            )
            while not parent_task.done():
                try:
                    yield await asyncio.wait_for(child_events.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    pass
            try:
                result = await parent_task
            except Exception as error:
                parent_error = error
                try:
                    await _cancel_parent(runtime, parent_run_id)
                    runtime_quiesced = True
                except BaseException as cleanup_error:
                    _add_exception_note(
                        error,
                        f"sub-agent cleanup also failed: {cleanup_error}",
                    )
                while not child_events.empty():
                    yield child_events.get_nowait()
                for artifact_event in await _finalize_artifact_events(
                    runtime,
                    parent_run_id,
                ):
                    yield artifact_event
                artifacts_finalized = True
                yield {
                    "type": "sandbox_output",
                    "stream": "error",
                    "data": str(error),
                    "container_id": parent_run_id,
                }
                if getattr(error, "disposable_parent_deleted", False) is True:
                    yield {
                        "type": "sandbox",
                        "phase": "deleted",
                        "container_id": parent_run_id,
                    }
                else:
                    cleanup_error = getattr(
                        error,
                        "disposable_parent_cleanup_error",
                        "disposable parent cleanup not confirmed",
                    )
                    yield {
                        "type": "sandbox_output",
                        "stream": "error",
                        "data": str(cleanup_error),
                        "container_id": parent_run_id,
                    }
                raise
            await _cancel_parent(runtime, parent_run_id)
            runtime_quiesced = True
            while not child_events.empty():
                yield child_events.get_nowait()
            for artifact_event in await _finalize_artifact_events(runtime, parent_run_id):
                yield artifact_event
            artifacts_finalized = True
        container_id = result["container_id"]
        for stream in ("stdout", "stderr"):
            if result.get(stream):
                yield {
                    "type": "sandbox_output",
                    "stream": stream,
                    "data": result[stream],
                    "container_id": container_id,
                }
        exit_code = _nonzero_exit_code(result)
        if exit_code is not None:
            failure_message = _format_nonzero_exit_failure(result, exit_code)
            parent_error = RuntimeError(failure_message)
            yield {
                "type": "sandbox_output",
                "stream": "error",
                "data": failure_message,
                "container_id": container_id,
            }
            yield {
                "type": "sandbox",
                "phase": "deleted",
                "container_id": parent_run_id,
            }
            raise parent_error
        yield {
            "type": "sandbox",
            "phase": "completed",
            "container_id": container_id,
        }
    finally:
        parent_cleanup_error: BaseException | None = None
        if parent_task is not None and not parent_task.done():
            parent_task.cancel()
            result = await _await_task_authoritatively(
                parent_task,
                return_exceptions=True,
            )
            if (
                result
                and isinstance(result[0], BaseException)
                and not isinstance(result[0], asyncio.CancelledError)
            ):
                parent_cleanup_error = result[0]
        if not runtime_quiesced:
            try:
                await _cancel_parent(runtime, parent_run_id)
            except BaseException as cleanup_error:
                if parent_error is None:
                    raise
                _add_exception_note(
                    parent_error,
                    f"sub-agent cleanup also failed: {cleanup_error}",
                )
        if not artifacts_finalized:
            try:
                await runtime.finalize_parent_artifacts(parent_run_id)
                artifacts_finalized = True
            except BaseException as cleanup_error:
                if parent_error is None:
                    raise
                _add_exception_note(
                    parent_error,
                    f"sub-agent artifact cleanup also failed: {cleanup_error}",
                )
        try:
            await authority.aclose()
        except BaseException as cleanup_error:
            if parent_error is None:
                raise
            _add_exception_note(
                parent_error,
                f"capability cleanup also failed: {cleanup_error}",
            )
        if parent_cleanup_error is not None and parent_error is None:
            raise parent_cleanup_error
        if parent_cleanup_error is not None:
            _add_exception_note(
                parent_error,
                f"disposable parent cleanup also failed: {parent_cleanup_error}",
            )
    yield {
        "type": "sandbox",
        "phase": "deleted",
        "container_id": parent_run_id,
    }


async def execute_code_as_action(
    script: str,
    sandbox_manager,
    *,
    gateway,
    tenant_id: str,
    provider: str = "default",
    parent_budget: Any,
    mount_bundle: dict | None = None,
) -> str:
    """Execute a Python *script* inside a sandbox container.

    Runs a disposable parent with backend-owned dynamic children and collects
    the canonical sandbox output stream.

    Args:
        script: Python source code to execute.
        sandbox_manager: The application-wide ``SandboxManager`` instance.

    Returns:
        Combined stdout/stderr output as a single string.
    """
    output_parts: list[str] = []
    async for event in stream_code_as_action(
        script,
        sandbox_manager,
        gateway=gateway,
        tenant_id=tenant_id,
        provider=provider,
        parent_budget=parent_budget,
        mount_bundle=mount_bundle,
    ):
        if event.get("type") == "sandbox_output":
            data = event.get("data", "")
            if event.get("stream") == "error":
                output_parts.append(f"[ERROR] {data}")
            elif event.get("stream") != "artifact":
                output_parts.append(data)
    return "\n".join(output_parts)


async def _cancel_parent(runtime: SubAgentRuntime, parent_run_id: str) -> None:
    cleanup = asyncio.create_task(runtime.cancel_parent(parent_run_id))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
    await cleanup


def _nonzero_exit_code(result: dict[str, Any]) -> int | None:
    exit_code = result.get("exit_code")
    if exit_code is None:
        return None
    try:
        code = int(exit_code)
    except (TypeError, ValueError):
        return None
    return code if code != 0 else None


def _format_nonzero_exit_failure(result: dict[str, Any], exit_code: int) -> str:
    detail = str(result.get("stderr") or result.get("stdout") or "").strip()
    if len(detail) > MAX_EXIT_FAILURE_DETAIL_CHARS:
        detail = f"{detail[:MAX_EXIT_FAILURE_DETAIL_CHARS]}...[truncated]"
    if detail:
        return f"Code-as-action exited with exit code {exit_code}: {detail}"
    return f"Code-as-action exited with exit code {exit_code}"


async def _finalize_artifact_events(
    runtime: SubAgentRuntime,
    parent_run_id: str,
) -> list[dict]:
    snapshots = await runtime.finalize_parent_artifacts(parent_run_id)
    increment_runtime_metric("subagent_lifecycle_events", len(snapshots))
    events = []
    for snapshot in snapshots:
        logger.info(
            "sub-agent artifact observed before cleanup parent=%s child=%s status=%s",
            parent_run_id,
            snapshot.get("run_id"),
            snapshot.get("status"),
        )
        events.append(
            {
                "type": "sandbox_output",
                "stream": "artifact",
                "data": json.dumps(snapshot, sort_keys=True),
                "container_id": parent_run_id,
            }
        )
    logger.info(
        "sub-agent artifacts finalized parent=%s count=%d",
        parent_run_id,
        len(snapshots),
    )
    return events


def _add_exception_note(error: BaseException, note: str) -> None:
    """Preserve cleanup context on Python versions without BaseException.add_note."""
    if hasattr(error, "add_note"):
        error.add_note(note)
        return
    notes = list(getattr(error, "__notes__", []))
    notes.append(note)
    error.__notes__ = notes


class _ChildSandboxContext:
    """One child-owned sandbox allocation with no access to the shared pool API."""

    def __init__(self, manager) -> None:
        self._manager = manager
        self._container_id: str | None = None

    async def start(self) -> str:
        if self._container_id is not None:
            raise RuntimeError("child sandbox already started")
        allocation = asyncio.create_task(self._manager.allocate())
        try:
            self._container_id = await asyncio.shield(allocation)
        except asyncio.CancelledError as cancellation:
            try:
                self._container_id = await _await_task_authoritatively(allocation)
            except BaseException:
                raise cancellation
            await self.close()
            raise cancellation
        return self._container_id

    async def execute(self, container_id: str, script: str, timeout: int = 30):
        if container_id != self._container_id or self._container_id is None:
            raise RuntimeError("child sandbox scope rejected")
        async for event in self._manager.execute(container_id, script, timeout):
            yield event

    async def close(self) -> None:
        if self._container_id is None:
            return
        container_id, self._container_id = self._container_id, None
        recycle = asyncio.create_task(self._manager.recycle(container_id))
        while not recycle.done():
            try:
                await asyncio.shield(recycle)
            except asyncio.CancelledError:
                continue
        await recycle

    def __getattr__(self, name: str):
        raise RuntimeError(f"child sandbox operation is not allowed: {name}")


async def _await_task_authoritatively(
    task: asyncio.Task,
    *,
    return_exceptions: bool = False,
):
    """Wait through repeated cancellation so a resource task cannot be orphaned."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    if return_exceptions:
        return await asyncio.gather(task, return_exceptions=True)
    return task.result()
