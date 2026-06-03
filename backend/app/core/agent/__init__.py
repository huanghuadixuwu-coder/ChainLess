"""Agent Engine — ReAct loop, tool routing, code execution, and prompt builder.

Layers
------
- :mod:`app.core.agent.engine`          — ReAct loop with token budget + circuit breaker
- :mod:`app.core.agent.tool_router`     — Routes tool calls to builtin / MCP executors
- :mod:`app.core.agent.code_executor`   — Code-as-action execution in sandbox
- :mod:`app.core.agent.prompt_builder`  — Token-aware context builder
"""
