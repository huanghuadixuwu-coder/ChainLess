"""Tool risk classification for safety-aware execution.

Provides a three-tier risk model:

- **safe** — Tools that are purely read-only or informational; auto-execute.
- **risky** — Tools that mutate state (write files, fetch external content);
  auto-execute but the frontend should notify the user.
- **destructive** — Tools that can cause irreversible damage (delete files,
  execute shell commands); user confirmation is REQUIRED before execution.
"""

from enum import Enum


class RiskLevel(str, Enum):
    SAFE = "safe"  # Auto-execute
    RISKY = "risky"  # Auto-execute, user notified
    DESTRUCTIVE = "destructive"  # User confirmation REQUIRED


# ---------------------------------------------------------------------------
# Built-in tool classifications
# ---------------------------------------------------------------------------

BUILTIN_RISK: dict[str, RiskLevel] = {
    "file_read": RiskLevel.SAFE,
    "file_list": RiskLevel.SAFE,
    "web_search": RiskLevel.SAFE,
    "web_fetch": RiskLevel.RISKY,
    "file_write": RiskLevel.RISKY,
    "shell_exec": RiskLevel.DESTRUCTIVE,
    "file_delete": RiskLevel.DESTRUCTIVE,
    "code_as_action": RiskLevel.RISKY,  # Sandboxed, but executes arbitrary code
}

MCP_DEFAULT_RISK = RiskLevel.RISKY  # Unknown MCP tools default to RISKY


def classify_tool(tool_name: str, tool_type: str = "builtin") -> RiskLevel:
    """Classify a tool into one of the three risk levels.

    Args:
        tool_name: The name of the tool (e.g. ``"file_read"``, ``"shell_exec"``).
        tool_type: The tool registry type — ``"builtin"`` or ``"mcp"``.

    Returns:
        The ``RiskLevel`` for the given tool.  Builtins unknown to the
        classification table default to ``RISKY``.  MCP tools default to
        ``RISKY``.
    """
    if tool_type == "builtin":
        return BUILTIN_RISK.get(tool_name, RiskLevel.RISKY)
    elif tool_type == "mcp":
        return MCP_DEFAULT_RISK
    return RiskLevel.RISKY


def is_pre_authorized(tool_name: str, pre_auth_list: list[str]) -> bool:
    """Check whether *tool_name* is covered by a pre-authorization list.

    The wildcard ``"*"`` authorises all tools.  This is a placeholder for
    Phase 6 where user-configured pre-auth lists are persisted.
    """
    return tool_name in pre_auth_list or "*" in pre_auth_list
