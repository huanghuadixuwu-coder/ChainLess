"""Policy validation for isolated stdio MCP runtime requests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


class MCPRuntimePolicyError(ValueError):
    """Raised when an stdio MCP runtime payload is not approved."""


@dataclass(frozen=True)
class StdioRuntimePolicy:
    """Approved stdio runtime payload handed to the isolated supervisor."""

    server_name: str
    command: str
    args: list[str]
    runtime_kind: str
    runtime_url: str
    image_ref: str
    command_provenance: dict[str, Any]
    package_digest: str
    env_secret_refs: list[dict[str, Any]]
    filesystem_policy: dict[str, Any]
    network_policy: dict[str, Any]
    resource_limits: dict[str, Any]
    max_session_seconds: int
    max_output_bytes: int
    restart_policy: dict[str, Any]
    approved_payload_hash: str


def validate_stdio_runtime_policy(
    server_name: str,
    config: dict[str, Any],
) -> StdioRuntimePolicy:
    """Validate and normalize an approved isolated stdio runtime payload."""

    if config.get("transport", "stdio") != "stdio":
        raise MCPRuntimePolicyError("stdio runtime policy only accepts stdio transport")
    if config.get("runtime_kind") != "isolated_stdio":
        raise MCPRuntimePolicyError("stdio transport requires isolated_stdio runtime_kind")

    command = _required_str(config, "command")
    runtime_url = str(config.get("stdio_runtime_url") or "http://mcp-runtime:9101").rstrip("/")
    image_ref = _required_str(config, "stdio_runtime_image_ref")
    package_digest = _required_str(config, "stdio_package_digest")
    if not package_digest.startswith(("sha256:", "sha512:")):
        raise MCPRuntimePolicyError("stdio_package_digest must be a pinned sha digest")

    command_provenance = _required_dict(config, "stdio_command_provenance")
    _require_truthy(command_provenance, "source", "stdio_command_provenance.source is required")
    _require_truthy(command_provenance, "approved_by", "stdio_command_provenance.approved_by is required")
    _require_truthy(command_provenance, "approved_at", "stdio_command_provenance.approved_at is required")

    filesystem_policy = _required_dict(config, "stdio_filesystem_policy")
    _validate_filesystem_policy(filesystem_policy)

    network_policy = _required_dict(config, "stdio_network_policy")
    _validate_network_policy(network_policy)

    resource_limits = _required_dict(config, "stdio_resource_limits")
    _validate_resource_limits(resource_limits)

    restart_policy = _required_dict(config, "stdio_restart_policy")
    _require_truthy(restart_policy, "max_restarts", "stdio_restart_policy.max_restarts is required")

    max_session_seconds = _positive_int(config, "stdio_max_session_seconds")
    max_output_bytes = _positive_int(config, "stdio_max_output_bytes")
    env_secret_refs = list(config.get("env_secret_refs", []))
    if env_secret_refs:
        raise MCPRuntimePolicyError("env_secret_refs are not supported until runtime secret injection exists")

    payload_hash = approved_payload_hash(
        command=command,
        args=[str(arg) for arg in config.get("args", [])],
        image_ref=image_ref,
        package_digest=package_digest,
        command_provenance=command_provenance,
        env_secret_refs=env_secret_refs,
        filesystem_policy=filesystem_policy,
        network_policy=network_policy,
        resource_limits=resource_limits,
        max_session_seconds=max_session_seconds,
        max_output_bytes=max_output_bytes,
        restart_policy=restart_policy,
    )

    return StdioRuntimePolicy(
        server_name=server_name,
        command=command,
        args=[str(arg) for arg in config.get("args", [])],
        runtime_kind="isolated_stdio",
        runtime_url=runtime_url,
        image_ref=image_ref,
        command_provenance=command_provenance,
        package_digest=package_digest,
        env_secret_refs=env_secret_refs,
        filesystem_policy=filesystem_policy,
        network_policy=network_policy,
        resource_limits=resource_limits,
        max_session_seconds=max_session_seconds,
        max_output_bytes=max_output_bytes,
        restart_policy=restart_policy,
        approved_payload_hash=payload_hash,
    )


def approved_payload_hash(
    *,
    command: str,
    args: list[str],
    image_ref: str,
    package_digest: str,
    command_provenance: dict[str, Any],
    env_secret_refs: list[dict[str, Any]],
    filesystem_policy: dict[str, Any],
    network_policy: dict[str, Any],
    resource_limits: dict[str, Any],
    max_session_seconds: int,
    max_output_bytes: int,
    restart_policy: dict[str, Any],
) -> str:
    """Return the canonical hash runtime and backend both approve."""

    payload = {
        "command": command,
        "args": args,
        "image_ref": image_ref,
        "package_digest": package_digest,
        "command_provenance": command_provenance,
        "env_secret_refs": env_secret_refs,
        "filesystem_policy": filesystem_policy,
        "network_policy": network_policy,
        "resource_limits": resource_limits,
        "max_session_seconds": max_session_seconds,
        "max_output_bytes": max_output_bytes,
        "restart_policy": restart_policy,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _required_str(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MCPRuntimePolicyError(f"{key} is required")
    return value


def _required_dict(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict) or not value:
        raise MCPRuntimePolicyError(f"{key} is required")
    return value


def _positive_int(config: dict[str, Any], key: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or value < 1:
        raise MCPRuntimePolicyError(f"{key} must be a positive integer")
    return value


def _require_truthy(payload: dict[str, Any], key: str, message: str) -> None:
    if not payload.get(key):
        raise MCPRuntimePolicyError(message)


def _validate_filesystem_policy(policy: dict[str, Any]) -> None:
    forbidden = {
        "/var/run/docker.sock",
        "/app",
        "/repo",
        "/workspace",
        "/",
    }
    mounts = policy.get("mounts", [])
    if not isinstance(mounts, list):
        raise MCPRuntimePolicyError("stdio_filesystem_policy.mounts must be a list")
    for mount in mounts:
        if not isinstance(mount, dict):
            raise MCPRuntimePolicyError("stdio_filesystem_policy.mounts entries must be objects")
        source = str(mount.get("source", ""))
        target = str(mount.get("target", ""))
        if source in forbidden or target in forbidden or source.startswith("/repo/"):
            raise MCPRuntimePolicyError("stdio runtime cannot mount docker socket, backend, workspace, or host filesystem")
        if not mount.get("approved"):
            raise MCPRuntimePolicyError("stdio filesystem mounts must be explicitly approved")
    if policy.get("allow_backend_fs") is not False:
        raise MCPRuntimePolicyError("stdio runtime must deny backend filesystem access")
    if policy.get("allow_docker_socket") is not False:
        raise MCPRuntimePolicyError("stdio runtime must deny docker socket access")
    if policy.get("allow_host_fs") is not False:
        raise MCPRuntimePolicyError("stdio runtime must deny host filesystem access")


def _validate_network_policy(policy: dict[str, Any]) -> None:
    allowed = policy.get("allowed_hosts", [])
    if not isinstance(allowed, list):
        raise MCPRuntimePolicyError("stdio_network_policy.allowed_hosts must be a list")
    if policy.get("mode") not in {"none", "allowlist"}:
        raise MCPRuntimePolicyError("stdio_network_policy.mode must be none or allowlist")
    if policy.get("mode") == "allowlist" and not allowed:
        raise MCPRuntimePolicyError("allowlist network mode requires allowed_hosts")
    if policy.get("deny_private_networks") is not True:
        raise MCPRuntimePolicyError("stdio runtime must deny private networks")


def _validate_resource_limits(limits: dict[str, Any]) -> None:
    required_positive = ("memory_mb", "cpus", "pids", "timeout_seconds")
    for key in required_positive:
        value = limits.get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            raise MCPRuntimePolicyError(f"stdio_resource_limits.{key} must be positive")
