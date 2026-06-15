"""W8 layered instruction reload contract."""

from __future__ import annotations

from pathlib import Path

from app.core.memory.layered import load_layered_instructions


def _write_instruction(root: Path, tenant: str, layer: str, text: str) -> None:
    path = root / tenant / layer / "CLAUDE.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_layered_instructions_reload_file_changes_without_restart(tmp_path) -> None:
    _write_instruction(tmp_path, "tenant-a", "project", "old instruction")
    assert "old instruction" in load_layered_instructions(str(tmp_path), "tenant-a")

    _write_instruction(tmp_path, "tenant-a", "project", "new instruction")
    loaded = load_layered_instructions(str(tmp_path), "tenant-a")

    assert "new instruction" in loaded
    assert "old instruction" not in loaded


def test_layered_instructions_do_not_leak_across_tenants(tmp_path) -> None:
    _write_instruction(tmp_path, "tenant-a", "local", "tenant-a only")
    _write_instruction(tmp_path, "tenant-b", "local", "tenant-b only")

    loaded_a = load_layered_instructions(str(tmp_path), "tenant-a")
    loaded_b = load_layered_instructions(str(tmp_path), "tenant-b")

    assert "tenant-a only" in loaded_a
    assert "tenant-b only" not in loaded_a
    assert "tenant-b only" in loaded_b
    assert "tenant-a only" not in loaded_b
