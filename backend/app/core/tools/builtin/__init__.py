"""Builtin tools — aggregates all tool definitions and executors.

Available tool families:

- ``file_ops``   — file_read, file_write, file_list
- ``web``        — web_fetch, web_search
- ``sandbox``    — shell_exec (requires SandboxManager dependency injection)
"""

from .file_ops import FILE_TOOLS, execute as file_exec
from .sandbox import SHELL_TOOLS, execute as shell_exec
from .web import WEB_TOOLS, execute as web_exec

# All tool schemas (OpenAI function format).
ALL_TOOLS = FILE_TOOLS + WEB_TOOLS + SHELL_TOOLS

# ---------------------------------------------------------------------------
# Executor lookup tables
# ---------------------------------------------------------------------------
# Tools that accept the standard ``(tool_name, args)`` signature.
TOOL_EXECUTORS: dict[str, object] = {}
for name in ["file_read", "file_write", "file_list"]:
    TOOL_EXECUTORS[name] = file_exec
for name in ["web_fetch", "web_search", "weather_get"]:
    TOOL_EXECUTORS[name] = web_exec

# ``shell_exec`` has a different signature
# (needs ``sandbox_manager`` injection) so it is NOT included in the
# flat TOOL_EXECUTORS dict.  The Agent Engine is responsible for resolving
# it via ``resolve_executor(tool_name, context)``.

__all__ = [
    "ALL_TOOLS",
    "TOOL_EXECUTORS",
    "FILE_TOOLS",
    "WEB_TOOLS",
    "SHELL_TOOLS",
    "file_exec",
    "web_exec",
    "shell_exec",
]
