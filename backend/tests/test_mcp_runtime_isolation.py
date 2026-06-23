"""Isolated stdio MCP runtime policy and compose evidence."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
from types import SimpleNamespace
import uuid

import httpx
import pytest
import yaml
from sqlalchemy import select, text, update

from app.core.tools.mcp.manager import MCPManager, mcp_manager
from app.core.tools.mcp.client import MCPToolClient
from app.core.tools.mcp_runtime import (
    IsolatedMCPRuntimeSupervisor,
    MCPRuntimePolicyError,
    approved_payload_hash,
    validate_stdio_runtime_policy,
)
from app.models.acquisition import MCPServerConfiguration
from app.models.user import User
from app.services.auth_service import create_access_token, decode_token, hash_password


ROOT = Path("/repo")
if not ROOT.exists():
    ROOT = Path(__file__).resolve().parents[2]


def approved_stdio_config(**overrides):
    config = {
        "transport": "stdio",
        "runtime_kind": "isolated_stdio",
        "command": "python",
        "args": ["/runtime/echo_mcp_server.py"],
        "env_secret_refs": [],
        "egress_policy": {},
        "stdio_runtime_image_ref": "chainless-mcp-runtime:w4-1-quality",
        "stdio_command_provenance": {
            "source": "activation_target",
            "approved_by": "admin",
            "approved_at": "2026-06-22T00:00:00Z",
        },
        "stdio_package_digest": "sha256:" + "a" * 64,
        "stdio_filesystem_policy": {
            "allow_docker_socket": False,
            "allow_backend_fs": False,
            "allow_host_fs": False,
            "mounts": [],
        },
        "stdio_network_policy": {
            "mode": "none",
            "allowed_hosts": [],
            "deny_private_networks": True,
        },
        "stdio_resource_limits": {
            "memory_mb": 256,
            "cpus": 0.5,
            "pids": 64,
            "timeout_seconds": 30,
        },
        "stdio_max_session_seconds": 30,
        "stdio_max_output_bytes": 65536,
        "stdio_restart_policy": {"max_restarts": 1},
    }
    config.update(overrides)
    return config


def _mcp_record(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    config: dict,
    enabled: bool = True,
) -> MCPServerConfiguration:
    return MCPServerConfiguration(
        tenant_id=uuid.UUID(tenant_id),
        user_id=uuid.UUID(user_id),
        name=name,
        transport=config.get("transport", "stdio"),
        runtime_kind=config.get("runtime_kind", "isolated_stdio"),
        command=config.get("command"),
        url=config.get("url"),
        args=config.get("args", []),
        env_secret_refs=config.get("env_secret_refs", []),
        credential_connection_refs=[],
        egress_policy=config.get("egress_policy", {}),
        stdio_runtime_image_ref=config.get("stdio_runtime_image_ref"),
        stdio_command_provenance=config.get("stdio_command_provenance", {}),
        stdio_package_digest=config.get("stdio_package_digest"),
        stdio_filesystem_policy=config.get("stdio_filesystem_policy", {}),
        stdio_network_policy=config.get("stdio_network_policy", {}),
        stdio_resource_limits=config.get("stdio_resource_limits", {}),
        stdio_max_session_seconds=config.get("stdio_max_session_seconds"),
        stdio_max_output_bytes=config.get("stdio_max_output_bytes"),
        stdio_restart_policy=config.get("stdio_restart_policy", {}),
        enabled=enabled,
        risk_level=config.get("risk_level", "risky"),
    )


def _compose_services() -> tuple[dict, dict]:
    production = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    test = yaml.safe_load((ROOT / "docker-compose.test.yml").read_text(encoding="utf-8"))
    return production["services"], test["services"]


def _load_migration_0013():
    migration_path = ROOT / "backend" / "alembic" / "versions" / "0013_tenant_scoped_mcp_config_identity.py"
    spec = importlib.util.spec_from_file_location("migration_0013", migration_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_stdio_mcp_requires_isolated_runtime_kind() -> None:
    with pytest.raises(MCPRuntimePolicyError, match="isolated_stdio"):
        validate_stdio_runtime_policy(
            "bad",
            approved_stdio_config(runtime_kind="local_stdio"),
        )


@pytest.mark.asyncio
async def test_backend_mcp_client_does_not_launch_stdio_process() -> None:
    client = MCPToolClient("safe", **approved_stdio_config())

    await client.connect()
    try:
        assert client.get_tool_definitions()[0]["function"]["name"] == "mcp__safe__echo"
        assert client._runtime_client is not None
        assert not hasattr(client, "_stdio_ctx")
        assert not hasattr(client, "_session")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_stdio_runtime_executes_real_command_inside_runtime_image() -> None:
    client = MCPToolClient("real", **approved_stdio_config())
    await client.connect()
    try:
        names = [tool["function"]["name"] for tool in client.get_tool_definitions()]
        assert "mcp__real__echo" in names
        result = await client.call_tool("mcp__real__echo", {"text": "from-runtime"})
        assert result == '["from-runtime"]'
    finally:
        await client.disconnect()


def test_stdio_runtime_requires_command_provenance_and_package_digest() -> None:
    with pytest.raises(MCPRuntimePolicyError, match="stdio_command_provenance"):
        validate_stdio_runtime_policy(
            "missing-provenance",
            approved_stdio_config(stdio_command_provenance={}),
        )
    with pytest.raises(MCPRuntimePolicyError, match="stdio_package_digest"):
        validate_stdio_runtime_policy(
            "missing-digest",
            approved_stdio_config(stdio_package_digest=None),
        )
    with pytest.raises(MCPRuntimePolicyError, match="sha digest"):
        validate_stdio_runtime_policy(
            "unpinned-digest",
            approved_stdio_config(stdio_package_digest="latest"),
        )
    with pytest.raises(MCPRuntimePolicyError, match="env_secret_refs"):
        validate_stdio_runtime_policy(
            "env-ref",
            approved_stdio_config(env_secret_refs=[{"name": "TOKEN", "secret_ref": "secret:token"}]),
        )


def test_stdio_runtime_uses_dedicated_image_with_healthcheck() -> None:
    services, test_services = _compose_services()
    service = services["mcp-runtime"]

    assert service["build"]["context"] == "./mcp-runtime"
    assert service["image"] == "chainless-mcp-runtime:w4-1-quality"
    assert "healthcheck" in service
    assert "MCP_RUNTIME_KIND" in service["environment"]
    assert service["environment"]["MCP_RUNTIME_APPROVED_PAYLOAD_HASHES"] != "*"
    assert test_services["mcp-runtime"]["container_name"] == "chainless-mcp-runtime-test"
    assert "mcp_runtime" in service["networks"]

    dockerfile = (ROOT / "mcp-runtime" / "Dockerfile").read_text(encoding="utf-8")
    assert "HEALTHCHECK" in dockerfile
    assert "USER runtime" in dockerfile


def test_stdio_runtime_enforces_resource_limits() -> None:
    services, _ = _compose_services()
    service = services["mcp-runtime"]

    assert service["mem_limit"] == "256m"
    assert service["cpus"] == 0.5
    assert service["pids_limit"] == 64

    with pytest.raises(MCPRuntimePolicyError, match="memory_mb"):
        validate_stdio_runtime_policy(
            "missing-limits",
            approved_stdio_config(stdio_resource_limits={"cpus": 0.5, "pids": 64, "timeout_seconds": 30}),
        )


def test_stdio_runtime_cannot_access_docker_socket_backend_fs_host_fs_unapproved_mounts_or_non_allowlisted_network() -> None:
    services, _ = _compose_services()
    service = services["mcp-runtime"]

    assert service["networks"] == ["mcp_runtime"]
    assert "mcp_runtime" in services["backend"]["networks"]
    assert "egress" not in service["networks"]
    assert "public" not in service["networks"]
    assert "data" not in service["networks"]
    assert "sandbox_net" not in service["networks"]
    assert "volumes" not in service
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]

    with pytest.raises(MCPRuntimePolicyError, match="docker socket"):
        validate_stdio_runtime_policy(
            "docker-sock",
            approved_stdio_config(
                stdio_filesystem_policy={
                    "allow_docker_socket": True,
                    "allow_backend_fs": False,
                    "allow_host_fs": False,
                    "mounts": [],
                }
            ),
        )
    with pytest.raises(MCPRuntimePolicyError, match="approved"):
        validate_stdio_runtime_policy(
            "unapproved-mount",
            approved_stdio_config(
                stdio_filesystem_policy={
                    "allow_docker_socket": False,
                    "allow_backend_fs": False,
                    "allow_host_fs": False,
                    "mounts": [{"source": "named-data", "target": "/data"}],
                }
            ),
        )
    with pytest.raises(MCPRuntimePolicyError, match="allowlist"):
        validate_stdio_runtime_policy(
            "bad-network",
            approved_stdio_config(
                stdio_network_policy={
                    "mode": "allowlist",
                    "allowed_hosts": [],
                    "deny_private_networks": True,
                }
            ),
        )


@pytest.mark.asyncio
async def test_stdio_runtime_cleanup_after_success_failure_timeout_reconnect_backend_restart_and_rollback() -> None:
    policy = validate_stdio_runtime_policy("life", approved_stdio_config())
    supervisor = IsolatedMCPRuntimeSupervisor()

    await supervisor.start(policy)
    await supervisor.cleanup("life", "success")
    await supervisor.start(policy)
    await supervisor.cleanup("life", "failure")
    await supervisor.start(policy)
    await supervisor.cleanup("life", "timeout")
    await supervisor.reconnect(policy)
    await supervisor.recover_after_backend_restart(policy)
    await supervisor.rollback("life")

    evidence = supervisor.evidence("life")
    assert evidence is not None
    assert evidence.active is False
    assert evidence.cleanup_events == [
        "success",
        "failure",
        "timeout",
        "reconnect",
        "backend_restart",
        "rollback",
    ]
    assert evidence.reconnects == 1
    assert evidence.backend_restarts == 1
    assert evidence.rollbacks == 1


@pytest.mark.asyncio
async def test_stdio_runtime_enforces_timeout_and_output_limits() -> None:
    timeout_client = MCPToolClient(
        "timeout",
        **approved_stdio_config(stdio_max_session_seconds=30, stdio_resource_limits={
            "memory_mb": 256,
            "cpus": 0.5,
            "pids": 64,
            "timeout_seconds": 1,
        }),
    )
    await timeout_client.connect()
    try:
        with pytest.raises(Exception):
            await timeout_client.call_tool("mcp__timeout__sleep_echo", {"text": "late", "seconds": 2})
    finally:
        await timeout_client.disconnect()

    output_client = MCPToolClient(
        "output",
        **approved_stdio_config(stdio_max_output_bytes=3000),
    )
    await output_client.connect()
    try:
        with pytest.raises(Exception):
            await output_client.call_tool("mcp__output__big_echo", {"text": "x", "repeat": 50000})
    finally:
        await output_client.disconnect()


@pytest.mark.asyncio
async def test_backend_supervisor_rejects_oversized_runtime_http_response_before_json_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = validate_stdio_runtime_policy(
        "http-cap",
        approved_stdio_config(stdio_max_output_bytes=100),
    )
    supervisor = IsolatedMCPRuntimeSupervisor()

    class HugeResponse:
        headers = {"content-length": "101"}
        content = b"x" * 101

        def raise_for_status(self):
            return None

        def json(self):
            raise AssertionError("json() must not be called before response cap enforcement")

    class HugeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            return HugeResponse()

    monkeypatch.setattr("app.core.tools.mcp_runtime.supervisor.httpx.AsyncClient", HugeClient)

    with pytest.raises(ValueError, match="stdio_max_output_bytes"):
        await supervisor._post(policy, "/discover", {})


@pytest.mark.asyncio
async def test_register_persists_durable_config_and_fresh_manager_recovers_enabled_config(
    client,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()

    server_name = f"durable-{uuid.uuid4().hex}"
    config = approved_stdio_config()
    try:
        registered = await client.post(
            "/api/v1/tools/",
            headers=tenant_a_headers,
            json={"name": server_name, "tool_type": "mcp", "config": config},
        )
        assert registered.status_code == 201, registered.text
        assert registered.json()["tools"][0]["function"]["name"] == f"mcp__{server_name}__echo"

        async with _async_session_factory() as db:
            record = (
                await db.execute(
                    select(MCPServerConfiguration).where(
                        MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                        MCPServerConfiguration.user_id == uuid.UUID(payload["user_id"]),
                        MCPServerConfiguration.name == server_name,
                    )
                )
            ).scalar_one()
            assert record.enabled is True
            assert record.runtime_kind == "isolated_stdio"
            assert record.command == "python"
            assert record.stdio_package_digest == config["stdio_package_digest"]

            fresh_manager = MCPManager()
            result = await fresh_manager.recover_enabled_from_db(db, owner=payload["tenant_id"])
            assert result.recovered >= 1
            result = await fresh_manager.execute(
                f"mcp__{server_name}__echo",
                {"text": "after-restart"},
                owner=payload["tenant_id"],
            )
            assert result == '["after-restart"]'
            await fresh_manager.unregister(server_name, payload["tenant_id"])
    finally:
        async with _async_session_factory() as db:
            await mcp_manager.unregister_durable(
                db,
                server_name,
                tenant_id=payload["tenant_id"],
                user_id=payload["user_id"],
            )


@pytest.mark.asyncio
async def test_tenant_scoped_delete_by_second_admin_disables_original_and_recovery_does_not_resurrect(
    client,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        second_user = User(
            tenant_id=uuid.UUID(payload["tenant_id"]),
            username=f"second-admin-{uuid.uuid4().hex}",
            password_hash=hash_password("secret123"),
            role="admin",
        )
        db.add(second_user)
        await db.commit()
        await db.refresh(second_user)

    second_headers = {
        "Authorization": "Bearer "
        + create_access_token(payload["tenant_id"], str(second_user.id), second_user.username)
    }
    server_name = f"tenant-delete-{uuid.uuid4().hex}"
    try:
        registered = await client.post(
            "/api/v1/tools/",
            headers=tenant_a_headers,
            json={"name": server_name, "tool_type": "mcp", "config": approved_stdio_config()},
        )
        assert registered.status_code == 201, registered.text

        deleted = await client.delete(f"/api/v1/tools/{server_name}", headers=second_headers)
        assert deleted.status_code == 204, deleted.text

        async with _async_session_factory() as db:
            records = (
                await db.execute(
                    select(MCPServerConfiguration).where(
                        MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                        MCPServerConfiguration.name == server_name,
                    )
                )
            ).scalars().all()
            assert len(records) == 1
            assert records[0].user_id == uuid.UUID(payload["user_id"])
            assert records[0].enabled is False

            fresh_manager = MCPManager()
            result = await fresh_manager.recover_enabled_from_db(db, owner=payload["tenant_id"])
            assert result.recovered == 0
            assert fresh_manager.get_all_tools(payload["tenant_id"]) == []
    finally:
        async with _async_session_factory() as db:
            await mcp_manager.unregister_durable(
                db,
                server_name,
                tenant_id=payload["tenant_id"],
                user_id=payload["user_id"],
            )


@pytest.mark.asyncio
async def test_duplicate_tenant_name_registration_upserts_instead_of_duplicating(
    client,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()

    server_name = f"tenant-upsert-{uuid.uuid4().hex}"
    try:
        for _ in range(2):
            registered = await client.post(
                "/api/v1/tools/",
                headers=tenant_a_headers,
                json={"name": server_name, "tool_type": "mcp", "config": approved_stdio_config()},
            )
            assert registered.status_code == 201, registered.text

        async with _async_session_factory() as db:
            records = (
                await db.execute(
                    select(MCPServerConfiguration).where(
                        MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                        MCPServerConfiguration.name == server_name,
                    )
                )
            ).scalars().all()
            assert len(records) == 1
            assert records[0].enabled is True
    finally:
        async with _async_session_factory() as db:
            await mcp_manager.unregister_durable(
                db,
                server_name,
                tenant_id=payload["tenant_id"],
                user_id=payload["user_id"],
            )


@pytest.mark.asyncio
async def test_migration_0013_deduplicates_enabled_tenant_name_before_unique_index(
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    migration = _load_migration_0013()
    index_name = migration.MCP_TENANT_NAME_ENABLED_INDEX
    server_name = f"migration-dedupe-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    older = _mcp_record(
        tenant_id=payload["tenant_id"],
        user_id=payload["user_id"],
        name=server_name,
        config=approved_stdio_config(),
        enabled=True,
    )
    newer = _mcp_record(
        tenant_id=payload["tenant_id"],
        user_id=payload["user_id"],
        name=server_name,
        config=approved_stdio_config(stdio_package_digest="sha256:" + "b" * 64),
        enabled=True,
    )
    older.created_at = now - timedelta(days=2)
    older.updated_at = now - timedelta(days=2)
    newer.created_at = now - timedelta(days=1)
    newer.updated_at = now

    async with _async_session_factory() as db:
        await db.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        await db.commit()
        db.add_all([older, newer])
        await db.commit()
        try:
            await db.run_sync(
                lambda sync_session: migration._dedupe_enabled_mcp_configurations(
                    sync_session.connection()
                )
            )
            await db.execute(
                text(
                    f"CREATE UNIQUE INDEX {index_name} "
                    "ON mcp_server_configurations (tenant_id, name) WHERE enabled"
                )
            )
            await db.commit()
            db.expire_all()

            records = (
                await db.execute(
                    select(MCPServerConfiguration).where(
                        MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                        MCPServerConfiguration.name == server_name,
                    )
                )
            ).scalars().all()
            enabled = [record for record in records if record.enabled]
            disabled = [record for record in records if not record.enabled]
            assert len(enabled) == 1
            assert enabled[0].id == newer.id
            assert len(disabled) == 1
            assert disabled[0].disabled_at is not None
        finally:
            await db.execute(
                text(
                    "DELETE FROM mcp_server_configurations "
                    "WHERE tenant_id = :tenant_id AND name = :name"
                ),
                {"tenant_id": uuid.UUID(payload["tenant_id"]), "name": server_name},
            )
            await db.run_sync(
                lambda sync_session: migration._dedupe_enabled_mcp_configurations(
                    sync_session.connection()
                )
            )
            await db.execute(
                text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
                    "ON mcp_server_configurations (tenant_id, name) WHERE enabled"
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_remote_mcp_durable_registration_fails_closed_without_safe_transport_owner(
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    server_name = f"remote-fail-closed-{uuid.uuid4().hex}"
    manager = MCPManager()
    config = {
        "transport": "http",
        "runtime_kind": "remote_http",
        "url": "http://mcp.local",
        "egress_policy": {"allow_hosts": ["mcp.local"], "max_response_bytes": 10000},
    }
    async with _async_session_factory() as db:
        with pytest.raises(ValueError, match="SAFE_REMOTE_TRANSPORT_REQUIRED"):
            await manager.register_durable(
                db,
                server_name,
                config,
                tenant_id=payload["tenant_id"],
                user_id=payload["user_id"],
            )
        assert manager.get_all_tools(payload["tenant_id"]) == []
        record = (
            await db.execute(
                select(MCPServerConfiguration).where(
                    MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                    MCPServerConfiguration.name == server_name,
                )
            )
        ).scalar_one()
        assert record.transport == "http"
        assert record.enabled is False

        await db.delete(record)
        await db.commit()


@pytest.mark.asyncio
async def test_failed_durable_replacement_preserves_existing_runtime_and_record(
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    manager = MCPManager()
    server_name = f"replace-fail-{uuid.uuid4().hex}"
    old_config = approved_stdio_config()
    bad_config = approved_stdio_config(
        command="missing-runtime-command",
        stdio_package_digest="sha256:" + "b" * 64,
    )

    async with _async_session_factory() as db:
        await manager.register_durable(
            db,
            server_name,
            old_config,
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
        )
        old_result = await manager.execute(
            f"mcp__{server_name}__echo",
            {"text": "old-runtime"},
            owner=payload["tenant_id"],
        )
        assert old_result == '["old-runtime"]'
        old_record = (
            await db.execute(
                select(MCPServerConfiguration).where(
                    MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                    MCPServerConfiguration.name == server_name,
                )
            )
        ).scalar_one()
        old_hash = old_record.tool_schema_hash

        with pytest.raises(Exception):
            await manager.register_durable(
                db,
                server_name,
                bad_config,
                tenant_id=payload["tenant_id"],
                user_id=payload["user_id"],
            )

        still_result = await manager.execute(
            f"mcp__{server_name}__echo",
            {"text": "still-old"},
            owner=payload["tenant_id"],
        )
        assert still_result == '["still-old"]'
        db.expire_all()
        record = (
            await db.execute(
                select(MCPServerConfiguration).where(
                    MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                    MCPServerConfiguration.name == server_name,
                )
            )
        ).scalar_one()
        assert record.enabled is True
        assert record.command == old_config["command"]
        assert record.args == old_config["args"]
        assert record.stdio_package_digest == old_config["stdio_package_digest"]
        assert record.tool_schema_hash == old_hash

        await manager.unregister_durable(
            db,
            server_name,
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
        )


@pytest.mark.asyncio
async def test_successful_durable_replacement_updates_record_and_swaps_runtime(
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    manager = MCPManager()
    server_name = f"replace-success-{uuid.uuid4().hex}"
    old_config = approved_stdio_config(stdio_package_digest="sha256:" + "a" * 64)
    new_config = approved_stdio_config(
        risk_level="high_risk",
        egress_policy={"metadata": "replacement"},
    )

    async with _async_session_factory() as db:
        await manager.register_durable(
            db,
            server_name,
            old_config,
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
        )
        old_client = manager.get_client_for_tool(f"mcp__{server_name}__echo", payload["tenant_id"])

        await manager.register_durable(
            db,
            server_name,
            new_config,
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
        )
        new_client = manager.get_client_for_tool(f"mcp__{server_name}__echo", payload["tenant_id"])
        assert new_client is not None
        assert new_client is not old_client
        assert await manager.execute(
            f"mcp__{server_name}__echo",
            {"text": "new-runtime"},
            owner=payload["tenant_id"],
        ) == '["new-runtime"]'

        db.expire_all()
        records = (
            await db.execute(
                select(MCPServerConfiguration).where(
                    MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                    MCPServerConfiguration.name == server_name,
                )
            )
        ).scalars().all()
        assert len(records) == 1
        assert records[0].enabled is True
        assert records[0].stdio_package_digest == old_config["stdio_package_digest"]
        assert records[0].risk_level == "high_risk"
        assert records[0].egress_policy == {"metadata": "replacement"}

        await manager.unregister_durable(
            db,
            server_name,
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
        )


@pytest.mark.asyncio
async def test_concurrent_durable_replacements_serialize_db_and_runtime_install(
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    manager = MCPManager()
    server_name = f"replace-concurrent-{uuid.uuid4().hex}"
    active_connects = 0
    max_connects = 0

    class FakeConnectedClient:
        def __init__(self, name: str, marker: str) -> None:
            self.name = name
            self.marker = marker
            self.disconnected = False

        def get_tool_definitions(self) -> list[dict]:
            return [
                {
                    "type": "function",
                    "risk": "risky",
                    "function": {
                        "name": f"mcp__{self.name}__echo",
                        "description": f"fake client {self.marker}",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]

        async def call_tool(self, tool_name: str, args: dict) -> str:
            return json.dumps([self.marker])

        async def disconnect(self) -> None:
            self.disconnected = True

        def is_idle_expired(self) -> bool:
            return False

        async def recover_after_backend_restart(self) -> None:
            return None

        async def rollback(self) -> None:
            self.disconnected = True

    async def fake_connect(name: str, config: dict, owner: str | None = None):
        nonlocal active_connects, max_connects
        marker = config.get("egress_policy", {}).get("candidate", "unknown")
        active_connects += 1
        max_connects = max(max_connects, active_connects)
        try:
            await asyncio.sleep(0.05)
            return FakeConnectedClient(name, marker)
        finally:
            active_connects -= 1

    def candidate_config(marker: str) -> dict:
        return approved_stdio_config(egress_policy={"candidate": marker})

    monkeypatch.setattr(manager, "_connect_client", fake_connect)
    try:
        async with _async_session_factory() as db:
            await manager.register_durable(
                db,
                server_name,
                candidate_config("old"),
                tenant_id=payload["tenant_id"],
                user_id=payload["user_id"],
            )

        async def replace(marker: str) -> None:
            async with _async_session_factory() as db:
                await manager.register_durable(
                    db,
                    server_name,
                    candidate_config(marker),
                    tenant_id=payload["tenant_id"],
                    user_id=payload["user_id"],
                )

        await asyncio.gather(replace("A"), replace("B"))

        async with _async_session_factory() as db:
            records = (
                await db.execute(
                    select(MCPServerConfiguration).where(
                        MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                        MCPServerConfiguration.name == server_name,
                    )
                )
            ).scalars().all()
            enabled = [record for record in records if record.enabled]
            assert len(enabled) == 1
            db_candidate = enabled[0].egress_policy["candidate"]

        registry_key = manager._registry_key(server_name, payload["tenant_id"])
        runtime_candidate = manager._configs[registry_key]["egress_policy"]["candidate"]
        result = json.loads(
            await manager.execute(
                f"mcp__{server_name}__echo",
                {},
                owner=payload["tenant_id"],
            )
        )
        assert db_candidate in {"A", "B"}
        assert runtime_candidate == db_candidate
        assert result == [db_candidate]
        assert max_connects == 1
        assert manager._registry_locks == {}
    finally:
        async with _async_session_factory() as db:
            await manager.unregister_durable(
                db,
                server_name,
                tenant_id=payload["tenant_id"],
                user_id=payload["user_id"],
            )


@pytest.mark.asyncio
async def test_api_failed_mcp_replacement_preserves_existing_runtime_and_durable_record(
    client,
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User).where(User.id == uuid.UUID(payload["user_id"])).values(role="admin")
        )
        await db.commit()

    server_name = f"api-replace-fail-{uuid.uuid4().hex}"
    old_config = approved_stdio_config()
    bad_config = approved_stdio_config(
        command="missing-runtime-command",
        stdio_package_digest="sha256:" + "b" * 64,
    )
    try:
        registered = await client.post(
            "/api/v1/tools/",
            headers=tenant_a_headers,
            json={"name": server_name, "tool_type": "mcp", "config": old_config},
        )
        assert registered.status_code == 201, registered.text

        async with _async_session_factory() as db:
            old_record = (
                await db.execute(
                    select(MCPServerConfiguration).where(
                        MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                        MCPServerConfiguration.name == server_name,
                    )
                )
            ).scalar_one()
            old_hash = old_record.tool_schema_hash

        failed = await client.post(
            "/api/v1/tools/",
            headers=tenant_a_headers,
            json={"name": server_name, "tool_type": "mcp", "config": bad_config},
        )
        assert failed.status_code == 502, failed.text
        assert await mcp_manager.execute(
            f"mcp__{server_name}__echo",
            {"text": "api-old"},
            owner=payload["tenant_id"],
        ) == '["api-old"]'

        async with _async_session_factory() as db:
            record = (
                await db.execute(
                    select(MCPServerConfiguration).where(
                        MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                        MCPServerConfiguration.name == server_name,
                    )
                )
            ).scalar_one()
            assert record.enabled is True
            assert record.command == old_config["command"]
            assert record.stdio_package_digest == old_config["stdio_package_digest"]
            assert record.tool_schema_hash == old_hash
    finally:
        async with _async_session_factory() as db:
            await mcp_manager.unregister_durable(
                db,
                server_name,
                tenant_id=payload["tenant_id"],
                user_id=payload["user_id"],
            )


@pytest.mark.asyncio
async def test_register_durable_commit_and_runtime_failures_do_not_leave_ghost_active_client(
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    tenant_id = payload["tenant_id"]
    user_id = payload["user_id"]

    async with _async_session_factory() as db:
        manager = MCPManager()

        async def fail_commit():
            raise RuntimeError("commit failed before runtime")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="commit failed before runtime"):
            await manager.register_durable(
                db,
                f"commit-fail-{uuid.uuid4().hex}",
                approved_stdio_config(),
                tenant_id=tenant_id,
                user_id=user_id,
            )
        assert manager.get_all_tools(tenant_id) == []
        await db.rollback()

    async with _async_session_factory() as db:
        manager = MCPManager()

        async def fail_connect(name, config, owner=None):
            raise RuntimeError("runtime failed after durable write")

        monkeypatch.setattr(manager, "_connect_client", fail_connect)
        server_name = f"runtime-fail-{uuid.uuid4().hex}"
        with pytest.raises(RuntimeError, match="runtime failed after durable write"):
            await manager.register_durable(
                db,
                server_name,
                approved_stdio_config(),
                tenant_id=tenant_id,
                user_id=user_id,
            )
        records = (
            await db.execute(
                select(MCPServerConfiguration).where(
                    MCPServerConfiguration.tenant_id == uuid.UUID(tenant_id),
                    MCPServerConfiguration.name == server_name,
                )
            )
        ).scalars().all()
        assert len(records) == 1
        assert records[0].enabled is False
        assert manager.get_all_tools(tenant_id) == []

    server_name = f"final-commit-fail-{uuid.uuid4().hex}"
    async with _async_session_factory() as db:
        manager = MCPManager()
        original_commit = db.commit
        calls = 0

        async def fail_second_commit():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("final durable enable failed")
            await original_commit()

        monkeypatch.setattr(db, "commit", fail_second_commit)
        with pytest.raises(RuntimeError, match="final durable enable failed"):
            await manager.register_durable(
                db,
                server_name,
                approved_stdio_config(),
                tenant_id=tenant_id,
                user_id=user_id,
            )
        assert manager.get_client_for_tool(f"mcp__{server_name}__echo", tenant_id) is None

    async with _async_session_factory() as db:
        record = (
            await db.execute(
                select(MCPServerConfiguration).where(
                    MCPServerConfiguration.tenant_id == uuid.UUID(tenant_id),
                    MCPServerConfiguration.name == server_name,
                )
            )
        ).scalar_one()
        assert record.enabled is False


@pytest.mark.asyncio
async def test_unregister_durable_commit_failure_keeps_runtime_visible_and_db_enabled(
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    server_name = f"unregister-commit-fail-{uuid.uuid4().hex}"
    manager = MCPManager()
    async with _async_session_factory() as db:
        await manager.register_durable(
            db,
            server_name,
            approved_stdio_config(),
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
        )

    async with _async_session_factory() as db:
        async def fail_commit():
            raise RuntimeError("disable commit failed")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="disable commit failed"):
            await manager.unregister_durable(
                db,
                server_name,
                tenant_id=payload["tenant_id"],
                user_id=payload["user_id"],
            )
        assert manager.get_client_for_tool(f"mcp__{server_name}__echo", payload["tenant_id"]) is not None
        await db.rollback()

    async with _async_session_factory() as db:
        record = (
            await db.execute(
                select(MCPServerConfiguration).where(
                    MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                    MCPServerConfiguration.name == server_name,
                )
            )
        ).scalar_one()
        assert record.enabled is True
        await manager.unregister_durable(
            db,
            server_name,
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
        )


@pytest.mark.asyncio
async def test_startup_recovery_isolates_bad_records_and_recovers_valid_records(
    tenant_a_headers: dict[str, str],
) -> None:
    from app.api.deps import _async_session_factory

    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    good_name = f"recovery-good-{uuid.uuid4().hex}"
    bad_name = f"recovery-bad-{uuid.uuid4().hex}"
    async with _async_session_factory() as db:
        db.add(_mcp_record(
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
            name=bad_name,
            config=approved_stdio_config(command="missing-runtime-command"),
        ))
        db.add(_mcp_record(
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
            name=good_name,
            config=approved_stdio_config(),
        ))
        await db.commit()

        manager = MCPManager()
        result = await manager.recover_enabled_from_db(db, owner=payload["tenant_id"])
        assert result.recovered == 1
        assert result.failed == 1
        assert result.failures[0]["name"] == bad_name
        assert manager.get_client_for_tool(f"mcp__{good_name}__echo", payload["tenant_id"]) is not None
        assert manager.get_client_for_tool(f"mcp__{bad_name}__echo", payload["tenant_id"]) is None
        await manager.unregister(good_name, payload["tenant_id"])

        for name in (good_name, bad_name):
            record = (
                await db.execute(
                    select(MCPServerConfiguration).where(
                        MCPServerConfiguration.tenant_id == uuid.UUID(payload["tenant_id"]),
                        MCPServerConfiguration.name == name,
                    )
                )
            ).scalar_one()
            record.enabled = False
        await db.commit()


@pytest.mark.asyncio
async def test_startup_helper_invokes_durable_mcp_recovery(monkeypatch) -> None:
    import app.main as main

    calls: list[str] = []

    class FakeSession:
        async def __aenter__(self):
            return "db-session"

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeFactory:
        def __call__(self):
            return FakeSession()

    async def fake_recover(db):
        calls.append(db)
        return SimpleNamespace(recovered=7, failed=0, failures=[])

    monkeypatch.setattr("app.api.deps._async_session_factory", FakeFactory())
    monkeypatch.setattr("app.core.tools.mcp.manager.mcp_manager.recover_enabled_from_db", fake_recover)

    await main.recover_mcp_servers_on_startup()

    assert calls == ["db-session"]


@pytest.mark.asyncio
async def test_runtime_service_rejects_unapproved_payload_server_side() -> None:
    runtime_url = os.environ.get("MCP_RUNTIME_URL", "http://mcp-runtime:9101").rstrip("/")
    payload = {
        "server_name": "bad-runtime-payload",
        "command": "python",
        "args": ["/runtime/echo_mcp_server.py"],
        "max_session_seconds": 30,
        "max_output_bytes": 65536,
        "env": {},
        "env_secret_refs": [],
        "filesystem_policy": {
            "allow_docker_socket": False,
            "allow_backend_fs": False,
            "allow_host_fs": False,
            "mounts": [],
        },
        "network_policy": {"mode": "none", "allowed_hosts": [], "deny_private_networks": True},
        "resource_limits": {"memory_mb": 256, "cpus": 0.5, "pids": 64, "timeout_seconds": 30},
        "restart_policy": {"max_restarts": 1},
        "image_ref": "unapproved-image:latest",
        "package_digest": "sha256:" + "a" * 64,
        "command_provenance": {
            "source": "activation_target",
            "approved_by": "admin",
            "approved_at": "2026-06-22T00:00:00Z",
        },
    }
    valid_hash = approved_payload_hash(
        command=payload["command"],
        args=payload["args"],
        image_ref="chainless-mcp-runtime:w4-1-quality",
        package_digest=payload["package_digest"],
        command_provenance=payload["command_provenance"],
        env_secret_refs=payload["env_secret_refs"],
        filesystem_policy=payload["filesystem_policy"],
        network_policy=payload["network_policy"],
        resource_limits=payload["resource_limits"],
        max_session_seconds=payload["max_session_seconds"],
        max_output_bytes=payload["max_output_bytes"],
        restart_policy=payload["restart_policy"],
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        valid = await client.post(
            f"{runtime_url}/discover",
            json={**payload, "image_ref": "chainless-mcp-runtime:w4-1-quality", "approved_payload_hash": valid_hash},
        )
        assert valid.status_code == 200, valid.text

        missing_hash = await client.post(
            f"{runtime_url}/discover",
            json={**payload, "image_ref": "chainless-mcp-runtime:w4-1-quality"},
        )
        assert missing_hash.status_code == 403

        wrong_hash = await client.post(
            f"{runtime_url}/discover",
            json={**payload, "image_ref": "chainless-mcp-runtime:w4-1-quality", "approved_payload_hash": "sha256:" + "0" * 64},
        )
        assert wrong_hash.status_code == 403

        changed_command = await client.post(
            f"{runtime_url}/discover",
            json={
                **payload,
                "image_ref": "chainless-mcp-runtime:w4-1-quality",
                "command": "python3",
                "approved_payload_hash": valid_hash,
            },
        )
        assert changed_command.status_code == 403

        changed_digest = await client.post(
            f"{runtime_url}/discover",
            json={
                **payload,
                "image_ref": "chainless-mcp-runtime:w4-1-quality",
                "package_digest": "sha256:" + "b" * 64,
                "approved_payload_hash": valid_hash,
            },
        )
        assert changed_digest.status_code == 403

        changed_policy = await client.post(
            f"{runtime_url}/discover",
            json={
                **payload,
                "image_ref": "chainless-mcp-runtime:w4-1-quality",
                "filesystem_policy": {
                    "allow_docker_socket": False,
                    "allow_backend_fs": False,
                    "allow_host_fs": False,
                    "mounts": [{"source": "named-data", "target": "/data", "approved": True}],
                },
                "approved_payload_hash": valid_hash,
            },
        )
        assert changed_policy.status_code == 403

        raw_env_payload = {
            **payload,
            "image_ref": "chainless-mcp-runtime:w4-1-quality",
            "env": {"TOKEN": "raw-secret"},
            "approved_payload_hash": valid_hash,
        }
        raw_env = await client.post(f"{runtime_url}/discover", json=raw_env_payload)
        assert raw_env.status_code == 400

        bad_network_payload = {
            **payload,
            "image_ref": "chainless-mcp-runtime:w4-1-quality",
            "network_policy": {"mode": "allowlist", "allowed_hosts": ["example.com"], "deny_private_networks": True},
            "approved_payload_hash": valid_hash,
        }
        bad_network = await client.post(f"{runtime_url}/discover", json=bad_network_payload)
        assert bad_network.status_code == 403
