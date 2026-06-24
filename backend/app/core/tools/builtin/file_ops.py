"""Builtin file operation tools for the agent workspace."""

import os
from dataclasses import asdict, is_dataclass
from typing import Any

from app.core.artifacts import ToolExecutionResult, capture_file_write_artifact
from app.core.workspace_connectors.mounts import WorkspaceConnectorMountError

_ALLOWED_BASE = os.environ.get("FILE_TOOLS_BASE_DIR", "/workspace")
_MAX_READ_BYTES = int(os.environ.get("FILE_TOOLS_MAX_READ_BYTES", "20000"))
_CONNECTOR_ROOT = "/workspace/connectors"
_CONNECTOR_CONTEXT_KEYS = ("workspace_connector_mount_bundle", "mount_bundle")
_CONNECTOR_SOURCE_KEYS = (
    "workspace_connector_trusted_sources",
    "workspace_connector_mount_sources",
)


def _workspace_base(context: dict | None = None) -> str:
    candidate = (context or {}).get("workspace_base")
    if isinstance(candidate, str) and candidate.strip():
        allowed = os.path.realpath(_ALLOWED_BASE)
        resolved = os.path.realpath(candidate)
        if not resolved.startswith(allowed + os.sep) and resolved != allowed:
            raise ValueError(
                "workspace_base override is not allowed for host paths; "
                "ask the user to approve a Workspace Connector instead"
            )
        return candidate
    return _ALLOWED_BASE


def _ensure_workspace(base: str) -> None:
    os.makedirs(os.path.realpath(base), exist_ok=True)


def _safe_resolve(path: str, *, base: str) -> str:
    """Resolve a workspace path and reject traversal outside the workspace."""
    allowed = os.path.realpath(base)
    requested = path.lstrip("/\\")
    resolved = os.path.realpath(os.path.join(allowed, requested))
    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        raise ValueError(f"Access denied: '{path}' is outside the workspace")
    return resolved


def _connector_request(path: str) -> tuple[str, str] | None:
    normalized = str(path or ".").replace("\\", "/").strip()
    if normalized.startswith(f"{_CONNECTOR_ROOT}/"):
        remainder = normalized.removeprefix(f"{_CONNECTOR_ROOT}/")
    elif normalized.startswith("workspace/connectors/"):
        remainder = normalized.removeprefix("workspace/connectors/")
    elif normalized.startswith("connectors/"):
        remainder = normalized.removeprefix("connectors/")
    else:
        return None

    connector_id, _, relative_path = remainder.partition("/")
    if not connector_id:
        return None
    return connector_id, relative_path or "."


def _as_mapping(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return {}


def _context_sequence(context: dict | None, keys: tuple[str, ...]) -> list[Any]:
    if not context:
        return []
    for key in keys:
        value = context.get(key)
        if value is None:
            continue
        if is_dataclass(value):
            mapped = asdict(value)
            value = mapped.get("mounts", value)
        elif hasattr(value, "model_dump"):
            mapped = value.model_dump()
            value = mapped.get("mounts", value)
        elif isinstance(value, dict):
            value = value.get("mounts", [])
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
    return []


def _connector_mount_for(context: dict | None, connector_id: str) -> dict[str, Any]:
    for mount in _context_sequence(context, _CONNECTOR_CONTEXT_KEYS):
        mapped = _as_mapping(mount)
        if mapped.get("connector_id") == connector_id:
            return mapped
    raise WorkspaceConnectorMountError(
        "WORKSPACE_CONNECTOR_NOT_MOUNTED",
        (
            "Workspace Connector is not mounted for this run; "
            f"ask the user to approve it again: {connector_id}"
        ),
        connector_id=connector_id,
    )


def _connector_source_for(context: dict | None, connector_id: str) -> dict[str, Any]:
    for source in _context_sequence(context, _CONNECTOR_SOURCE_KEYS):
        mapped = _as_mapping(source)
        if mapped.get("connector_id") == connector_id:
            return mapped
    raise WorkspaceConnectorMountError(
        "WORKSPACE_CONNECTOR_SOURCE_UNAVAILABLE",
        (
            "Workspace Connector source is unavailable or has been revoked; "
            f"ask the user to approve it again: {connector_id}"
        ),
        connector_id=connector_id,
    )


def _safe_resolve_connector_path(
    raw_path: str,
    *,
    context: dict | None,
    write: bool,
) -> str | None:
    request = _connector_request(raw_path)
    if request is None:
        return None

    connector_id, relative_path = request
    mount = _connector_mount_for(context, connector_id)
    source = _connector_source_for(context, connector_id)
    if int(mount.get("generation", 0)) != int(source.get("generation", -1)):
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_GENERATION_MISMATCH",
            (
                "Workspace Connector generation mismatch; "
                f"ask the user to approve it again: {connector_id}"
            ),
            connector_id=connector_id,
        )
    mode = str(source.get("mode") or mount.get("mode") or "")
    if write and mode != "read_write":
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_READ_ONLY",
            f"Workspace Connector is read-only and cannot be written: {connector_id}",
            connector_id=connector_id,
        )
    host_path = source.get("host_path")
    if not isinstance(host_path, str) or not host_path.strip():
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_SOURCE_UNAVAILABLE",
            (
                "Workspace Connector source is unavailable or has been revoked; "
                f"ask the user to approve it again: {connector_id}"
            ),
            connector_id=connector_id,
        )
    allowed = os.path.realpath(host_path)
    requested = relative_path.lstrip("/\\")
    resolved = os.path.realpath(os.path.join(allowed, requested))
    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_PATH_ESCAPE",
            f"Workspace Connector path is outside the approved mount: {connector_id}",
            connector_id=connector_id,
        )
    return resolved


def _raise_connector_path_error(raw_path: str, exc: OSError) -> None:
    request = _connector_request(raw_path)
    connector_id = request[0] if request else None
    if isinstance(exc, FileNotFoundError):
        raise WorkspaceConnectorMountError(
            "WORKSPACE_CONNECTOR_PATH_NOT_FOUND",
            (
                "Workspace Connector path was not found; check the connector-relative "
                f"path or ask the user to re-approve it: {connector_id or 'unknown'}"
            ),
            connector_id=connector_id,
        ) from exc
    raise WorkspaceConnectorMountError(
        "WORKSPACE_CONNECTOR_PATH_UNAVAILABLE",
        (
            "Workspace Connector path is unavailable; check access or ask the user "
            f"to re-approve it: {connector_id or 'unknown'}"
        ),
        connector_id=connector_id,
    ) from exc


FILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read a UTF-8 text file from the agent workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace file path"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write UTF-8 text content to a file in the agent workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace file path"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_list",
            "description": "List files in an agent workspace directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace directory path",
                    },
                },
                "required": ["path"],
            },
        },
    },
]


async def execute(tool_name: str, args: dict, context: dict | None = None) -> str | ToolExecutionResult:
    """Execute a workspace file operation."""
    raw_path = args.get("path", ".")
    connector_path = _safe_resolve_connector_path(
        raw_path,
        context=context,
        write=tool_name == "file_write",
    )
    if connector_path is None:
        workspace_base = _workspace_base(context)
        _ensure_workspace(workspace_base)
        path = _safe_resolve(raw_path, base=workspace_base)
    else:
        workspace_base = None
        path = connector_path

    if tool_name == "file_read":
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read(_MAX_READ_BYTES + 1)
        except OSError as exc:
            if connector_path is not None:
                _raise_connector_path_error(raw_path, exc)
            raise
        if len(content) > _MAX_READ_BYTES:
            return content[:_MAX_READ_BYTES] + "\n\n[truncated...]"
        return content

    if tool_name == "file_write":
        content = args["content"]
        before_content = None
        try:
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8") as existing:
                        before_content = existing.read()
                except UnicodeDecodeError:
                    before_content = None
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            if connector_path is not None:
                _raise_connector_path_error(raw_path, exc)
            raise
        rel_path = (
            raw_path.lstrip("/")
            if workspace_base is None
            else os.path.relpath(path, os.path.realpath(workspace_base))
        )
        artifacts = await capture_file_write_artifact(
            tenant_id=(context or {}).get("tenant_id"),
            conversation_id=(context or {}).get("conversation_id"),
            user_id=(context or {}).get("user_id"),
            run_id=(context or {}).get("run_id"),
            tool_call_id=(context or {}).get("tool_call_id"),
            workspace_path=rel_path,
            before_content=before_content,
            after_content=content,
        )
        result = f"Written {len(content)} bytes to workspace:{rel_path}"
        if artifacts:
            return ToolExecutionResult(content=result, artifacts=artifacts)
        return result

    if tool_name == "file_list":
        try:
            items = sorted(os.listdir(path))
        except OSError as exc:
            if connector_path is not None:
                _raise_connector_path_error(raw_path, exc)
            raise
        if not items:
            return "[empty]"
        return "\n".join(items)

    raise ValueError(f"Unknown file tool: {tool_name}")
