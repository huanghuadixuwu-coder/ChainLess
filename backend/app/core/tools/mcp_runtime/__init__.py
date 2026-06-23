"""Isolated MCP stdio runtime boundary.

The backend MCP client owns remote HTTP/SSE transports.  Stdio MCP servers must
cross this package so policy validation and lifecycle cleanup stay centralized.
"""

from .client import IsolatedMCPRuntimeClient
from .policy import (
    MCPRuntimePolicyError,
    StdioRuntimePolicy,
    approved_payload_hash,
    validate_stdio_runtime_policy,
)
from .supervisor import IsolatedMCPRuntimeSupervisor, RuntimeLifecycleEvidence

__all__ = [
    "IsolatedMCPRuntimeClient",
    "IsolatedMCPRuntimeSupervisor",
    "MCPRuntimePolicyError",
    "RuntimeLifecycleEvidence",
    "StdioRuntimePolicy",
    "approved_payload_hash",
    "validate_stdio_runtime_policy",
]
