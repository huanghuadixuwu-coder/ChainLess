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
import json
import uuid
from typing import AsyncIterator, Any

from app.core.artifacts import ToolExecutionResult
from app.core.agent.code_executor import stream_code_as_action
from app.core.agent.tool_router import execute_tool
from app.core.tools.builtin import ALL_TOOLS
from app.core.tools.builtin.sandbox import execute as execute_shell_exec
from app.core.tools.classifier import RiskLevel, classify_tool

# ---------------------------------------------------------------------------
# Constants — guardrails
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 10
MAX_TOKENS_PER_TURN = 100_000
MAX_CONSECUTIVE_ERRORS = 3


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

            yield {
                "type": "tool_call_start",
                "tool_call_id": tc["id"],
                "name": tc["name"],
                "args": args,
                "risk": risk.value,
            }

            # ---- Safety check: classify tool risk ----
            if risk == RiskLevel.DESTRUCTIVE:
                destructive_hit = True
                yield {
                    "type": "confirmation_required",
                    "tool_call_id": tc["id"],
                    "tool_name": tc["name"],
                    "args": args,
                    "risk": "destructive",
                    "timeout_s": 30,
                }
                # Engine pauses — caller handles user response via
                # a separate confirmation endpoint (Phase 6).
                # For now, break out of the ReAct loop entirely.
                break

            try:
                tool_context = {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "tool_call_id": tc["id"],
                }
                if tc["name"] == "code_as_action":
                    if is_sub_agent:
                        raise RuntimeError("sub-agents cannot execute Code-as-Action")
                    if not tenant_id:
                        raise RuntimeError("Code-as-Action requires a trusted tenant scope")
                    output_parts: list[str] = []
                    async for sandbox_event in stream_code_as_action(
                        args.get("script", ""),
                        sandbox_manager,
                        gateway=gateway,
                        tenant_id=tenant_id,
                        provider=provider,
                        parent_budget=turn_budget,
                    ):
                        if sandbox_event["type"] == "sandbox_output":
                            data = sandbox_event.get("data", "")
                            if sandbox_event.get("stream") == "error":
                                output_parts.append(f"[ERROR] {data}")
                            elif sandbox_event.get("stream") != "artifact":
                                output_parts.append(data)
                        yield sandbox_event
                    result = "\n".join(output_parts)
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
                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
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
