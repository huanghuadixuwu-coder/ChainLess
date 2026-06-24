"""ReAct agent engine — think-act-observe loop with safety guards.

The engine drives a ReAct loop:
  1. Call the LLM (via **LLMGateway**)
  2. If the LLM returns tool calls, execute them and feed results back
  3. Repeat until the LLM produces a pure-text response or a guard triggers

Guards
------
- **Iteration limit** (``MAX_ITERATIONS``) — prevents infinite loops.
- **Token budget** (``MAX_TOKENS_PER_TURN``) — cumulative across iterations.
- **Circuit breaker** (``MAX_CONSECUTIVE_ERRORS``) — stops on repeated tool failures.
"""

import asyncio
import inspect
import json
import logging
import uuid
from typing import AsyncIterator, Any

from app.core.artifacts import ToolExecutionResult
from app.core.agent.code_executor import stream_code_as_action
from app.core.agent.tool_router import AcquiredToolConfirmationRequired, execute_tool
from app.core.capabilities.hooks import emit_capability_hook
from app.core.capabilities.policy import evaluate_worker_tool_policy
from app.core.tools.builtin import ALL_TOOLS
from app.core.tools.builtin.sandbox import execute as execute_shell_exec
from app.core.tools.classifier import RiskLevel, classify_tool
from app.core.tools.api_runtime import APIToolConfirmationRequired
from app.core.browser_automation import BrowserAutomationConfirmationRequired
from app.core.workspace_connectors.mounts import sandbox_mount_payload_from_context

# ---------------------------------------------------------------------------
# Constants — guardrails
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 10
MAX_TOKENS_PER_TURN = 100_000
MAX_CONSECUTIVE_ERRORS = 3
ACQUISITION_RECORD_TIMEOUT_SECONDS = 5.0
_ACQUISITION_CAPTURE_TEXT_CHARS = 1001
_ACQUISITION_CAPTURE_EVENT_DATA_CHARS = 401
_ACQUISITION_MAX_SANDBOX_EVENTS = 24
logger = logging.getLogger(__name__)
_ACQUISITION_RECORDING_TASKS: set[asyncio.Task[None]] = set()


def select_execution_route(prompt: str, tools: list[dict] | None = None) -> str:
    """Choose the deterministic first route for a turn.

    The router is intentionally conservative: it only chooses a specialized
    path when the prompt and exposed tools make that path unambiguous.
    Otherwise the normal ReAct loop remains the fallback.
    """
    tool_names = {
        tool.get("function", {}).get("name", "")
        for tool in (tools or ALL_TOOLS)
    }
    text = prompt.lower()
    if any(word in text for word in ("weather", "forecast", "temperature", "天气")):
        return "direct_tool:weather_get" if "weather_get" in tool_names else "react"
    if any(word in text for word in ("run python", "execute python", "script", "代码", "计算")):
        return "code_as_action" if "code_as_action" in tool_names else "react"
    if any(word in text for word in ("search", "fetch", "browse", "查", "搜索")):
        web_tools = {"web_search", "web_fetch"} & tool_names
        if len(web_tools) == 1:
            return f"direct_tool:{next(iter(web_tools))}"
    return "react"


class _TurnBudget:
    """One shared token ledger for the parent turn and all dynamic children."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.consumed = 0
        self._lock = asyncio.Lock()

    @property
    def remaining(self) -> int:
        return self.limit - self.consumed

    async def consume(self, amount: int) -> None:
        async with self._lock:
            if amount > self.remaining:
                raise RuntimeError("turn token budget exhausted")
            self.consumed += amount


# ---------------------------------------------------------------------------
# Agent entry-point
# ---------------------------------------------------------------------------


async def run_agent(
    gateway,
    sandbox_manager,
    provider: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    is_sub_agent: bool = False,
    tenant_id: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
    run_id: str | None = None,
    sub_agent_execution: Any | None = None,
    max_iterations: int | None = None,
    max_tokens_per_turn: int | None = None,
    max_consecutive_errors: int | None = None,
    authorized_tool_names: set[str] | list[str] | tuple[str, ...] | None = None,
    worker_context: dict[str, Any] | None = None,
    workspace_base: str | None = None,
    connector_mount_context: dict[str, Any] | None = None,
    acquisition_recorder: Any | None = None,
    acquired_tool_manifest_version: str | None = None,
) -> AsyncIterator[dict]:
    """Run the ReAct loop with token budget + circuit breaker.

    Args:
        gateway: The application-wide ``LLMGateway`` instance.
        sandbox_manager: The application-wide ``SandboxManager`` instance.
        provider: LLM provider name (e.g. ``"default"``).
        messages: Conversation history.  **This list is mutated** — tool
            call requests and their results are appended during the loop
            so that subsequent iterations have full context.
        tools: Tool definitions to expose to the LLM.  Defaults to
            ``ALL_TOOLS`` from the builtin tool registry.  Note that
            ``code_as_action`` and ``shell_exec`` are handled directly
            by the engine, not by the tool router.
        is_sub_agent: Disable recursive Code-as-Action for depth-one children.
        tenant_id: Trusted backend tenant scope required by Code-as-Action.
        user_id: Trusted backend user scope for persisted artifacts.
        conversation_id: Trusted conversation scope for persisted artifacts.
        run_id: Optional parent run id. Generated per engine run when omitted.
        sub_agent_execution: Backend-owned child budget/partial-result context.
        acquisition_recorder: Optional best-effort callback for runtime
            acquisition evidence. When omitted, code-as-action uses the
            acquisition facade if trusted tenant/user scope is present.

    Yields:
        Event dicts with the following ``type`` values:

        - ``"text"``            → ``{"type": "text", "content": str}``
        - ``"tool_call_start"`` → ``{"type": "tool_call_start", "name": str, "args": dict}``
        - ``"tool_result"``     → ``{"type": "tool_result", "name": str, "result": str}``
        - ``"tool_error"``      → ``{"type": "tool_error", "name": str, "error": str, "consecutive": int}``
        - ``"confirmation_required"`` → ``{"type": "confirmation_required", "tool_name": str, "args": dict, "risk": str, "timeout_s": int}``
        - ``"error"``           → ``{"type": "error", "code": str, "message": str}``
        - ``"done"``            → ``{"type": "done", "tokens_used": int}``
    """
    iteration = 0
    tokens_used = 0
    max_iterations = MAX_ITERATIONS if max_iterations is None else max_iterations
    max_tokens_per_turn = (
        MAX_TOKENS_PER_TURN if max_tokens_per_turn is None else max_tokens_per_turn
    )
    max_consecutive_errors = (
        MAX_CONSECUTIVE_ERRORS if max_consecutive_errors is None else max_consecutive_errors
    )
    run_id = run_id or str(uuid.uuid4())
    turn_budget = None if sub_agent_execution is not None else _TurnBudget(max_tokens_per_turn)
    consecutive_errors = 0
    active_tools = ALL_TOOLS if tools is None else tools
    if is_sub_agent:
        active_tools = [
            tool
            for tool in active_tools
            if tool.get("function", {}).get("name") != "code_as_action"
        ]
    allowed_tool_names = {
        tool.get("function", {}).get("name")
        for tool in active_tools
        if tool.get("function", {}).get("name")
    }
    runtime_authorized_tool_names = (
        None if authorized_tool_names is None else set(authorized_tool_names)
    )
    configured_tool_risks = {
        tool.get("function", {}).get("name"): tool.get("risk")
        for tool in active_tools
        if tool.get("function", {}).get("name") and tool.get("risk")
    }

    while iteration < max_iterations:
        # ---- Guard: token budget ----
        if turn_budget is not None:
            tokens_used = turn_budget.consumed
        if tokens_used >= max_tokens_per_turn:
            yield {
                "type": "error",
                "code": "TOKEN_BUDGET_EXHAUSTED",
                "message": f"Exceeded {max_tokens_per_turn} token budget",
            }
            break

        # ---- Guard: circuit breaker ----
        if consecutive_errors >= max_consecutive_errors:
            yield {
                "type": "error",
                "code": "CIRCUIT_BREAKER",
                "message": f"{max_consecutive_errors} consecutive tool errors",
            }
            break

        iteration += 1

        # ---- Step 1: LLM call ----
        tool_calls_buffer: dict[int, dict] = {}

        async for delta in gateway.chat_stream(
            provider, messages, active_tools, tenant_id=tenant_id
        ):
            if sub_agent_execution is not None:
                await sub_agent_execution.consume_budget(1)
                tokens_used += 1
            else:
                try:
                    await turn_budget.consume(1)
                    tokens_used = turn_budget.consumed
                except RuntimeError:
                    yield {
                        "type": "error",
                        "code": "TOKEN_BUDGET_EXHAUSTED",
                        "message": f"Exceeded {max_tokens_per_turn} token budget",
                    }
                    return

            if delta["type"] == "text":
                yield {"type": "text", "content": delta["content"]}

            elif delta["type"] == "tool_call":
                idx = delta.get("index", 0)
                if idx not in tool_calls_buffer:
                    tool_calls_buffer[idx] = {
                        "id": delta.get("id", ""),
                        "name": "",
                        "arguments": "",
                    }
                tool_calls_buffer[idx]["name"] += delta.get("name") or ""
                tool_calls_buffer[idx]["arguments"] += delta.get("arguments") or ""

        # ---- Step 2: No tool calls -> response is complete ----
        if not tool_calls_buffer:
            break

        # ---- Step 3: Execute each tool call ----
        destructive_hit = False
        for tc in tool_calls_buffer.values():
            if (
                tc["name"] not in allowed_tool_names
                or (
                    runtime_authorized_tool_names is not None
                    and tc["name"] not in runtime_authorized_tool_names
                )
            ):
                consecutive_errors += 1
                yield {
                    "type": "tool_error",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "code": "TOOL_NOT_AUTHORIZED",
                    "blocked": True,
                    "rejection_reason": "Tool is not pre-authorized for this run",
                    "error": f"tool is not authorized for this run: {tc['name']}",
                    "consecutive": consecutive_errors,
                }
                continue

            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                if not isinstance(args, dict):
                    raise ValueError("tool arguments must be a JSON object")
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                consecutive_errors += 1
                yield {
                    "type": "tool_error",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "error": f"invalid tool arguments: {exc}",
                    "consecutive": consecutive_errors,
                }
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": tc["arguments"],
                                },
                            }
                        ],
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": f"Error: invalid tool arguments: {exc}",
                    }
                )
                continue
            configured_risk = configured_tool_risks.get(tc["name"])
            try:
                risk = RiskLevel(configured_risk) if configured_risk else classify_tool(tc["name"])
            except ValueError:
                risk = classify_tool(tc["name"])

            await emit_capability_hook(
                "before_tool_call",
                {
                    "tool_call_id": tc["id"],
                    "tool_name": tc["name"],
                    "risk": risk.value,
                    "worker_run_id": (worker_context or {}).get("worker_run_id"),
                    "worker_id": (worker_context or {}).get("worker_id"),
                },
            )
            worker_tool_policy = evaluate_worker_tool_policy(
                tc["name"],
                worker_context,
                risk=risk.value,
            )
            if worker_tool_policy.action == "block":
                consecutive_errors += 1
                await emit_capability_hook(
                    "after_tool_call",
                    {
                        "tool_call_id": tc["id"],
                        "tool_name": tc["name"],
                        "status": "blocked",
                        "reason": worker_tool_policy.reason,
                        "worker_run_id": (worker_context or {}).get("worker_run_id"),
                    },
                    policy_action="block",
                )
                yield {
                    "type": "tool_error",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "code": "WORKER_TOOL_NOT_ALLOWED",
                    "blocked": True,
                    "rejection_reason": worker_tool_policy.reason,
                    "error": f"worker policy disallows tool: {tc['name']}",
                    "consecutive": consecutive_errors,
                    "worker_run_id": (worker_context or {}).get("worker_run_id"),
                }
                continue

            yield {
                "type": "tool_call_start",
                "tool_call_id": tc["id"],
                "name": tc["name"],
                "args": args,
                "risk": risk.value,
            }

            # ---- Safety check: classify tool risk ----
            if risk == RiskLevel.DESTRUCTIVE or worker_tool_policy.action == "confirm":
                destructive_hit = True
                confirmation_risk = (
                    risk.value if worker_tool_policy.action == "confirm" else "destructive"
                )
                yield {
                    "type": "confirmation_required",
                    "tool_call_id": tc["id"],
                    "tool_name": tc["name"],
                    "args": args,
                    "risk": confirmation_risk,
                    "timeout_s": 30,
                }
                await emit_capability_hook(
                    "after_tool_call",
                    {
                        "tool_call_id": tc["id"],
                        "tool_name": tc["name"],
                        "status": "needs_confirmation",
                        "risk": confirmation_risk,
                        "worker_run_id": (worker_context or {}).get("worker_run_id"),
                    },
                    policy_action="confirm",
                )
                # Engine pauses — caller handles user response via
                # a separate confirmation endpoint (Phase 6).
                # For now, break out of the ReAct loop entirely.
                break

            try:
                code_action_trace: dict[str, Any] | None = None
                code_action_mount_bundle: dict[str, Any] | None = None
                tool_context = {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "tool_call_id": tc["id"],
                    "workspace_base": workspace_base,
                    "worker_context": worker_context,
                    "acquired_tool_manifest_version": acquired_tool_manifest_version,
                }
                if connector_mount_context:
                    tool_context.update(connector_mount_context)
                if tc["name"] == "code_as_action":
                    from app.core.acquisition.facade import runtime_capability_enabled

                    if not runtime_capability_enabled("code_as_action"):
                        raise RuntimeError("Code-as-Action acquisition runtime is disabled")
                    if is_sub_agent:
                        raise RuntimeError("sub-agents cannot execute Code-as-Action")
                    if not tenant_id:
                        raise RuntimeError("Code-as-Action requires a trusted tenant scope")
                    script = str(args.get("script", ""))
                    mount_bundle = sandbox_mount_payload_from_context(connector_mount_context)
                    code_action_mount_bundle = mount_bundle
                    code_action_trace = _new_code_action_trace(script)
                    output_parts: list[str] = []
                    async for sandbox_event in stream_code_as_action(
                        script,
                        sandbox_manager,
                        gateway=gateway,
                        tenant_id=tenant_id,
                        provider=provider,
                        parent_budget=turn_budget,
                        mount_bundle=mount_bundle,
                    ):
                        _capture_code_action_event(code_action_trace, sandbox_event)
                        if sandbox_event["type"] == "sandbox_output":
                            data = sandbox_event.get("data", "")
                            if sandbox_event.get("stream") == "error":
                                output_parts.append(f"[ERROR] {data}")
                            elif sandbox_event.get("stream") == "stderr":
                                output_parts.append(data)
                            elif sandbox_event.get("stream") == "stdout":
                                output_parts.append(data)
                            elif sandbox_event.get("stream") != "artifact":
                                output_parts.append(data)
                        yield sandbox_event
                    result = "\n".join(output_parts)
                    _schedule_code_as_action_acquisition(
                        acquisition_recorder=acquisition_recorder,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        source_run_id=run_id,
                        tool_call_id=tc["id"],
                        trace=code_action_trace,
                        status="succeeded",
                        risk_level=risk.value,
                        failure_reason=None,
                        mount_bundle=code_action_mount_bundle,
                    )
                    acquisition_event = _code_as_action_acquisition_event(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        source_run_id=run_id,
                        tool_call_id=tc["id"],
                        status="succeeded",
                        risk_level=risk.value,
                    )
                    if acquisition_event is not None:
                        yield acquisition_event
                elif tc["name"] == "shell_exec":
                    result = await execute_shell_exec(tc["name"], args, sandbox_manager)
                else:
                    result = await execute_tool(tc["name"], args, context=tool_context)

                artifacts: list[dict] = []
                if isinstance(result, ToolExecutionResult):
                    artifacts = result.artifacts
                    result = result.content

                yield {
                    "type": "tool_result",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "result": str(result)[:2000],
                    "artifacts": artifacts,
                }
                await emit_capability_hook(
                    "after_tool_call",
                    {
                        "tool_call_id": tc["id"],
                        "tool_name": tc["name"],
                        "status": "succeeded",
                        "worker_run_id": (worker_context or {}).get("worker_run_id"),
                    },
                    policy_action="allow",
                )
                consecutive_errors = 0

            except Exception as e:
                if isinstance(e, (APIToolConfirmationRequired, BrowserAutomationConfirmationRequired, AcquiredToolConfirmationRequired)):
                    destructive_hit = True
                    confirmation_args = dict(getattr(e, "original_args", None) or e.sanitized_args)
                    if isinstance(e, (BrowserAutomationConfirmationRequired, AcquiredToolConfirmationRequired)):
                        confirmation_args["__public_args"] = dict(e.sanitized_args)
                    if acquired_tool_manifest_version:
                        confirmation_args["__acquired_tool_manifest_version"] = acquired_tool_manifest_version
                    confirmation_args["__acquisition_confirmation_context"] = e.confirmation_context
                    yield {
                        "type": "confirmation_required",
                        "tool_call_id": tc["id"],
                        "tool_name": tc["name"],
                        "args": confirmation_args,
                        "risk": e.risk,
                        "timeout_s": 30,
                    }
                    await emit_capability_hook(
                        "after_tool_call",
                        {
                            "tool_call_id": tc["id"],
                            "tool_name": tc["name"],
                            "status": "needs_confirmation",
                            "risk": e.risk,
                            "worker_run_id": (worker_context or {}).get("worker_run_id"),
                        },
                        policy_action="confirm",
                    )
                    break
                consecutive_errors += 1
                if tc["name"] == "code_as_action":
                    _schedule_code_as_action_acquisition(
                        acquisition_recorder=acquisition_recorder,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        source_run_id=run_id,
                        tool_call_id=tc["id"],
                        trace=code_action_trace
                        or _new_code_action_trace(str(args.get("script", ""))),
                        status="failed",
                        risk_level=risk.value,
                        failure_reason=str(e),
                        mount_bundle=code_action_mount_bundle,
                    )
                    acquisition_event = _code_as_action_acquisition_event(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        source_run_id=run_id,
                        tool_call_id=tc["id"],
                        status="failed",
                        risk_level=risk.value,
                        failure_reason=str(e),
                    )
                    if acquisition_event is not None:
                        yield acquisition_event
                await emit_capability_hook(
                    "after_tool_call",
                    {
                        "tool_call_id": tc["id"],
                        "tool_name": tc["name"],
                        "status": "failed",
                        "error": str(e),
                        "worker_run_id": (worker_context or {}).get("worker_run_id"),
                    },
                    policy_action="allow",
                )
                yield {
                    "type": "tool_error",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "error": str(e),
                    "consecutive": consecutive_errors,
                }
                result = f"Error: {e}"

            # Append tool call metadata to message history so the LLM sees
            # what happened on the next iteration.
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result) if result is not None else "pending_confirmation",
                }
            )

        # ---- Safety break: destructive tool halted the loop ----
        if destructive_hit:
            yield {"type": "done", "tokens_used": tokens_used}
            return

        # ---- Loop back to Step 1 for another iteration ----

    if turn_budget is not None:
        tokens_used = turn_budget.consumed
    yield {"type": "done", "tokens_used": tokens_used}


class _CappedTextBuffer:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._parts: list[str] = []
        self._length = 0

    def append(self, value: Any) -> None:
        text = str(value or "")
        if not text or self._length >= self._limit:
            return
        remaining = self._limit - self._length
        chunk = text[:remaining]
        self._parts.append(chunk)
        self._length += len(chunk)

    def text(self) -> str:
        return "".join(self._parts)


class _CappedSandboxEvents:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._events: list[dict[str, Any]] = []

    def append(self, event: dict[str, Any]) -> None:
        if len(self._events) >= self._limit:
            self._events.pop(0)
        self._events.append(_sandbox_event_for_acquisition(event))

    def items(self) -> list[dict[str, Any]]:
        return list(self._events)


def _new_code_action_trace(script: str) -> dict[str, Any]:
    return {
        "script": script,
        "stdout": _CappedTextBuffer(_ACQUISITION_CAPTURE_TEXT_CHARS),
        "stderr": _CappedTextBuffer(_ACQUISITION_CAPTURE_TEXT_CHARS),
        "error": _CappedTextBuffer(_ACQUISITION_CAPTURE_TEXT_CHARS),
        "sandbox_events": _CappedSandboxEvents(_ACQUISITION_MAX_SANDBOX_EVENTS),
    }


def _capture_code_action_event(trace: dict[str, Any], event: dict[str, Any]) -> None:
    events = trace.get("sandbox_events")
    if isinstance(events, _CappedSandboxEvents):
        events.append(event)

    if event.get("type") != "sandbox_output":
        return
    stream = event.get("stream")
    if stream not in {"stdout", "stderr", "error"}:
        return
    buffer = trace.get(stream)
    if isinstance(buffer, _CappedTextBuffer):
        buffer.append(event.get("data", ""))


def _trace_text(trace: dict[str, Any], key: str, legacy_key: str) -> str:
    value = trace.get(key)
    if isinstance(value, _CappedTextBuffer):
        return value.text()
    if value is not None:
        return str(value)
    return "".join(str(part) for part in trace.get(legacy_key, []))


def _trace_sandbox_events(trace: dict[str, Any]) -> list[dict[str, Any]]:
    events = trace.get("sandbox_events", [])
    if isinstance(events, _CappedSandboxEvents):
        return events.items()
    return list(events)


def _capped_text(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit]


def _capped_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _capped_text(value, _ACQUISITION_CAPTURE_TEXT_CHARS)


def _sandbox_event_for_acquisition(event: dict[str, Any]) -> dict[str, Any]:
    """Keep acquisition evidence bounded before the facade redacts it."""

    summary = {
        "type": event.get("type"),
        "phase": event.get("phase"),
        "stream": event.get("stream"),
    }
    if event.get("data") is not None:
        summary["data"] = _capped_text(
            event.get("data", ""),
            _ACQUISITION_CAPTURE_EVENT_DATA_CHARS,
        )
    return {key: value for key, value in summary.items() if value is not None}


def _schedule_code_as_action_acquisition(**kwargs: Any) -> None:
    """Start best-effort recording without delaying tool completion."""

    if not kwargs.get("tenant_id") or not kwargs.get("user_id"):
        return
    task = asyncio.create_task(_record_code_as_action_acquisition(**kwargs))
    _ACQUISITION_RECORDING_TASKS.add(task)
    task.add_done_callback(_ACQUISITION_RECORDING_TASKS.discard)


def _code_as_action_acquisition_event(
    *,
    tenant_id: str | None,
    user_id: str | None,
    source_run_id: str | None,
    tool_call_id: str | None,
    status: str,
    risk_level: str,
    failure_reason: str | None = None,
) -> dict[str, Any] | None:
    """Expose a real V3 exploration notice without waiting on durable analysis."""

    if not tenant_id or not user_id:
        return None
    try:
        from app.core.acquisition.facade import acquisition_enabled, acquisition_notice

        if not acquisition_enabled():
            return None
        return acquisition_notice(
            "acquisition_exploration",
            {
                "source_run_id": source_run_id,
                "tool_call_id": tool_call_id,
                "strategy": "code_as_action",
                "status": status,
                "risk_level": risk_level,
                "failure_reason": failure_reason,
            },
        )
    except Exception:
        return None


async def _record_code_as_action_acquisition(
    *,
    acquisition_recorder: Any | None,
    tenant_id: str | None,
    user_id: str | None,
    conversation_id: str | None,
    source_run_id: str | None,
    tool_call_id: str | None,
    trace: dict[str, Any],
    status: str,
    risk_level: str,
    failure_reason: str | None,
    mount_bundle: dict[str, Any] | None,
) -> None:
    """Best-effort acquisition recording must never block tool completion."""

    if not tenant_id or not user_id:
        return
    try:
        recorder = acquisition_recorder
        if recorder is None:
            from app.core.acquisition.facade import record_code_as_action_exploration

            recorder = record_code_as_action_exploration
        result = recorder(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            source_run_id=source_run_id,
            tool_call_id=tool_call_id,
            script=str(trace.get("script", "")),
            status=status,
            risk_level=risk_level,
            stdout=_trace_text(trace, "stdout", "stdout_parts"),
            stderr=(
                _trace_text(trace, "stderr", "stderr_parts")
                + _trace_text(trace, "error", "error_parts")
            ),
            sandbox_events=_trace_sandbox_events(trace),
            failure_reason=_capped_optional_text(failure_reason),
            mount_bundle=mount_bundle,
        )
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=ACQUISITION_RECORD_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.exception("code-as-action acquisition recording timed out")
    except Exception:
        logger.exception("code-as-action acquisition recording failed")
