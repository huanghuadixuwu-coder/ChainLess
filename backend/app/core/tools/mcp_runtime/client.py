"""Client facade for isolated stdio MCP runtimes."""

from __future__ import annotations

import json
from typing import Any

from .policy import StdioRuntimePolicy
from .supervisor import IsolatedMCPRuntimeSupervisor


class IsolatedMCPRuntimeClient:
    """Delegates stdio MCP discovery and calls to an isolated supervisor."""

    def __init__(
        self,
        policy: StdioRuntimePolicy,
        supervisor: IsolatedMCPRuntimeSupervisor | None = None,
    ) -> None:
        self.policy = policy
        self.supervisor = supervisor or IsolatedMCPRuntimeSupervisor()
        self._tools: list[dict[str, Any]] = []

    async def connect(self) -> None:
        self._tools = await self.supervisor.start(self.policy)

    async def call_tool(self, local_name: str, args: dict[str, Any]) -> str:
        result = await self.supervisor.call_tool(self.policy, local_name, args)
        if isinstance(result, list):
            return json.dumps(result, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    async def disconnect(self, reason: str = "success") -> None:
        await self.supervisor.cleanup(self.policy.server_name, reason)

    async def reconnect(self) -> None:
        self._tools = await self.supervisor.reconnect(self.policy)

    async def recover_after_backend_restart(self) -> None:
        self._tools = await self.supervisor.recover_after_backend_restart(self.policy)

    async def rollback(self) -> None:
        await self.supervisor.rollback(self.policy.server_name)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return self._tools
