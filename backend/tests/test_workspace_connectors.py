"""Workspace Connector owner and mount-bundle contract tests."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.agent.code_executor import CODE_AS_ACTION_TOOL, execute_code_as_action, stream_code_as_action
from app.core.agent.engine import run_agent
from app.core.sandbox.manager import SandboxManager
from app.core.secrets import decrypt_secret
from app.core.tools.builtin import file_ops
import app.core.workspace_connectors.mounts as mount_module
from app.core.workspace_connectors.mounts import (
    TrustedWorkspaceConnectorMountSource,
    WorkspaceConnectorMount,
    WorkspaceConnectorMountBundle,
    WorkspaceConnectorMountError,
    agent_context_for_mount_bundle,
    build_workspace_connector_runtime_context,
    build_sandbox_mount_payload,
    materialize_workspace_connector_source,
    resolve_mount_bundle,
    resolve_trusted_mount_sources,
)
from app.core.workspace_connectors.service import (
    WorkspaceConnectorApprovalRequired,
    _host_realpath_hash,
    create_workspace_connector,
    revoke_workspace_connector,
)
from app.models.acquisition import WorkspaceConnector
from app.models.audit_log import AuditLog
from app.models.conversation import Conversation, Message
from app.models.tenant import Tenant
from app.models.tool_confirmation import ToolConfirmation
from app.services.auth_service import decode_token
from app.services.conversation_stream_service import (
    WORKSPACE_CONNECTOR_CONTEXT_ARG,
    execute_confirmed_tool,
    persist_confirmation_required,
)

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


async def _same_tenant_user_headers(client: AsyncClient, tenant_id: uuid.UUID) -> dict[str, str]:
    async with _async_session_factory() as db:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    suffix = uuid.uuid4().hex
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": tenant.name,
            "username": f"user-{suffix}",
            "password": "secret123",
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _confirmation(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    host_path: str | Path | None = None,
    mode: str = "read_only",
    tool_name: str = "workspace_connector.create",
    purpose: str = "workspace_connector",
    status: str = "approved",
) -> ToolConfirmation:
    args = {"purpose": purpose, "mode": mode}
    if host_path is not None:
        args["host_realpath_hash"] = _host_realpath_hash(host_path)
    async with _async_session_factory() as db:
        conversation = Conversation(tenant_id=tenant_id, user_id=user_id, title="workspace approval owner")
        db.add(conversation)
        await db.flush()
        confirmation = ToolConfirmation(
            conversation_id=conversation.id,
            tool_call_id=f"workspace-approval-{uuid.uuid4().hex}",
            tool_name=tool_name,
            args=args,
            status=status,
        )
        db.add(confirmation)
        await db.commit()
        return confirmation


def _load_sandbox_proxy_main():
    root = Path("/repo")
    if not root.exists():
        root = Path(__file__).resolve().parents[2]
    sandbox_proxy_dir = root / "sandbox-proxy"
    os.environ.setdefault("SANDBOX_IMAGE", "chainless-sandbox:test")
    if str(sandbox_proxy_dir) not in sys.path:
        sys.path.insert(0, str(sandbox_proxy_dir))
    spec = importlib.util.spec_from_file_location(
        "sandbox_proxy_main_for_workspace_connector_tests",
        sandbox_proxy_dir / "main.py",
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _synthetic_mount_context(
    connector_id: str,
    host_path: Path,
    *,
    mode: str = "read_only",
) -> tuple[WorkspaceConnectorMountBundle, list[TrustedWorkspaceConnectorMountSource], dict]:
    bundle = WorkspaceConnectorMountBundle(
        schema_version="workspace_connector_mounts.v1",
        mounts=[
            WorkspaceConnectorMount(
                connector_id=connector_id,
                generation=1,
                container_mount_path=f"/workspace/connectors/{connector_id}",
                backend_mount_path=f"/workspace/connectors/{connector_id}",
                sandbox_mount_path=f"/workspace/connectors/{connector_id}",
                mode=mode,
            )
        ],
    )
    sources = [
        TrustedWorkspaceConnectorMountSource(
            connector_id=connector_id,
            generation=1,
            host_path=str(host_path),
            mode=mode,
        )
    ]
    return bundle, sources, {
        "workspace_connector_mount_bundle": bundle,
        "workspace_connector_trusted_sources": sources,
    }


def _mount_for_target(
    connector_id: str,
    target_path: Path,
    *,
    generation: int = 1,
    mode: str = "read_only",
) -> WorkspaceConnectorMount:
    return WorkspaceConnectorMount(
        connector_id=connector_id,
        generation=generation,
        container_mount_path=f"/workspace/connectors/{connector_id}",
        backend_mount_path=str(target_path),
        sandbox_mount_path=f"/workspace/connectors/{connector_id}",
        mode=mode,
    )


async def test_workspace_connector_requires_user_approval(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    async with _async_session_factory() as db:
        with pytest.raises(WorkspaceConnectorApprovalRequired, match="approval"):
            await create_workspace_connector(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                name="Unapproved docs",
                host_path=tmp_path / "docs",
                mode="read_only",
                approval_id=None,
            )

        rows = (
            await db.execute(
                select(WorkspaceConnector).where(
                    WorkspaceConnector.tenant_id == tenant_id,
                    WorkspaceConnector.user_id == user_id,
                )
            )
        ).scalars().all()
        assert rows == []


async def test_workspace_connector_rejects_invalid_or_unowned_approvals(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    same_tenant_other_headers = await _same_tenant_user_headers(client, tenant_id)
    same_tenant_other_tenant_id, same_tenant_other_user_id = _identity(same_tenant_other_headers)
    tenant_b_id, tenant_b_user_id = _identity(tenant_b_headers)
    host_path = tmp_path / "docs"
    pending = await _confirmation(tenant_id, user_id, host_path=host_path, status="pending")
    rejected = await _confirmation(tenant_id, user_id, host_path=host_path, status="rejected")
    cross_user = await _confirmation(same_tenant_other_tenant_id, same_tenant_other_user_id, host_path=host_path)
    cross_tenant = await _confirmation(tenant_b_id, tenant_b_user_id, host_path=host_path)

    invalid_approval_ids = [
        uuid.uuid4(),
        pending.id,
        rejected.id,
        cross_user.id,
        cross_tenant.id,
    ]
    for approval_id in invalid_approval_ids:
        async with _async_session_factory() as db:
            with pytest.raises(WorkspaceConnectorApprovalRequired, match="approved confirmation owned"):
                await create_workspace_connector(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    name="Invalid approval docs",
                    host_path=host_path,
                    mode="read_only",
                    approval_id=approval_id,
                )

    async with _async_session_factory() as db:
        rows = (
            await db.execute(
                select(WorkspaceConnector).where(
                    WorkspaceConnector.tenant_id == tenant_id,
                    WorkspaceConnector.user_id == user_id,
                )
            )
        ).scalars().all()
        assert rows == []


async def test_workspace_connector_rejects_unrelated_approval(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "docs"
    unrelated = await _confirmation(
        tenant_id,
        user_id,
        host_path=host_path,
        tool_name="filesystem.delete",
    )
    wrong_purpose = await _confirmation(
        tenant_id,
        user_id,
        host_path=host_path,
        purpose="api_tool",
    )

    for approval_id in (unrelated.id, wrong_purpose.id):
        async with _async_session_factory() as db:
            with pytest.raises(WorkspaceConnectorApprovalRequired, match="workspace_connector"):
                await create_workspace_connector(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    name="Unrelated approval docs",
                    host_path=host_path,
                    mode="read_only",
                    approval_id=approval_id,
                )


async def test_workspace_connector_rejects_wrong_approval_mode(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "docs"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path, mode="read_only")

    async with _async_session_factory() as db:
        with pytest.raises(WorkspaceConnectorApprovalRequired, match="mode"):
            await create_workspace_connector(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                name="Wrong mode docs",
                host_path=host_path,
                mode="read_write",
                approval_id=approval.id,
            )


async def test_workspace_connector_rejects_wrong_approval_host_path(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    approved_host_path = tmp_path / "approved"
    requested_host_path = tmp_path / "requested"
    approval = await _confirmation(tenant_id, user_id, host_path=approved_host_path)

    async with _async_session_factory() as db:
        with pytest.raises(WorkspaceConnectorApprovalRequired, match="host path"):
            await create_workspace_connector(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                name="Wrong path docs",
                host_path=requested_host_path,
                mode="read_only",
                approval_id=approval.id,
            )


async def test_workspace_connector_rejects_reused_approval(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "approved"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)

    async with _async_session_factory() as db:
        await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="First connector",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(WorkspaceConnectorApprovalRequired, match="already been used"):
            await create_workspace_connector(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                name="Replay connector",
                host_path=host_path,
                mode="read_only",
                approval_id=approval.id,
            )


async def test_workspace_connector_sanitizes_allowlist_rule_metadata(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "approved"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)

    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Sanitized connector",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
            allowlist_rule={
                "label": "safe",
                "approval_id": str(uuid.uuid4()),
                "raw_host_path_exposed": True,
                "host_path": str(host_path),
                "host_realpath_hash": "leaky-hash",
                "nested": {
                    "safe_note": "kept",
                    "token": "secret-token",
                    "host_path_secret_ref": "ciphertext",
                },
                "items": [
                    {"name": "kept"},
                    {"password": "hidden", "host_realpath": str(host_path)},
                ],
            },
        )
        await db.commit()

    async with _async_session_factory() as db:
        stored = (
            await db.execute(
                select(WorkspaceConnector).where(WorkspaceConnector.connector_id == connector.connector_id)
            )
        ).scalar_one()

    assert stored.allowlist_rule["approval_id"] == str(approval.id)
    assert stored.allowlist_rule["raw_host_path_exposed"] is False
    assert stored.allowlist_rule["label"] == "safe"
    assert stored.allowlist_rule["nested"] == {"safe_note": "kept"}
    assert stored.allowlist_rule["items"] == [{"name": "kept"}, {}]
    rendered = repr(stored.allowlist_rule).lower()
    assert str(host_path).lower() not in rendered
    assert stored.allowlist_rule["approval_id"] == str(approval.id)
    for forbidden in ("host_realpath", "secret", "token", "password", "leaky-hash"):
        assert forbidden not in rendered


async def test_mount_bundle_contains_connector_id_generation_and_container_paths(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "approved"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Approved workspace",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        bundle = await resolve_mount_bundle(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            connector_ids=[connector.connector_id],
        )

    assert len(bundle.mounts) == 1
    mount = bundle.mounts[0]
    assert mount.connector_id.startswith("wsc_")
    assert mount.generation == 1
    assert mount.mode == "read_only"
    assert mount.container_mount_path == f"/workspace/connectors/{mount.connector_id}"
    assert mount.backend_mount_path == f"/workspace/connectors/{mount.connector_id}"
    assert mount.sandbox_mount_path == f"/workspace/connectors/{mount.connector_id}"
    assert "host" not in repr(bundle).lower()


async def test_trusted_mount_source_resolves_encrypted_host_path_without_public_leaks(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "approved-source"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Approved source",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    expected_host_path = str(host_path.expanduser().resolve(strict=False))
    async with _async_session_factory() as db:
        stored = (
            await db.execute(
                select(WorkspaceConnector).where(WorkspaceConnector.connector_id == connector.connector_id)
            )
        ).scalar_one()
        assert stored.host_path_secret_ref is not None
        assert expected_host_path not in stored.host_path_secret_ref
        assert decrypt_secret(stored.host_path_secret_ref) == expected_host_path

        sources = await resolve_trusted_mount_sources(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            connector_generations={connector.connector_id: connector.mount_generation},
        )
        audits = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "workspace_connector.created",
                    AuditLog.resource_id == str(connector.id),
                )
            )
        ).scalars().all()

    assert len(sources) == 1
    assert sources[0].connector_id == connector.connector_id
    assert sources[0].generation == 1
    assert sources[0].host_path == expected_host_path
    assert sources[0].mode == "read_only"
    audit_text = repr([row.details for row in audits])
    assert expected_host_path not in audit_text
    assert stored.host_path_secret_ref not in audit_text
    assert "host_path_secret_ref" not in audit_text


async def test_materialize_connector_source_directory_copies_and_removes_stale_target(
    tmp_path: Path,
) -> None:
    connector_id = f"wsc_{uuid.uuid4().hex}"
    source_path = tmp_path / "approved-source"
    source_path.mkdir()
    (source_path / "fresh.txt").write_text("fresh connector fact\n", encoding="utf-8")
    nested = source_path / "nested"
    nested.mkdir()
    (nested / "child.txt").write_text("nested fact\n", encoding="utf-8")
    target_path = tmp_path / "mount-target"
    target_path.mkdir()
    (target_path / "stale.txt").write_text("stale fact\n", encoding="utf-8")

    materialized = materialize_workspace_connector_source(
        source=TrustedWorkspaceConnectorMountSource(
            connector_id=connector_id,
            generation=1,
            host_path=str(source_path),
            mode="read_only",
        ),
        mount=_mount_for_target(connector_id, target_path),
    )

    assert materialized.host_path == str(target_path.resolve(strict=False))
    assert (target_path / "fresh.txt").read_text(encoding="utf-8") == "fresh connector fact\n"
    assert (target_path / "nested" / "child.txt").read_text(encoding="utf-8") == "nested fact\n"
    assert not (target_path / "stale.txt").exists()
    assert str(source_path) not in repr(materialized)


async def test_materialize_connector_source_file_exposes_under_target_basename(
    tmp_path: Path,
) -> None:
    connector_id = f"wsc_{uuid.uuid4().hex}"
    source_path = tmp_path / "approved.txt"
    source_path.write_text("approved file fact\n", encoding="utf-8")
    target_path = tmp_path / "file-target"
    target_path.mkdir()
    (target_path / "old.txt").write_text("old fact\n", encoding="utf-8")

    materialized = materialize_workspace_connector_source(
        source=TrustedWorkspaceConnectorMountSource(
            connector_id=connector_id,
            generation=1,
            host_path=str(source_path),
            mode="read_only",
        ),
        mount=_mount_for_target(connector_id, target_path),
    )

    expected_file = target_path / source_path.name
    assert materialized.host_path == str(target_path.resolve(strict=False))
    assert expected_file.read_text(encoding="utf-8") == "approved file fact\n"
    assert not (target_path / "old.txt").exists()
    assert str(source_path) not in repr(materialized)


async def test_materialize_connector_missing_source_error_is_actionable_without_raw_path(
    tmp_path: Path,
) -> None:
    connector_id = f"wsc_{uuid.uuid4().hex}"
    source_path = tmp_path / "missing-source"

    with pytest.raises(WorkspaceConnectorMountError) as exc:
        materialize_workspace_connector_source(
            source=TrustedWorkspaceConnectorMountSource(
                connector_id=connector_id,
                generation=1,
                host_path=str(source_path),
                mode="read_only",
            ),
            mount=_mount_for_target(connector_id, tmp_path / "target"),
        )

    assert exc.value.code == "WORKSPACE_CONNECTOR_SOURCE_UNAVAILABLE"
    assert connector_id in str(exc.value)
    assert "approve it again" in str(exc.value)
    assert str(source_path) not in str(exc.value)


async def test_materialize_connector_rejects_recursive_target_without_raw_path(
    tmp_path: Path,
) -> None:
    connector_id = f"wsc_{uuid.uuid4().hex}"
    source_path = tmp_path / "approved-source"
    source_path.mkdir()
    target_path = source_path / "connectors" / connector_id

    with pytest.raises(WorkspaceConnectorMountError) as exc:
        materialize_workspace_connector_source(
            source=TrustedWorkspaceConnectorMountSource(
                connector_id=connector_id,
                generation=1,
                host_path=str(source_path),
                mode="read_only",
            ),
            mount=_mount_for_target(connector_id, target_path),
        )

    assert exc.value.code == "WORKSPACE_CONNECTOR_RECURSIVE_MATERIALIZATION"
    assert connector_id in str(exc.value)
    assert str(source_path) not in str(exc.value)
    assert str(target_path) not in str(exc.value)


async def test_trusted_mount_source_rejects_stale_generation(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "stale-source"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Stale source",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        connector_id = connector.connector_id
        stale_generation = connector.mount_generation
        connector.mount_generation += 1
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(WorkspaceConnectorMountError) as exc:
            await resolve_trusted_mount_sources(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                connector_generations={connector_id: stale_generation},
            )

    assert exc.value.code == "WORKSPACE_CONNECTOR_GENERATION_MISMATCH"
    assert connector_id in str(exc.value)


async def test_trusted_mount_source_handles_generation_change_after_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "raced-source"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Raced source",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    real_resolve_mount_bundle = mount_module.resolve_mount_bundle
    changed_generation = False

    async def resolve_then_change_generation(*args, **kwargs):
        nonlocal changed_generation
        bundle = await real_resolve_mount_bundle(*args, **kwargs)
        if not changed_generation:
            changed_generation = True
            db = args[0] if args else kwargs["db"]
            stored = (
                await db.execute(
                    select(WorkspaceConnector).where(
                        WorkspaceConnector.connector_id == connector.connector_id
                    )
                )
            ).scalar_one()
            stored.mount_generation += 1
            await db.flush()
        return bundle

    monkeypatch.setattr(mount_module, "resolve_mount_bundle", resolve_then_change_generation)

    async with _async_session_factory() as db:
        with pytest.raises(WorkspaceConnectorMountError) as exc:
            await mount_module.resolve_trusted_mount_sources(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                connector_generations={connector.connector_id: connector.mount_generation},
            )

    assert exc.value.code == "WORKSPACE_CONNECTOR_GENERATION_MISMATCH"
    assert connector.connector_id in str(exc.value)


async def test_trusted_mount_source_revalidates_disabled_connector_after_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "disabled-source"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Disabled source",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    real_resolve_mount_bundle = mount_module.resolve_mount_bundle
    disabled = False

    async def resolve_then_disable(*args, **kwargs):
        nonlocal disabled
        bundle = await real_resolve_mount_bundle(*args, **kwargs)
        if not disabled:
            disabled = True
            async with _async_session_factory() as external_db:
                stored = (
                    await external_db.execute(
                        select(WorkspaceConnector).where(
                            WorkspaceConnector.connector_id == connector.connector_id
                        )
                    )
                ).scalar_one()
                stored.enabled = False
                await external_db.commit()
        return bundle

    monkeypatch.setattr(mount_module, "resolve_mount_bundle", resolve_then_disable)

    async with _async_session_factory() as db:
        with pytest.raises(WorkspaceConnectorMountError) as exc:
            await mount_module.resolve_trusted_mount_sources(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                connector_generations={connector.connector_id: connector.mount_generation},
            )

    assert exc.value.code == "WORKSPACE_CONNECTOR_REVOKED"
    assert connector.connector_id in str(exc.value)


async def test_mount_bundle_propagates_to_sandbox_proxy_without_raw_host_path(
    monkeypatch: pytest.MonkeyPatch,
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WORKSPACE_CONNECTOR_VOLUME", "chainless_test_workspace")
    monkeypatch.setenv("WORKSPACE_CONNECTOR_VOLUME_SUBPATH_PREFIX", "connectors")
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "data"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path, mode="read_write")
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Approved data",
            host_path=host_path,
            mode="read_write",
            approval_id=approval.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        bundle = await resolve_mount_bundle(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            connector_ids=[connector.connector_id],
        )

    payload = build_sandbox_mount_payload(bundle)
    raw_payload = repr(payload).lower()
    assert str(tmp_path).lower() not in raw_payload
    assert "host_path" not in raw_payload
    assert "host_realpath" not in raw_payload

    proxy_main = _load_sandbox_proxy_main()
    request = proxy_main.ParentExecuteRequest(
        run_id="workspace-connector-contract",
        capability="workspace connector contract acceptance",
        script="print('ok')",
        mount_bundle=payload,
    )
    assert request.mount_bundle.mounts[0].connector_id == connector.connector_id
    docker_mounts = proxy_main._connector_docker_mounts(request.mount_bundle)
    assert len(docker_mounts) == 1
    assert docker_mounts[0]["Type"] == "volume"
    assert docker_mounts[0]["Source"] == "chainless_test_workspace"
    assert docker_mounts[0]["Target"] == f"/workspace/connectors/{connector.connector_id}"
    assert docker_mounts[0]["ReadOnly"] is False
    assert docker_mounts[0]["VolumeOptions"]["Subpath"] == f"connectors/{connector.connector_id}"
    read_only_payload = {
        **payload,
        "mounts": [
            {
                **payload["mounts"][0],
                "mode": "read_only",
            }
        ],
    }
    read_only_request = proxy_main.ParentExecuteRequest(
        run_id="workspace-connector-read-only-contract",
        capability="workspace connector read only contract",
        script="print('ok')",
        mount_bundle=read_only_payload,
    )
    read_only_mounts = proxy_main._connector_docker_mounts(read_only_request.mount_bundle)
    assert read_only_mounts[0]["ReadOnly"] is True

    with pytest.raises(ValueError, match="raw host paths"):
        proxy_main.ParentExecuteRequest(
            run_id="bad-workspace-connector-contract",
            capability="workspace connector contract rejection",
            script="print('bad')",
            mount_bundle={
                **payload,
                "mounts": [
                    {
                        **payload["mounts"][0],
                        "host_path": str(tmp_path / "data"),
                    }
                ],
            },
        )
    with pytest.raises(ValueError):
        proxy_main.ParentExecuteRequest(
            run_id="bad-workspace-connector-secret-contract",
            capability="workspace connector contract rejection",
            script="print('bad')",
            mount_bundle={
                **payload,
                "mounts": [
                    {
                        **payload["mounts"][0],
                        "host_path_secret_ref": "ciphertext",
                    }
                ],
            },
        )
    with pytest.raises(ValueError):
        proxy_main.ParentExecuteRequest(
            run_id="bad-workspace-connector-schema-contract",
            capability="workspace connector contract rejection",
            script="print('bad')",
            mount_bundle={
                **payload,
                "schema_version": "workspace_connector_mounts.v2",
            },
        )
    payload_without_schema = dict(payload)
    payload_without_schema.pop("schema_version")
    with pytest.raises(ValueError):
        proxy_main.ParentExecuteRequest(
            run_id="missing-workspace-connector-schema-contract",
            capability="workspace connector contract rejection",
            script="print('bad')",
            mount_bundle=payload_without_schema,
        )
    with pytest.raises(ValueError, match="mount paths must match connector_id"):
        proxy_main.ParentExecuteRequest(
            run_id="bad-workspace-connector-path-contract",
            capability="workspace connector contract rejection",
            script="print('bad')",
            mount_bundle={
                **payload,
                "mounts": [
                    {
                        **payload["mounts"][0],
                        "sandbox_mount_path": "/workspace/connectors/wsc_00000000000000000000000000000000",
                    }
                ],
            },
        )


async def test_sandbox_proxy_fails_closed_when_connector_volume_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKSPACE_CONNECTOR_VOLUME", raising=False)
    monkeypatch.setenv("WORKSPACE_CONNECTOR_VOLUME_SUBPATH_PREFIX", "connectors")
    proxy_main = _load_sandbox_proxy_main()
    connector_id = f"wsc_{uuid.uuid4().hex}"
    request = proxy_main.ParentExecuteRequest(
        run_id="workspace-connector-missing-volume",
        capability="workspace connector missing volume contract",
        script="print('bad')",
        mount_bundle={
            "schema_version": "workspace_connector_mounts.v1",
            "mounts": [
                {
                    "connector_id": connector_id,
                    "generation": 1,
                    "container_mount_path": f"/workspace/connectors/{connector_id}",
                    "backend_mount_path": f"/workspace/connectors/{connector_id}",
                    "sandbox_mount_path": f"/workspace/connectors/{connector_id}",
                    "mode": "read_only",
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="WORKSPACE_CONNECTOR_VOLUME"):
        proxy_main._connector_docker_mounts(request.mount_bundle)


async def test_raw_host_path_is_never_exposed_to_agent_context(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "private-project"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Private project",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        bundle = await resolve_mount_bundle(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            connector_ids=[connector.connector_id],
        )

    context = agent_context_for_mount_bundle(bundle)
    rendered = repr(context)
    assert str(host_path) not in rendered
    assert "host_realpath_hash" not in rendered
    assert "host_path_secret_ref" not in rendered
    assert context["workspace_connectors"][0]["connector_id"] == connector.connector_id
    assert context["workspace_connectors"][0]["path"] == connector.sandbox_mount_path


async def test_file_read_accepts_connector_mounted_path(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "approved-files"
    host_path.mkdir()
    (host_path / "file.txt").write_text("connector fact: arctic tern\n", encoding="utf-8")
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Readable connector",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        bundle = await resolve_mount_bundle(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            connector_ids=[connector.connector_id],
        )
        sources = await resolve_trusted_mount_sources(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            connector_generations={connector.connector_id: connector.mount_generation},
        )

    context = {
        "workspace_connector_mount_bundle": bundle,
        "workspace_connector_trusted_sources": sources,
    }
    absolute_result = await file_ops.execute(
        "file_read",
        {"path": f"/workspace/connectors/{connector.connector_id}/file.txt"},
        context=context,
    )
    relative_result = await file_ops.execute(
        "file_read",
        {"path": f"connectors/{connector.connector_id}/file.txt"},
        context=context,
    )

    assert absolute_result == "connector fact: arctic tern\n"
    assert relative_result == "connector fact: arctic tern\n"


async def test_run_agent_file_read_uses_connector_mount_context(tmp_path: Path) -> None:
    connector_id = f"wsc_{uuid.uuid4().hex}"
    host_path = tmp_path / "agent-readable"
    host_path.mkdir()
    (host_path / "file.txt").write_text("agent connector fact\n", encoding="utf-8")
    _, _, connector_context = _synthetic_mount_context(connector_id, host_path)

    class Gateway:
        calls = 0

        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "tool_call",
                    "index": 0,
                    "id": "connector-file-read",
                    "name": "file_read",
                    "arguments": json.dumps(
                        {"path": f"/workspace/connectors/{connector_id}/file.txt"}
                    ),
                }
                return
            yield {"type": "text", "content": "done"}

    events = [
        event
        async for event in run_agent(
            Gateway(),
            sandbox_manager=object(),
            provider="default",
            messages=[{"role": "user", "content": "read connector file"}],
            tools=file_ops.FILE_TOOLS,
            tenant_id="tenant-a",
            connector_mount_context=connector_context,
        )
    ]

    tool_result = next(event for event in events if event["type"] == "tool_result")
    assert tool_result["name"] == "file_read"
    assert tool_result["result"] == "agent connector fact\n"
    assert str(host_path) not in repr(events)


async def test_run_agent_code_as_action_passes_connector_mount_bundle(tmp_path: Path) -> None:
    connector_id = f"wsc_{uuid.uuid4().hex}"
    host_path = tmp_path / "agent-code-action"
    host_path.mkdir()
    bundle, _, connector_context = _synthetic_mount_context(connector_id, host_path)
    expected_payload = build_sandbox_mount_payload(bundle)

    class Gateway:
        calls = 0

        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "tool_call",
                    "index": 0,
                    "id": "connector-code-action",
                    "name": "code_as_action",
                    "arguments": json.dumps({"script": "print('connector code ok')"}),
                }
                return
            yield {"type": "text", "content": "done"}

    class Sandbox:
        captured: dict | None = None

        async def execute_disposable_parent(self, **kwargs):
            self.captured = kwargs
            return {
                "container_id": "connector-code-parent",
                "deleted": True,
                "active_container_ids": [],
                "cleanup_errors": [],
                "stdout": "connector code ok",
                "stderr": "",
            }

    sandbox = Sandbox()
    events = [
        event
        async for event in run_agent(
            Gateway(),
            sandbox,
            "default",
            [{"role": "user", "content": "run connector code"}],
            tools=[CODE_AS_ACTION_TOOL],
            tenant_id="tenant-a",
            connector_mount_context=connector_context,
        )
    ]

    assert sandbox.captured is not None
    assert sandbox.captured["mount_bundle"] == expected_payload
    assert str(host_path) not in repr(sandbox.captured["mount_bundle"])
    assert any(event.get("data") == "connector code ok" for event in events)


async def test_confirmed_tools_receive_connector_context_without_host_path_leaks(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    connector_id = f"wsc_{uuid.uuid4().hex}"
    host_path = tmp_path / "confirmed-readable"
    host_path.mkdir()
    (host_path / "file.txt").write_text("confirmed connector fact\n", encoding="utf-8")
    bundle, _, connector_context = _synthetic_mount_context(connector_id, host_path)

    file_result = await execute_confirmed_tool(
        "file_read",
        {"path": f"/workspace/connectors/{connector_id}/file.txt"},
        sandbox=object(),
        gateway=object(),
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        connector_mount_context=connector_context,
    )
    assert file_result == "confirmed connector fact\n"

    class Sandbox:
        captured: dict | None = None

        async def execute_disposable_parent(self, **kwargs):
            self.captured = kwargs
            return {
                "container_id": "confirmed-code-parent",
                "deleted": True,
                "active_container_ids": [],
                "cleanup_errors": [],
                "stdout": "confirmed code ok",
                "stderr": "",
            }

    sandbox = Sandbox()
    code_result = await execute_confirmed_tool(
        "code_as_action",
        {"script": "print('confirmed code ok')"},
        sandbox=sandbox,
        gateway=object(),
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        connector_mount_context=connector_context,
    )
    assert "confirmed code ok" in code_result
    assert sandbox.captured is not None
    assert sandbox.captured["mount_bundle"] == build_sandbox_mount_payload(bundle)
    assert str(host_path) not in repr(sandbox.captured["mount_bundle"])

    async with _async_session_factory() as db:
        conversation = Conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            title="connector confirmation leak guard",
        )
        db.add(conversation)
        await db.flush()
        conversation_id = conversation.id
        await persist_confirmation_required(
            db,
            conversation_id,
            tool_call_id="confirmed-connector-leak-guard",
            tool_name="file_read",
            args={
                "path": f"/workspace/connectors/{connector_id}/file.txt",
                WORKSPACE_CONNECTOR_CONTEXT_ARG: {
                    "workspace_connector_mount_bundle": build_sandbox_mount_payload(bundle),
                    "workspace_connector_trusted_sources": [
                        {
                            "connector_id": connector_id,
                            "generation": 1,
                            "host_path": str(host_path),
                            "mode": "read_only",
                        }
                    ],
                },
            },
            risk="destructive",
            timeout_s=30,
        )
        stored = (
            await db.execute(
                select(ToolConfirmation).where(
                    ToolConfirmation.conversation_id == conversation_id,
                    ToolConfirmation.tool_call_id == "confirmed-connector-leak-guard",
                )
            )
        ).scalar_one()
        messages = (
            await db.execute(
                select(Message).where(Message.conversation_id == conversation_id)
            )
        ).scalars().all()

    assert WORKSPACE_CONNECTOR_CONTEXT_ARG not in stored.args
    assert str(host_path) not in repr(stored.args)
    assert str(host_path) not in repr([message.meta_data for message in messages])


async def test_confirmed_tool_ignores_embedded_workspace_connector_context(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    connector_id = f"wsc_{uuid.uuid4().hex}"
    host_path = tmp_path / "embedded-context-must-not-work"
    host_path.mkdir()
    (host_path / "secret.txt").write_text("embedded host secret\n", encoding="utf-8")
    bundle, _, _ = _synthetic_mount_context(connector_id, host_path)
    malicious_args = {
        "path": f"/workspace/connectors/{connector_id}/secret.txt",
        WORKSPACE_CONNECTOR_CONTEXT_ARG: {
            "workspace_connector_mount_bundle": build_sandbox_mount_payload(bundle),
            "workspace_connector_trusted_sources": [
                {
                    "connector_id": connector_id,
                    "generation": 1,
                    "host_path": str(host_path),
                    "mode": "read_only",
                }
            ],
        },
    }

    with pytest.raises(WorkspaceConnectorMountError) as exc:
        await execute_confirmed_tool(
            "file_read",
            malicious_args,
            sandbox=object(),
            gateway=object(),
            tenant_id=str(tenant_id),
            user_id=str(user_id),
        )

    assert exc.value.code == "WORKSPACE_CONNECTOR_NOT_MOUNTED"
    assert str(host_path) not in str(exc.value)


async def test_revoked_connector_file_read_fails_with_actionable_message(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "revoked-files"
    host_path.mkdir()
    (host_path / "file.txt").write_text("must not be reachable\n", encoding="utf-8")
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Revoked file connector",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        connector_id = connector.connector_id
        await db.commit()

    async with _async_session_factory() as db:
        bundle = await resolve_mount_bundle(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            connector_ids=[connector_id],
        )
        await revoke_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            connector_id=connector_id,
            reason="user revoked access before file read",
        )
        await db.commit()

    with pytest.raises(WorkspaceConnectorMountError) as exc:
        await file_ops.execute(
            "file_read",
            {"path": f"/workspace/connectors/{connector_id}/file.txt"},
            context={"workspace_connector_mount_bundle": bundle},
        )

    assert exc.value.code == "WORKSPACE_CONNECTOR_SOURCE_UNAVAILABLE"
    assert connector_id in str(exc.value)
    assert "approve it again" in str(exc.value)
    assert str(host_path) not in str(exc.value)


async def test_runtime_context_materializes_source_and_omits_raw_host_path(
    monkeypatch: pytest.MonkeyPatch,
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "runtime-source"
    host_path.mkdir()
    (host_path / "fact.txt").write_text("runtime materialized fact\n", encoding="utf-8")
    approval = await _confirmation(tenant_id, user_id, host_path=host_path, mode="read_write")

    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Runtime materialized connector",
            host_path=host_path,
            mode="read_write",
            approval_id=approval.id,
        )
        await db.commit()

    async def fail_if_legacy_resolver_is_used(*args, **kwargs):
        raise AssertionError("runtime context should not use per-connector resolver path")

    monkeypatch.setattr(mount_module, "resolve_mount_bundle", fail_if_legacy_resolver_is_used)
    monkeypatch.setattr(
        mount_module,
        "resolve_trusted_mount_sources",
        fail_if_legacy_resolver_is_used,
    )

    async with _async_session_factory() as db:
        context = await build_workspace_connector_runtime_context(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    assert context is not None
    rendered_context = repr(context)
    assert str(host_path) not in rendered_context
    assert "host_realpath_hash" not in rendered_context
    assert "host_path_secret_ref" not in rendered_context
    bundle = context["workspace_connector_mount_bundle"]
    assert bundle.mounts[0].mode == "read_only"
    sources = context["workspace_connector_trusted_sources"]
    assert len(sources) == 1
    assert sources[0].connector_id == connector.connector_id
    assert sources[0].host_path.startswith(f"/workspace/connectors/{connector.connector_id}")
    assert sources[0].mode == "read_only"
    assert str(host_path) not in sources[0].host_path
    payload = context["workspace_connector_sandbox_mount_payload"]
    assert payload["mounts"][0]["mode"] == "read_only"

    result = await file_ops.execute(
        "file_read",
        {"path": f"/workspace/connectors/{connector.connector_id}/fact.txt"},
        context=context,
    )
    assert result == "runtime materialized fact\n"

    with pytest.raises(WorkspaceConnectorMountError) as exc:
        await file_ops.execute(
            "file_write",
            {
                "path": f"/workspace/connectors/{connector.connector_id}/fact.txt",
                "content": "must not write to runtime snapshot\n",
            },
            context=context,
        )

    assert exc.value.code == "WORKSPACE_CONNECTOR_READ_ONLY"
    assert (host_path / "fact.txt").read_text(encoding="utf-8") == "runtime materialized fact\n"


async def test_runtime_context_skips_missing_source_without_raw_path(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "runtime-missing-source"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Runtime missing connector",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        context = await build_workspace_connector_runtime_context(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    assert context is None


async def test_workspace_connector_runtime_flag_blocks_mount_materialization(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "runtime-disabled-source"
    host_path.mkdir()
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Runtime disabled connector",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    monkeypatch.setattr("app.core.acquisition.facade.settings.acquisition_workspace_connectors_enabled", False)

    async with _async_session_factory() as db:
        assert await build_workspace_connector_runtime_context(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
        ) is None
        with pytest.raises(WorkspaceConnectorMountError, match="Workspace Connector runtime is disabled"):
            await resolve_mount_bundle(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                connector_ids=[connector.connector_id],
            )


async def test_connector_file_read_missing_path_does_not_leak_host_path(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "missing-file-source"
    host_path.mkdir()
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Missing file connector",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        context = await build_workspace_connector_runtime_context(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    with pytest.raises(WorkspaceConnectorMountError) as exc:
        await file_ops.execute(
            "file_read",
            {"path": f"/workspace/connectors/{connector.connector_id}/missing.txt"},
            context=context,
        )

    assert exc.value.code == "WORKSPACE_CONNECTOR_PATH_NOT_FOUND"
    assert connector.connector_id in str(exc.value)
    assert str(host_path) not in str(exc.value)


async def test_code_as_action_propagates_connector_mount_bundle_contract(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "code-action-source"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Code action connector",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        bundle = await resolve_mount_bundle(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            connector_ids=[connector.connector_id],
        )

    payload = build_sandbox_mount_payload(bundle)

    class Sandbox:
        captured: dict | None = None

        async def execute_disposable_parent(self, **kwargs):
            self.captured = kwargs
            return {
                "container_id": "contract-parent",
                "deleted": True,
                "active_container_ids": [],
                "cleanup_errors": [],
                "stdout": "contract ok",
                "stderr": "",
            }

    sandbox = Sandbox()
    events = [
        event
        async for event in stream_code_as_action(
            "print('contract ok')",
            sandbox,
            gateway=object(),
            tenant_id=str(tenant_id),
            parent_budget=1000,
            mount_bundle=payload,
        )
    ]

    assert sandbox.captured is not None
    assert sandbox.captured["mount_bundle"] == payload
    assert "host" not in repr(sandbox.captured["mount_bundle"]).lower()
    assert any(event.get("data") == "contract ok" for event in events)


@pytest.mark.live_docker
async def test_code_as_action_reads_connector_mounted_path_in_live_sandbox(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    if os.environ.get("CHAINLESS_LIVE_DOCKER") != "1":
        pytest.skip("set CHAINLESS_LIVE_DOCKER=1 inside backend-test-live")
    assert os.environ.get("CHAINLESS_LIVE_CONNECTOR_MOUNT_ROOT_READY") == "1"

    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "approved-live-source.txt"
    host_path.write_text("live approved connector fact\n", encoding="utf-8")
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Live approved source",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        connector_id = connector.connector_id
        await db.commit()

    connector_path = Path("/workspace/connectors") / connector_id
    assert not (connector_path / host_path.name).exists()
    async with _async_session_factory() as db:
        context = await build_workspace_connector_runtime_context(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    assert context is not None
    assert (connector_path / host_path.name).read_text(encoding="utf-8") == (
        "live approved connector fact\n"
    )
    assert str(host_path) not in repr(context)
    payload = context["workspace_connector_sandbox_mount_payload"]

    class LiveSettings:
        sandbox_proxy_url = os.environ["SANDBOX_PROXY_URL"]
        proxy_auth_token = os.environ["PROXY_AUTH_TOKEN"]
        sandbox_pool_min = 0
        sandbox_pool_max = 0

    manager = SandboxManager(LiveSettings())
    try:
        output = await execute_code_as_action(
            (
                "from pathlib import Path\n"
                f"print(Path('/workspace/connectors/{connector_id}/{host_path.name}').read_text())"
            ),
            manager,
            gateway=object(),
            tenant_id=str(tenant_id),
            parent_budget=1000,
            mount_bundle=payload,
        )
    finally:
        await manager.close()
        shutil.rmtree(connector_path, ignore_errors=True)

    assert "live approved connector fact" in output


async def test_connector_revocation_blocks_future_mounts(
    tenant_a_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    host_path = tmp_path / "revoked"
    approval = await _confirmation(tenant_id, user_id, host_path=host_path)
    async with _async_session_factory() as db:
        connector = await create_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Revoked workspace",
            host_path=host_path,
            mode="read_only",
            approval_id=approval.id,
        )
        await db.commit()

    async with _async_session_factory() as db:
        revoked = await revoke_workspace_connector(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            connector_id=connector.connector_id,
            reason="user revoked local workspace access",
        )
        await db.commit()
        assert revoked.enabled is False
        assert revoked.mount_generation == 2

    async with _async_session_factory() as db:
        with pytest.raises(WorkspaceConnectorMountError) as exc:
            await resolve_mount_bundle(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                connector_ids=[connector.connector_id],
            )

    assert exc.value.code == "WORKSPACE_CONNECTOR_REVOKED"
    assert connector.connector_id in str(exc.value)
