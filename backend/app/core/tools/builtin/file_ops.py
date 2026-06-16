"""Builtin file operation tools for the agent workspace."""

import os

from app.core.artifacts import ToolExecutionResult, capture_file_write_artifact

_ALLOWED_BASE = os.environ.get("FILE_TOOLS_BASE_DIR", "/workspace")
_MAX_READ_BYTES = int(os.environ.get("FILE_TOOLS_MAX_READ_BYTES", "20000"))


def _workspace_base(context: dict | None = None) -> str:
    candidate = (context or {}).get("workspace_base")
    if isinstance(candidate, str) and candidate.strip():
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
    workspace_base = _workspace_base(context)
    _ensure_workspace(workspace_base)
    raw_path = args.get("path", ".")
    path = _safe_resolve(raw_path, base=workspace_base)

    if tool_name == "file_read":
        with open(path, encoding="utf-8") as f:
            content = f.read(_MAX_READ_BYTES + 1)
        if len(content) > _MAX_READ_BYTES:
            return content[:_MAX_READ_BYTES] + "\n\n[truncated...]"
        return content

    if tool_name == "file_write":
        content = args["content"]
        before_content = None
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as existing:
                    before_content = existing.read()
            except UnicodeDecodeError:
                before_content = None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        rel_path = os.path.relpath(path, os.path.realpath(workspace_base))
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
        items = sorted(os.listdir(path))
        if not items:
            return "[empty]"
        return "\n".join(items)

    raise ValueError(f"Unknown file tool: {tool_name}")
