"""Workspace Connector mount-bundle resolver.

Mount bundles are the only runtime-facing representation of approved workspace
access. They contain connector ids, generations, and container paths; raw host
paths and host realpath hashes are intentionally omitted.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secrets import SecretDecryptionError, decrypt_secret
from app.models.acquisition import WorkspaceConnector


_RUNTIME_MATERIALIZED_CONNECTOR_MODE = "read_only"


class WorkspaceConnectorMountError(RuntimeError):
    """Actionable mount-resolution failure."""

    def __init__(self, code: str, message: str, *, connector_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.connector_id = connector_id


@dataclass(frozen=True)
class WorkspaceConnectorMount:
    connector_id: str
    generation: int
    container_mount_path: str
    backend_mount_path: str
    sandbox_mount_path: str
    mode: str


@dataclass(frozen=True)
class WorkspaceConnectorMountBundle:
    schema_version: str
    mounts: list[WorkspaceConnectorMount]


@dataclass(frozen=True)
class TrustedWorkspaceConnectorMountSource:
    connector_id: str
    generation: int
    host_path: str
    mode: str


def materialize_workspace_connector_source(
    *,
    source: TrustedWorkspaceConnectorMountSource,
    mount: WorkspaceConnectorMount,
) -> TrustedWorkspaceConnectorMountSource:
    """Copy the approved source into the backend connector mount path.

    The returned source points at the materialized backend path, not the raw
    approved host path. Runtime callers pass read-only mount/source modes
    because W5.2 materialization is snapshot-only and does not sync writes back.
    """

    if source.connector_id != mount.connector_id or source.generation != mount.generation:
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_GENERATION_MISMATCH",
            (
                "Workspace Connector generation mismatch; "
                f"ask the user to approve it again: {mount.connector_id}"
            ),
            connector_id=mount.connector_id,
        )

    source_path = Path(source.host_path).expanduser()
    target_path = Path(mount.backend_mount_path)
    try:
        source_resolved = source_path.resolve(strict=True)
    except OSError as exc:
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_SOURCE_UNAVAILABLE",
            (
                "Workspace Connector source is unavailable; "
                f"ask the user to approve it again: {mount.connector_id}"
            ),
            connector_id=mount.connector_id,
        ) from exc

    try:
        target_resolved = target_path.resolve(strict=False)
    except OSError as exc:
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_TARGET_UNAVAILABLE",
            (
                "Workspace Connector mount target is unavailable; "
                f"ask the user to approve it again: {mount.connector_id}"
            ),
            connector_id=mount.connector_id,
        ) from exc

    same_path = source_resolved == target_resolved
    if source_resolved.is_dir() and _is_relative_to(target_resolved, source_resolved) and not same_path:
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_RECURSIVE_MATERIALIZATION",
            (
                "Workspace Connector source cannot be materialized inside itself; "
                f"ask the user to approve a narrower source path: {mount.connector_id}"
            ),
            connector_id=mount.connector_id,
        )

    try:
        if same_path:
            materialized_path = target_resolved
        elif source_resolved.is_dir():
            _clean_materialization_target(target_resolved)
            target_resolved.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_resolved, target_resolved, dirs_exist_ok=True, symlinks=True)
            materialized_path = target_resolved
        elif source_resolved.is_file():
            _clean_materialization_target(target_resolved)
            target_resolved.mkdir(parents=True, exist_ok=True)
            materialized_file = target_resolved / source_resolved.name
            shutil.copy2(source_resolved, materialized_file, follow_symlinks=False)
            materialized_path = target_resolved
        else:
            raise WorkspaceConnectorMountError(
                "WORKSPACE_CONNECTOR_SOURCE_UNAVAILABLE",
                (
                    "Workspace Connector source is unavailable; "
                    f"ask the user to approve it again: {mount.connector_id}"
                ),
                connector_id=mount.connector_id,
            )
    except WorkspaceConnectorMountError:
        raise
    except OSError as exc:
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_MATERIALIZATION_FAILED",
            (
                "Workspace Connector source could not be prepared for this run; "
                f"check access or ask the user to approve it again: {mount.connector_id}"
            ),
            connector_id=mount.connector_id,
        ) from exc

    return TrustedWorkspaceConnectorMountSource(
        connector_id=source.connector_id,
        generation=source.generation,
        host_path=str(materialized_path),
        mode=source.mode,
    )


async def resolve_mount_bundle(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    connector_ids: Sequence[str],
) -> WorkspaceConnectorMountBundle:
    """Resolve enabled user-scoped connectors to a sanitized runtime bundle."""

    if not connector_ids:
        return WorkspaceConnectorMountBundle(schema_version="workspace_connector_mounts.v1", mounts=[])

    requested = [str(connector_id) for connector_id in connector_ids]
    records = list(
        (
            await db.execute(
                select(WorkspaceConnector).where(
                    WorkspaceConnector.tenant_id == tenant_id,
                    WorkspaceConnector.user_id == user_id,
                    WorkspaceConnector.connector_id.in_(requested),
                )
            )
        ).scalars()
    )
    by_id = {record.connector_id: record for record in records}
    mounts: list[WorkspaceConnectorMount] = []
    now = datetime.now(timezone.utc)
    for connector_id in requested:
        record = by_id.get(connector_id)
        if record is None:
            raise WorkspaceConnectorMountError(
                "WORKSPACE_CONNECTOR_NOT_FOUND",
                f"Workspace Connector not found or not accessible for this user: {connector_id}",
                connector_id=connector_id,
            )
        if not record.enabled:
            raise WorkspaceConnectorMountError(
                "WORKSPACE_CONNECTOR_REVOKED",
                f"Workspace Connector has been revoked; ask the user to approve it again: {connector_id}",
                connector_id=connector_id,
            )
        if record.expires_at is not None and record.expires_at <= now:
            raise WorkspaceConnectorMountError(
                "WORKSPACE_CONNECTOR_EXPIRED",
                f"Workspace Connector has expired; ask the user to renew approval: {connector_id}",
                connector_id=connector_id,
            )
        if record.mount_health_status in {"unhealthy", "stale"}:
            raise WorkspaceConnectorMountError(
                "WORKSPACE_CONNECTOR_STALE",
                f"Workspace Connector mount is stale; ask the user to re-approve it: {connector_id}",
                connector_id=connector_id,
            )
        mounts.append(
            WorkspaceConnectorMount(
                connector_id=record.connector_id,
                generation=record.mount_generation,
                container_mount_path=record.container_mount_path,
                backend_mount_path=record.backend_mount_path,
                sandbox_mount_path=record.sandbox_mount_path,
                mode=record.mode,
            )
        )
    return WorkspaceConnectorMountBundle(schema_version="workspace_connector_mounts.v1", mounts=mounts)


async def resolve_trusted_mount_sources(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    connector_generations: dict[str, int],
) -> list[TrustedWorkspaceConnectorMountSource]:
    """Resolve connector generation pins to real host paths for the mount owner only."""

    if not connector_generations:
        return []

    bundle = await resolve_mount_bundle(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        connector_ids=list(connector_generations),
    )
    sources: list[TrustedWorkspaceConnectorMountSource] = []
    now = datetime.now(timezone.utc)
    for mount in bundle.mounts:
        expected_generation = connector_generations[mount.connector_id]
        if mount.generation != expected_generation:
            raise WorkspaceConnectorMountError(
                "WORKSPACE_CONNECTOR_GENERATION_MISMATCH",
                f"Workspace Connector generation mismatch; ask the user to approve it again: {mount.connector_id}",
                connector_id=mount.connector_id,
            )
        record = (
            await db.execute(
                select(WorkspaceConnector).where(
                    WorkspaceConnector.tenant_id == tenant_id,
                    WorkspaceConnector.user_id == user_id,
                    WorkspaceConnector.connector_id == mount.connector_id,
                    WorkspaceConnector.mount_generation == mount.generation,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if record is None:
            raise WorkspaceConnectorMountError(
                "WORKSPACE_CONNECTOR_GENERATION_MISMATCH",
                (
                    "Workspace Connector source changed or is no longer available; "
                    f"ask the user to approve it again: {mount.connector_id}"
                ),
                connector_id=mount.connector_id,
            )
        _raise_if_connector_not_mountable(record, now=now)
        if not record.host_path_secret_ref:
            raise WorkspaceConnectorMountError(
                "WORKSPACE_CONNECTOR_SOURCE_UNAVAILABLE",
                f"Workspace Connector source path is unavailable; ask the user to approve it again: {mount.connector_id}",
                connector_id=mount.connector_id,
            )
        try:
            host_path = decrypt_secret(record.host_path_secret_ref)
        except SecretDecryptionError as exc:
            raise WorkspaceConnectorMountError(
                "WORKSPACE_CONNECTOR_SOURCE_UNAVAILABLE",
                f"Workspace Connector source path is unavailable; ask the user to approve it again: {mount.connector_id}",
                connector_id=mount.connector_id,
            ) from exc
        sources.append(
            TrustedWorkspaceConnectorMountSource(
                connector_id=mount.connector_id,
                generation=mount.generation,
                host_path=host_path,
                mode=mount.mode,
            )
        )
    return sources


async def build_workspace_connector_runtime_context(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Build trusted server-side connector context for one user run.

    Production chat mounts every currently enabled user-scoped connector. This
    hot path intentionally avoids per-connector row locks: it validates current
        record state, decrypts the approved source once, materializes a read-only
        snapshot into the backend mount path, and skips unavailable connectors
        without blocking an otherwise normal chat turn. The durable connector mode
        remains available through explicit owner resolvers; runtime snapshots are
        not a write-back surface.
    """

    records = list(
        (
            await db.execute(
                select(WorkspaceConnector).where(
                    WorkspaceConnector.tenant_id == tenant_id,
                    WorkspaceConnector.user_id == user_id,
                    WorkspaceConnector.enabled.is_(True),
                )
            )
        ).scalars()
    )
    if not records:
        return None

    mounts: list[WorkspaceConnectorMount] = []
    materialized_sources: list[TrustedWorkspaceConnectorMountSource] = []
    now = datetime.now(timezone.utc)
    for record in records:
        try:
            _raise_if_connector_not_mountable(record, now=now)
            if not record.host_path_secret_ref:
                raise WorkspaceConnectorMountError(
                    "WORKSPACE_CONNECTOR_SOURCE_UNAVAILABLE",
                    (
                        "Workspace Connector source path is unavailable; "
                        f"ask the user to approve it again: {record.connector_id}"
                    ),
                    connector_id=record.connector_id,
                )
            mount = WorkspaceConnectorMount(
                connector_id=record.connector_id,
                generation=record.mount_generation,
                container_mount_path=record.container_mount_path,
                backend_mount_path=record.backend_mount_path,
                sandbox_mount_path=record.sandbox_mount_path,
                mode=_RUNTIME_MATERIALIZED_CONNECTOR_MODE,
            )
            raw_source = TrustedWorkspaceConnectorMountSource(
                connector_id=record.connector_id,
                generation=record.mount_generation,
                host_path=decrypt_secret(record.host_path_secret_ref),
                mode=_RUNTIME_MATERIALIZED_CONNECTOR_MODE,
            )
            materialized_source = materialize_workspace_connector_source(
                source=raw_source,
                mount=mount,
            )
        except (SecretDecryptionError, WorkspaceConnectorMountError):
            continue
        mounts.append(mount)
        materialized_sources.append(materialized_source)

    if not mounts:
        return None

    bundle = WorkspaceConnectorMountBundle(
        schema_version="workspace_connector_mounts.v1",
        mounts=mounts,
    )
    return {
        "workspace_connector_mount_bundle": bundle,
        "workspace_connector_trusted_sources": materialized_sources,
        "workspace_connector_sandbox_mount_payload": build_sandbox_mount_payload(bundle),
    }


def _raise_if_connector_not_mountable(record: WorkspaceConnector, *, now: datetime) -> None:
    """Re-check mutable connector state after trusted-source lookup races."""

    if not record.enabled:
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_REVOKED",
            f"Workspace Connector has been revoked; ask the user to approve it again: {record.connector_id}",
            connector_id=record.connector_id,
        )
    if record.expires_at is not None and record.expires_at <= now:
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_EXPIRED",
            f"Workspace Connector has expired; ask the user to renew approval: {record.connector_id}",
            connector_id=record.connector_id,
        )
    if record.mount_health_status in {"unhealthy", "stale"}:
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_STALE",
            f"Workspace Connector mount is stale; ask the user to re-approve it: {record.connector_id}",
            connector_id=record.connector_id,
        )


def _clean_materialization_target(target_path: Path) -> None:
    """Remove a stale materialized snapshot before copying fresh contents."""

    if not target_path.exists() and not target_path.is_symlink():
        return
    if target_path.is_dir() and not target_path.is_symlink():
        shutil.rmtree(target_path)
        return
    target_path.unlink()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def build_sandbox_mount_payload(bundle: WorkspaceConnectorMountBundle) -> dict[str, Any]:
    """Return the sandbox-proxy mount contract without raw host path data."""

    return {
        "schema_version": bundle.schema_version,
        "mounts": [
            {
                "connector_id": mount.connector_id,
                "generation": mount.generation,
                "container_mount_path": mount.container_mount_path,
                "backend_mount_path": mount.backend_mount_path,
                "sandbox_mount_path": mount.sandbox_mount_path,
                "mode": mount.mode,
            }
            for mount in bundle.mounts
        ],
    }


_SANDBOX_MOUNT_KEYS = (
    "connector_id",
    "generation",
    "container_mount_path",
    "backend_mount_path",
    "sandbox_mount_path",
    "mode",
)


def sandbox_mount_payload_from_context(context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Extract the sandbox mount payload from trusted server-side agent context."""

    if not context:
        return None
    for key in ("workspace_connector_sandbox_mount_payload", "sandbox_mount_bundle"):
        payload = context.get(key)
        if payload is not None:
            return _sanitize_sandbox_mount_payload(payload)

    bundle = context.get("workspace_connector_mount_bundle")
    if bundle is None:
        bundle = context.get("mount_bundle")
    if bundle is None:
        return None
    if isinstance(bundle, WorkspaceConnectorMountBundle):
        return build_sandbox_mount_payload(bundle)
    return _sanitize_sandbox_mount_payload(bundle)


def _sanitize_sandbox_mount_payload(payload: Any) -> dict[str, Any]:
    mapped = _as_mapping(payload)
    mounts = mapped.get("mounts", [])
    if not isinstance(mounts, (list, tuple)):
        mounts = []
    sanitized_mounts: list[dict[str, Any]] = []
    for mount in mounts:
        mount_map = _as_mapping(mount)
        sanitized_mounts.append(
            {key: mount_map[key] for key in _SANDBOX_MOUNT_KEYS if key in mount_map}
        )
    return {
        "schema_version": mapped.get("schema_version", "workspace_connector_mounts.v1"),
        "mounts": sanitized_mounts,
    }


def _as_mapping(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def agent_context_for_mount_bundle(bundle: WorkspaceConnectorMountBundle) -> dict[str, Any]:
    """Return agent-visible connector context using only sandbox paths."""

    return {
        "workspace_connectors": [
            {
                "connector_id": mount.connector_id,
                "generation": mount.generation,
                "path": mount.sandbox_mount_path,
                "mode": mount.mode,
            }
            for mount in bundle.mounts
        ],
    }
