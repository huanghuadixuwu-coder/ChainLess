"""MEMORY.md index maintenance.

The index file serves as a human-readable registry of all memories for a
given tenant.  Each entry links to a per-memory markdown file.
"""

from pathlib import Path


async def update_index(
    base_path: str,
    tenant_id: str,
    memory_id: str,
    name: str,
    description: str,
    tags: list[str],
) -> None:
    """Append a memory entry to the tenant's MEMORY.md index.

    Creates the file if it does not exist yet.
    """
    index_path = Path(base_path) / tenant_id / "MEMORY.md"
    if not index_path.exists():
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("# Memory Index\n\n")

    tag_str = " ".join(f"#{t}" for t in tags)
    line = f"- [{name}](memory/{memory_id}.md) — {description} {tag_str}\n"
    with open(index_path, "a") as f:
        f.write(line)
