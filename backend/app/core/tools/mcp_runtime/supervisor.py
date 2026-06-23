"""Supervisor client for isolated stdio MCP runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .policy import StdioRuntimePolicy


@dataclass
class RuntimeLifecycleEvidence:
    """Lifecycle evidence retained by the backend for audit and tests."""

    server_name: str
    image_ref: str
    package_digest: str
    cleanup_events: list[str] = field(default_factory=list)
    reconnects: int = 0
    backend_restarts: int = 0
    rollbacks: int = 0
    active: bool = False


class IsolatedMCPRuntimeSupervisor:
    """Supervises approved isolated stdio sessions through mcp-runtime HTTP."""

    def __init__(self) -> None:
        self._sessions: dict[str, StdioRuntimePolicy] = {}
        self._evidence: dict[str, RuntimeLifecycleEvidence] = {}

    async def start(self, policy: StdioRuntimePolicy) -> list[dict[str, Any]]:
        evidence = self._evidence_for(policy)
        payload = self._runtime_payload(policy)
        response = await self._post(policy, "/discover", payload)
        tools = response.get("tools")
        if not isinstance(tools, list):
            raise ValueError("mcp-runtime /discover response must include tools")
        self._sessions[policy.server_name] = policy
        evidence.active = True
        return tools

    async def call_tool(
        self,
        policy: StdioRuntimePolicy,
        local_name: str,
        args: dict[str, Any],
    ) -> Any:
        if policy.server_name not in self._sessions:
            await self.start(policy)
        payload = {
            **self._runtime_payload(policy),
            "tool_name": local_name,
            "arguments": args,
        }
        try:
            response = await self._post(policy, "/call", payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 504:
                await self.cleanup(policy.server_name, "timeout")
            elif exc.response.status_code == 413:
                await self.cleanup(policy.server_name, "output_limit")
            else:
                await self.cleanup(policy.server_name, "failure")
            raise
        except httpx.TimeoutException:
            await self.cleanup(policy.server_name, "timeout")
            raise
        except Exception:
            evidence = self._evidence_for(policy)
            max_restarts = int(policy.restart_policy.get("max_restarts", 0))
            if evidence.reconnects < max_restarts:
                evidence.reconnects += 1
                await self.cleanup(policy.server_name, "reconnect")
                await self.start(policy)
                response = await self._post(policy, "/call", payload)
            else:
                await self.cleanup(policy.server_name, "failure")
                raise
        content = response.get("content")
        if not isinstance(content, list):
            raise ValueError("mcp-runtime /call response must include content")
        encoded = str(content).encode("utf-8")
        if len(encoded) > policy.max_output_bytes:
            await self.cleanup(policy.server_name, "output_limit")
            raise ValueError("mcp-runtime response exceeds stdio_max_output_bytes")
        return content

    async def cleanup(self, server_name: str, reason: str) -> None:
        policy = self._sessions.pop(server_name, None)
        if policy is not None:
            try:
                await self._post(policy, "/cleanup", {"server_name": server_name, "reason": reason})
            except Exception:
                pass
        evidence = self._evidence.get(server_name)
        if evidence is None:
            return
        evidence.active = False
        evidence.cleanup_events.append(reason)

    async def reconnect(self, policy: StdioRuntimePolicy) -> list[dict[str, Any]]:
        evidence = self._evidence_for(policy)
        evidence.reconnects += 1
        await self.cleanup(policy.server_name, "reconnect")
        return await self.start(policy)

    async def recover_after_backend_restart(self, policy: StdioRuntimePolicy) -> list[dict[str, Any]]:
        evidence = self._evidence_for(policy)
        evidence.backend_restarts += 1
        await self.cleanup(policy.server_name, "backend_restart")
        return await self.start(policy)

    async def rollback(self, server_name: str) -> None:
        evidence = self._evidence.get(server_name)
        if evidence is not None:
            evidence.rollbacks += 1
        await self.cleanup(server_name, "rollback")

    def evidence(self, server_name: str) -> RuntimeLifecycleEvidence | None:
        return self._evidence.get(server_name)

    def _evidence_for(self, policy: StdioRuntimePolicy) -> RuntimeLifecycleEvidence:
        if policy.server_name not in self._evidence:
            self._evidence[policy.server_name] = RuntimeLifecycleEvidence(
                server_name=policy.server_name,
                image_ref=policy.image_ref,
                package_digest=policy.package_digest,
            )
        return self._evidence[policy.server_name]

    def _runtime_payload(self, policy: StdioRuntimePolicy) -> dict[str, Any]:
        return {
            "server_name": policy.server_name,
            "command": policy.command,
            "args": policy.args,
            "env_secret_refs": policy.env_secret_refs,
            "filesystem_policy": policy.filesystem_policy,
            "network_policy": policy.network_policy,
            "resource_limits": policy.resource_limits,
            "max_session_seconds": policy.max_session_seconds,
            "max_output_bytes": policy.max_output_bytes,
            "restart_policy": policy.restart_policy,
            "image_ref": policy.image_ref,
            "package_digest": policy.package_digest,
            "command_provenance": policy.command_provenance,
            "approved_payload_hash": policy.approved_payload_hash,
        }

    async def _post(self, policy: StdioRuntimePolicy, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        timeout = max(float(policy.max_session_seconds) + 5.0, 10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{policy.runtime_url}{path}", json=payload)
            response.raise_for_status()
            self._enforce_runtime_http_cap(policy, response)
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError(f"mcp-runtime {path} response must be an object")
        return data

    def _enforce_runtime_http_cap(
        self,
        policy: StdioRuntimePolicy,
        response: httpx.Response,
    ) -> None:
        # The MCP SDK materializes stdio tool content inside mcp-runtime.  Until a
        # custom streaming MCP transport exists, fail closed before backend JSON
        # parsing so oversized runtime HTTP responses cannot amplify in backend.
        headers = getattr(response, "headers", {}) or {}
        content_length = headers.get("content-length") if hasattr(headers, "get") else None
        if content_length is not None:
            try:
                if int(content_length) > policy.max_output_bytes:
                    raise ValueError("mcp-runtime HTTP response exceeds stdio_max_output_bytes")
            except ValueError as exc:
                if "stdio_max_output_bytes" in str(exc):
                    raise
                raise ValueError("mcp-runtime HTTP response has invalid content-length") from exc
        content = getattr(response, "content", b"")
        if content and len(content) > policy.max_output_bytes:
            raise ValueError("mcp-runtime HTTP response exceeds stdio_max_output_bytes")
