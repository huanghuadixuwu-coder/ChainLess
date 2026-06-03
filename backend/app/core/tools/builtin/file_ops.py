"""Builtin file operation tools: file_read, file_write, file_list.

For now, file ops work on the local filesystem. Sandbox-based file ops
come in a later integration (P2.3).
"""

import os

# Allowed base directory for file operations — anything outside is rejected
_ALLOWED_BASE = os.environ.get("FILE_TOOLS_BASE_DIR", os.getcwd())


def _safe_resolve(path: str) -> str:
    """Resolve path and reject any traversal outside the allowed base directory."""
    allowed = os.path.realpath(_ALLOWED_BASE)
    resolved = os.path.realpath(os.path.join(allowed, path))
    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        raise ValueError(f"Access denied: '{path}' is outside the allowed directory")
    return resolved


FILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read the contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
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
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list"},
                },
                "required": ["path"],
            },
        },
    },
]


async def execute(tool_name: str, args: dict) -> str:
    """Execute a file operation tool.

    Args:
        tool_name: One of ``file_read``, ``file_write``, ``file_list``.
        args: Dictionary with tool-specific arguments.

    Returns:
        Result string (file content, confirmation message, or file listing).

    Raises:
        ValueError: If *tool_name* is not recognised.
        FileNotFoundError: If the target path does not exist (read / list).
        IOError: On read/write failure.
    """
    raw_path = args.get("path", ".")
    path = _safe_resolve(raw_path)

    if tool_name == "file_read":
        with open(path) as f:
            return f.read()

    elif tool_name == "file_write":
        content = args["content"]
        with open(path, "w") as f:
            f.write(content)
        return f"Written {len(content)} bytes to {path}"

    elif tool_name == "file_list":
        items = os.listdir(path)
        return "\n".join(items)

    raise ValueError(f"Unknown file tool: {tool_name}")
