"""Minimal MCP echo server for runtime verification."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chainless-echo")


@mcp.tool()
def echo(text: str) -> str:
    """Return the provided text."""
    return text


if __name__ == "__main__":
    mcp.run()
