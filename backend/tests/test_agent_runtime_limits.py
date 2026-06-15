"""W8 agent runtime limits and deterministic route selection."""

from __future__ import annotations

import pytest

from app.core.agent.code_executor import CODE_AS_ACTION_TOOL
from app.core.agent.engine import run_agent, select_execution_route
from app.core.tools.builtin import ALL_TOOLS


@pytest.mark.asyncio
async def test_turn_budget_exhaustion_is_observable_not_uncaught() -> None:
    class ChattyGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            for _ in range(5):
                yield {"type": "text", "content": "x"}

    events = [
        event
        async for event in run_agent(
            ChattyGateway(),
            object(),
            "default",
            [{"role": "user", "content": "talk"}],
            tools=[],
            tenant_id="tenant-a",
            max_tokens_per_turn=2,
        )
    ]

    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "TOKEN_BUDGET_EXHAUSTED"


@pytest.mark.asyncio
async def test_authorized_tool_names_block_visible_but_unapproved_tools() -> None:
    class Gateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {
                "type": "tool_call",
                "index": 0,
                "id": "call-web",
                "name": "web_fetch",
                "arguments": '{"url":"https://example.com"}',
            }

    events = [
        event
        async for event in run_agent(
            Gateway(),
            object(),
            "default",
            [{"role": "user", "content": "fetch"}],
            tools=ALL_TOOLS,
            tenant_id="tenant-a",
            authorized_tool_names={"weather_get"},
            max_consecutive_errors=1,
        )
    ]

    blocked = next(event for event in events if event["type"] == "tool_error")
    assert blocked["code"] == "TOOL_NOT_AUTHORIZED"
    assert blocked["blocked"] is True
    assert blocked["name"] == "web_fetch"
    assert any(event.get("code") == "CIRCUIT_BREAKER" for event in events)


def test_complexity_router_is_deterministic_and_falls_back_to_react() -> None:
    tools = ALL_TOOLS + [CODE_AS_ACTION_TOOL]

    assert select_execution_route("What is the weather in Wuxi?", tools) == "direct_tool:weather_get"
    assert select_execution_route("Run Python code to compute 6*7", tools) == "code_as_action"
    assert select_execution_route("Run Python code", ALL_TOOLS) == "react"
    assert select_execution_route("Explain this architecture", tools) == "react"
