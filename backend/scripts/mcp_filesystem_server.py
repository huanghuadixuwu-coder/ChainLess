"""Minimal safe filesystem MCP server for W8 verification."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chainless-filesystem")
ROOT = Path.cwd().resolve()


def _safe_path(path: str) -> Path:
    candidate = (ROOT / path).resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError("path escapes MCP filesystem root")
    return candidate


@mcp.tool()
def list_directory(path: str = ".") -> list[str]:
    """List entries under the MCP filesystem root."""
    target = _safe_path(path)
    if not target.is_dir():
        raise ValueError("path is not a directory")
    return sorted(item.name for item in target.iterdir())


if __name__ == "__main__":
    mcp.run()
