"""MCP Manager — tracks all registered MCP servers and dispatches tool calls.

Provides a global singleton ``mcp_manager`` that the rest of the application
uses to register, unregister, and query MCP servers and their tools.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tools.mcp_runtime import IsolatedMCPRuntimeSupervisor
from app.models.acquisition import MCPServerConfiguration

from .client import MCPToolClient


@dataclass
class MCPRecoveryResult:
    """Restart recovery summary with per-record isolation evidence."""

    recovered: int = 0
    failed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)


@dataclass
class _RegistryLockEntry:
    """Reference-counted per-registry-key mutation lock."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class MCPManager:
    """Manages the lifecycle of zero or more MCP server connections.

    The manager acts as a registry: you *register* an MCP server with a name
    and config, which starts the server and discovers its tools; you can then
    route tool calls to the owning server via ``execute``.
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPToolClient] = {}
        self._client_owners: dict[str, str | None] = {}
        self._configs: dict[str, dict[str, Any]] = {}
        self._runtime_supervisor = IsolatedMCPRuntimeSupervisor()
        self._registry_locks: dict[str, _RegistryLockEntry] = {}
        self._registry_locks_guard = asyncio.Lock()

    def _registry_key(self, name: str, owner: str | None = None) -> str:
        if owner is None:
            return name
        return f"{owner}:{name}"

    def _visible_to(self, registry_key: str, owner: str | None = None) -> bool:
        registered_owner = self._client_owners.get(registry_key)
        return owner is None or registered_owner == owner

    @asynccontextmanager
    async def _registry_operation_lock(
        self,
        name: str,
        owner: str | None,
    ) -> AsyncIterator[None]:
        registry_key = self._registry_key(name, owner)
        async with self._registry_locks_guard:
            entry = self._registry_locks.get(registry_key)
            if entry is None:
                entry = _RegistryLockEntry()
                self._registry_locks[registry_key] = entry
            entry.users += 1
        await entry.lock.acquire()
        try:
            yield
        finally:
            entry.lock.release()
            async with self._registry_locks_guard:
                entry.users -= 1
                if entry.users == 0 and self._registry_locks.get(registry_key) is entry:
                    self._registry_locks.pop(registry_key, None)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def register(
        self,
        name: str,
        config: dict[str, Any],
        owner: str | None = None,
    ) -> list[dict[str, Any]]:
        """Register an MCP server and discover its tools.

        If a server with the same *name* already exists it is disconnected
        first (allowing re-registration / hot-reload).

        Args:
            name: Unique name for the MCP server instance.
            config: Dictionary with keys:
                - ``command`` (str, required): shell command to start the server.
                - ``args`` (list[str], optional): CLI arguments.
                - ``env`` (dict[str,str], optional): extra environment variables.
                - ``transport`` (stdio|http|sse, optional): MCP transport.
                - ``url`` (str, optional): HTTP/SSE MCP endpoint base URL.
                - ``idle_timeout_s`` (float, optional): reconnect after idle.
                - ``runtime_kind`` and ``stdio_*`` keys for isolated stdio.

        Returns:
            List of discovered tool definitions (``openai`` format).
        """
        client = await self._connect_client(name, config, owner)
        await self._install_connected_client(name, config, owner, client)
        return client.get_tool_definitions()

    async def unregister(self, name: str, owner: str | None = None) -> None:
        """Unregister an MCP server and disconnect it."""
        registry_key = self._registry_key(name, owner)
        if registry_key in self._clients:
            await self._clients[registry_key].disconnect()
            del self._clients[registry_key]
            self._client_owners.pop(registry_key, None)
            self._configs.pop(registry_key, None)

    def _build_client(
        self,
        name: str,
        config: dict[str, Any],
    ) -> MCPToolClient:
        return MCPToolClient(
            name,
            config.get("command"),
            config.get("args", []),
            config.get("env"),
            transport=config.get("transport", "stdio"),
            url=config.get("url"),
            idle_timeout_s=config.get("idle_timeout_s"),
            runtime_kind=config.get("runtime_kind"),
            env_secret_refs=config.get("env_secret_refs"),
            egress_policy=config.get("egress_policy"),
            stdio_runtime_image_ref=config.get("stdio_runtime_image_ref"),
            stdio_runtime_url=config.get("stdio_runtime_url"),
            stdio_command_provenance=config.get("stdio_command_provenance"),
            stdio_package_digest=config.get("stdio_package_digest"),
            stdio_filesystem_policy=config.get("stdio_filesystem_policy"),
            stdio_network_policy=config.get("stdio_network_policy"),
            stdio_resource_limits=config.get("stdio_resource_limits"),
            stdio_max_session_seconds=config.get("stdio_max_session_seconds"),
            stdio_max_output_bytes=config.get("stdio_max_output_bytes"),
            stdio_restart_policy=config.get("stdio_restart_policy"),
            tool_definitions=config.get("tool_definitions") or config.get("tools"),
            egress_network_scope=config.get("egress_network_scope", "allowlisted_domains"),
            runtime_supervisor=self._runtime_supervisor,
            remote_transport_adapter=config.get("remote_transport_adapter"),
        )

    async def _connect_client(
        self,
        name: str,
        config: dict[str, Any],
        owner: str | None,
    ) -> MCPToolClient:
        client = self._build_client(name, config)
        await client.connect()
        return client

    async def _install_connected_client(
        self,
        name: str,
        config: dict[str, Any],
        owner: str | None,
        client: MCPToolClient,
    ) -> None:
        registry_key = self._registry_key(name, owner)
        previous_client = self._clients.get(registry_key)
        self._clients[registry_key] = client
        self._client_owners[registry_key] = owner
        self._configs[registry_key] = dict(config)
        if previous_client is not None and previous_client is not client:
            await previous_client.disconnect()

    async def register_durable(
        self,
        db: AsyncSession,
        name: str,
        config: dict[str, Any],
        *,
        tenant_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """Register an MCP server and persist its durable enabled config."""
        async with self._registry_operation_lock(name, tenant_id):
            return await self._register_durable_locked(
                db,
                name,
                config,
                tenant_id=tenant_id,
                user_id=user_id,
            )

    async def _register_durable_locked(
        self,
        db: AsyncSession,
        name: str,
        config: dict[str, Any],
        *,
        tenant_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        normalized = self._normalize_config(config)
        records = (
            await db.execute(
                select(MCPServerConfiguration).where(
                    MCPServerConfiguration.tenant_id == uuid.UUID(tenant_id),
                    MCPServerConfiguration.name == name,
                ).order_by(MCPServerConfiguration.created_at.asc())
            )
        ).scalars().all()
        enabled_records = [record for record in records if record.enabled]
        if enabled_records:
            return await self._replace_enabled_durable(
                db,
                name,
                normalized,
                records,
                enabled_records[0],
                tenant_id=tenant_id,
            )

        record = records[0] if records else MCPServerConfiguration(
            tenant_id=uuid.UUID(tenant_id),
            user_id=uuid.UUID(user_id),
            name=name,
            transport=normalized.get("transport", "stdio"),
            runtime_kind=normalized.get("runtime_kind"),
            risk_level=normalized.get("risk_level", "risky"),
        )
        self._apply_config_record(record, normalized, tools=None, enabled=False)
        for duplicate in records[1:]:
            duplicate.enabled = False
            duplicate.disabled_at = datetime.now(timezone.utc)
        if not records:
            db.add(record)
        await db.commit()
        client: MCPToolClient | None = None
        try:
            client = await self._connect_client(name, normalized, tenant_id)
            tools = client.get_tool_definitions()
        except Exception:
            await self.unregister(name, tenant_id)
            raise
        try:
            self._mark_config_record_connected(record, tools)
            await db.commit()
        except Exception:
            await db.rollback()
            if client is not None:
                await client.disconnect()
            await self.unregister(name, tenant_id)
            raise
        await self._install_connected_client(name, normalized, tenant_id, client)
        return tools

    async def _replace_enabled_durable(
        self,
        db: AsyncSession,
        name: str,
        normalized: dict[str, Any],
        records: list[MCPServerConfiguration],
        record: MCPServerConfiguration,
        *,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        client = await self._connect_client(name, normalized, tenant_id)
        tools = client.get_tool_definitions()
        try:
            self._apply_config_record(record, normalized, tools=tools, enabled=True)
            now = datetime.now(timezone.utc)
            for duplicate in records:
                if duplicate.id == record.id:
                    continue
                duplicate.enabled = False
                duplicate.disabled_at = now
            await db.commit()
        except Exception:
            await db.rollback()
            await client.disconnect()
            raise
        await self._install_connected_client(name, normalized, tenant_id, client)
        return tools

    async def unregister_durable(
        self,
        db: AsyncSession,
        name: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> None:
        """Unregister an MCP server and disable its durable config."""
        async with self._registry_operation_lock(name, tenant_id):
            await self._unregister_durable_locked(
                db,
                name,
                tenant_id=tenant_id,
                user_id=user_id,
            )

    async def _unregister_durable_locked(
        self,
        db: AsyncSession,
        name: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> None:
        records = (
            await db.execute(
                select(MCPServerConfiguration).where(
                    MCPServerConfiguration.tenant_id == uuid.UUID(tenant_id),
                    MCPServerConfiguration.name == name,
                    MCPServerConfiguration.enabled.is_(True),
                )
            )
        ).scalars().all()
        for record in records:
            record.enabled = False
            record.disabled_at = datetime.now(timezone.utc)
        if records:
            await db.commit()
        await self.unregister(name, tenant_id)

    async def recover_enabled_from_db(
        self,
        db: AsyncSession,
        owner: str | None = None,
    ) -> MCPRecoveryResult:
        """Reload enabled durable configs after backend restart."""
        query = select(MCPServerConfiguration).where(MCPServerConfiguration.enabled.is_(True))
        if owner is not None:
            query = query.where(MCPServerConfiguration.tenant_id == uuid.UUID(owner))
        records = (await db.execute(query)).scalars().all()
        result = MCPRecoveryResult()
        for record in records:
            try:
                owner = str(record.tenant_id)
                async with self._registry_operation_lock(record.name, owner):
                    config = self._config_from_record(record)
                    await self.register(record.name, config, owner=owner)
                result.recovered += 1
            except Exception as exc:
                result.failed += 1
                result.failures.append(
                    {
                        "tenant_id": str(record.tenant_id),
                        "name": record.name,
                        "error": str(exc),
                    }
                )
        return result

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_all_tools(self, owner: str | None = None) -> list[dict[str, Any]]:
        """Return tool definitions visible to an owner scope."""
        tools: list[dict[str, Any]] = []
        for registry_key, client in self._clients.items():
            if not self._visible_to(registry_key, owner):
                continue
            tools.extend(client.get_tool_definitions())
        return tools

    def get_client_for_tool(
        self,
        tool_name: str,
        owner: str | None = None,
    ) -> MCPToolClient | None:
        """Return the client that owns a given fully qualified tool name.

        The tool name is expected to follow the prefix convention
        ``mcp__{server_name}__{tool_name}``.
        """
        for registry_key, client in self._clients.items():
            if not self._visible_to(registry_key, owner):
                continue
            if tool_name.startswith(f"mcp__{client.name}__"):
                return client
        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        owner: str | None = None,
    ) -> str:
        """Execute a tool on the MCP server that owns it.

        Args:
            tool_name: Fully qualified tool name
                (``mcp__{server_name}__{local_tool_name}``).
            args: Tool arguments.

        Returns:
            Tool result as a string.

        Raises:
            ValueError: If no registered server handles *tool_name*.
        """
        client = self.get_client_for_tool(tool_name, owner)
        if not client:
            raise ValueError(f"No MCP client for tool: {tool_name}")
        return await client.call_tool(tool_name, args)

    async def recover_after_backend_restart(self, owner: str | None = None) -> None:
        """Recover registered isolated stdio runtime sessions after restart."""
        for registry_key, client in list(self._clients.items()):
            if not self._visible_to(registry_key, owner):
                continue
            await client.recover_after_backend_restart()

    async def rollback(self, name: str, owner: str | None = None) -> None:
        """Cleanup runtime session after a failed activation rollback."""
        registry_key = self._registry_key(name, owner)
        client = self._clients.get(registry_key)
        if client is not None:
            await client.rollback()

    def _normalize_config(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(config)
        transport = normalized.get("transport", "stdio")
        normalized["transport"] = transport
        if not normalized.get("runtime_kind"):
            normalized["runtime_kind"] = {
                "http": "remote_http",
                "sse": "remote_sse",
                "stdio": "isolated_stdio",
            }.get(transport)
        return normalized

    def _apply_config_record(
        self,
        record: MCPServerConfiguration,
        config: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        *,
        enabled: bool,
    ) -> None:
        now = datetime.now(timezone.utc)
        record.transport = config.get("transport", "stdio")
        record.runtime_kind = config.get("runtime_kind")
        record.command = config.get("command")
        record.url = config.get("url")
        record.args = list(config.get("args", []))
        record.env_secret_refs = list(config.get("env_secret_refs", []))
        record.credential_connection_refs = list(config.get("credential_connection_refs", []))
        record.egress_policy = dict(config.get("egress_policy", {}))
        record.stdio_runtime_image_ref = config.get("stdio_runtime_image_ref")
        record.stdio_command_provenance = dict(config.get("stdio_command_provenance", {}))
        record.stdio_package_digest = config.get("stdio_package_digest")
        record.stdio_filesystem_policy = dict(config.get("stdio_filesystem_policy", {}))
        record.stdio_network_policy = dict(config.get("stdio_network_policy", {}))
        record.stdio_resource_limits = dict(config.get("stdio_resource_limits", {}))
        record.stdio_max_session_seconds = config.get("stdio_max_session_seconds")
        record.stdio_max_output_bytes = config.get("stdio_max_output_bytes")
        record.stdio_restart_policy = dict(config.get("stdio_restart_policy", {}))
        record.enabled = enabled
        record.risk_level = config.get("risk_level", "risky")
        if tools is not None:
            record.tool_schema_hash = hashlib.sha256(
                json.dumps(tools, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
        if enabled:
            record.last_verified_at = now
            record.last_connected_at = now
            record.disabled_at = None
        else:
            record.disabled_at = now

    def _mark_config_record_connected(
        self,
        record: MCPServerConfiguration,
        tools: list[dict[str, Any]],
    ) -> None:
        now = datetime.now(timezone.utc)
        record.enabled = True
        record.tool_schema_hash = hashlib.sha256(
            json.dumps(tools, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        record.last_verified_at = now
        record.last_connected_at = now
        record.disabled_at = None

    def _config_from_record(self, record: MCPServerConfiguration) -> dict[str, Any]:
        return {
            "transport": record.transport,
            "runtime_kind": record.runtime_kind,
            "command": record.command,
            "url": record.url,
            "args": record.args,
            "env_secret_refs": record.env_secret_refs,
            "credential_connection_refs": record.credential_connection_refs,
            "egress_policy": record.egress_policy,
            "stdio_runtime_image_ref": record.stdio_runtime_image_ref,
            "stdio_command_provenance": record.stdio_command_provenance,
            "stdio_package_digest": record.stdio_package_digest,
            "stdio_filesystem_policy": record.stdio_filesystem_policy,
            "stdio_network_policy": record.stdio_network_policy,
            "stdio_resource_limits": record.stdio_resource_limits,
            "stdio_max_session_seconds": record.stdio_max_session_seconds,
            "stdio_max_output_bytes": record.stdio_max_output_bytes,
            "stdio_restart_policy": record.stdio_restart_policy,
            "risk_level": record.risk_level,
        }


# Global singleton
mcp_manager = MCPManager()
