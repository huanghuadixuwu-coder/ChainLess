"""Code-as-Action executor.

Provides an executor that runs arbitrary Python scripts inside an isolated
sandbox container managed by ``SandboxManager``.
"""

MAX_SUB_AGENTS = 5
SUB_AGENT_TIMEOUT = 15

# Tool definition for the LLM function-calling API.
CODE_AS_ACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "code_as_action",
        "description": (
            "Write and execute Python code in an isolated sandbox container. "
            "Use this for any programming task, calculation, data processing, "
            "or script execution. The script is run in a fresh Python environment "
            "and stdout/stderr are captured."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "The complete Python script to execute",
                },
            },
            "required": ["script"],
        },
    },
}


async def execute_code_as_action(script: str, sandbox_manager) -> str:
    """Execute a Python *script* inside a sandbox container.

    Allocates a container from the pool, streams the script execution,
    collects output, and recycles the container.

    Args:
        script: Python source code to execute.
        sandbox_manager: The application-wide ``SandboxManager`` instance.

    Returns:
        Combined stdout/stderr output as a single string.
    """
    cid = await sandbox_manager.allocate()
    try:
        output_parts: list[str] = []
        async for chunk in sandbox_manager.execute(cid, script):
            if chunk.get("type") == "error":
                output_parts.append(f"[ERROR] {chunk.get('data', '')}")
            elif chunk.get("type") in ("stdout", "stderr"):
                output_parts.append(chunk.get("data", ""))
        return "\n".join(output_parts)
    finally:
        await sandbox_manager.recycle(cid)
