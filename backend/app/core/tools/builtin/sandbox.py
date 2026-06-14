"""Builtin sandbox tool: shell_exec.

Executes a shell command inside an isolated sandbox container managed by
the SandboxManager (sandbox-proxy).
"""

import json

from app.core.sandbox.manager import SandboxManager

SHELL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "shell_exec",
            "description": "Execute a shell command in an isolated sandbox container",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                },
                "required": ["command"],
            },
        },
    },
]


async def execute(tool_name: str, args: dict, sandbox_manager: SandboxManager) -> str:
    """Execute a shell command in the sandbox.

    Args:
        tool_name: Must be ``"shell_exec"``.
        args: Dictionary with ``command`` key.
        sandbox_manager: The application-wide SandboxManager instance.

    Returns:
        Combined stdout + stderr output from the sandbox.

    Raises:
        ValueError: If *tool_name* is not ``shell_exec``.
        RuntimeError: If sandbox execution fails.
    """
    if tool_name != "shell_exec":
        raise ValueError(f"Unknown sandbox tool: {tool_name}")

    command = args["command"]
    wrapped_script = (
        "import subprocess\n"
        "command = "
        f"{json.dumps(command)}\n"
        "result = subprocess.run(command, shell=True, capture_output=True, text=True)\n"
        "if result.stdout:\n"
        "    print(result.stdout, end='')\n"
        "if result.stderr:\n"
        "    print(result.stderr, end='')\n"
    )
    cid = await sandbox_manager.allocate()
    try:
        output_parts: list[str] = []
        async for event in sandbox_manager.execute(cid, script=wrapped_script, timeout=30):
            if event["type"] == "error":
                output_parts.append(f"[ERROR] {event['data']}")
            elif event["type"] in ("stdout", "stderr"):
                output_parts.append(event["data"])
            # "done" events carry no data
        return "\n".join(output_parts)
    finally:
        await sandbox_manager.recycle(cid)
