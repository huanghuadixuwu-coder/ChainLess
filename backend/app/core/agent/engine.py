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

import json
from typing import AsyncIterator

from app.core.agent.code_executor import execute_code_as_action
from app.core.agent.tool_router import execute_tool
from app.core.tools.builtin import ALL_TOOLS
from app.core.tools.classifier import RiskLevel, classify_tool

# ---------------------------------------------------------------------------
# Constants — guardrails
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 10
MAX_TOKENS_PER_TURN = 100_000
MAX_CONSECUTIVE_ERRORS = 3


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
        is_sub_agent: Reserved for sub-agent spawning (Phase 4).

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
    consecutive_errors = 0
    active_tools = tools or ALL_TOOLS

    while iteration < MAX_ITERATIONS:
        # ---- Guard: token budget ----
        if tokens_used >= MAX_TOKENS_PER_TURN:
            yield {
                "type": "error",
                "code": "TOKEN_BUDGET_EXHAUSTED",
                "message": f"Exceeded {MAX_TOKENS_PER_TURN} token budget",
            }
            break

        # ---- Guard: circuit breaker ----
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            yield {
                "type": "error",
                "code": "CIRCUIT_BREAKER",
                "message": f"{MAX_CONSECUTIVE_ERRORS} consecutive tool errors",
            }
            break

        iteration += 1

        # ---- Step 1: LLM call ----
        tool_calls_buffer: dict[int, dict] = {}

        async for delta in gateway.chat_stream(provider, messages, active_tools):
            tokens_used += 1

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
                tool_calls_buffer[idx]["name"] += delta.get("name", "")
                tool_calls_buffer[idx]["arguments"] += delta.get("arguments", "")

        # ---- Step 2: No tool calls -> response is complete ----
        if not tool_calls_buffer:
            break

        # ---- Step 3: Execute each tool call ----
        for tc in tool_calls_buffer.values():
            args = json.loads(tc["arguments"]) if tc["arguments"] else {}

            yield {"type": "tool_call_start", "name": tc["name"], "args": args}

            # ---- Safety check: classify tool risk ----
            risk = classify_tool(tc["name"])
            if risk == RiskLevel.DESTRUCTIVE:
                yield {
                    "type": "confirmation_required",
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
                if tc["name"] == "code_as_action":
                    result = await execute_code_as_action(
                        args.get("script", ""), sandbox_manager
                    )
                elif tc["name"] == "shell_exec":
                    # shell_exec goes through sandbox (same mechanism)
                    script = args.get("command", "")
                    result = await execute_code_as_action(script, sandbox_manager)
                else:
                    result = await execute_tool(tc["name"], args)

                yield {
                    "type": "tool_result",
                    "name": tc["name"],
                    "result": str(result)[:2000],
                }
                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                yield {
                    "type": "tool_error",
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
        # (risk is set inside the for-loop above; always defined here
        #  because tool_calls_buffer was non-empty when we entered the loop)
        if risk == RiskLevel.DESTRUCTIVE:
            yield {"type": "done", "tokens_used": tokens_used}
            return

        # ---- Loop back to Step 1 for another iteration ----

    yield {"type": "done", "tokens_used": tokens_used}
