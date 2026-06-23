"""Tiny MCP server installed only in the isolated mcp-runtime image."""

from __future__ import annotations

import time

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chainless-runtime-echo")


@mcp.tool()
def echo(text: str) -> str:
    """Return the provided text from inside the mcp-runtime image."""
    return text


@mcp.tool()
def big_echo(text: str, repeat: int = 1) -> str:
    """Return repeated text for output-limit verification."""
    return text * repeat


@mcp.tool()
def sleep_echo(text: str, seconds: float = 1.0) -> str:
    """Sleep before returning text for timeout verification."""
    time.sleep(seconds)
    return text


if __name__ == "__main__":
    mcp.run()
