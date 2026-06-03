"""Load hierarchical instruction (CLAUDE.md) files.

Layer order (lowest to highest precedence):
    enterprise -> user -> project -> rules -> local

Higher layers override lower ones — local values take precedence over everything.
"""

from pathlib import Path

LAYER_ORDER = ["enterprise", "user", "project", "rules", "local"]


def load_layered_instructions(base_path: str, tenant_id: str) -> str:
    """Merge hierarchical CLAUDE.md files from *base_path* / *tenant_id* / *layer*.

    Layers are loaded in ascending precedence order so that later files
    (e.g. *local*) override earlier ones (e.g. *enterprise*).
    Returns an empty string when no files exist.
    """
    parts: list[str] = []
    for layer in LAYER_ORDER:
        path = Path(base_path) / tenant_id / layer / "CLAUDE.md"
        if path.exists() and path.is_file():
            parts.append(f"<!-- {layer} -->\n{path.read_text()}")
    return "\n\n".join(parts)
