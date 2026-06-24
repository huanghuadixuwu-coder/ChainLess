"""Focused file-tool workspace boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.tools.builtin import file_ops

pytestmark = pytest.mark.asyncio


async def test_file_read_uses_run_scoped_workspace_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_base = workspace_root / "runs" / "file-tools-run"
    run_base.mkdir(parents=True)
    (run_base / "input.txt").write_text("run scoped file tool input\n", encoding="utf-8")
    monkeypatch.setattr(file_ops, "_ALLOWED_BASE", str(workspace_root))

    result = await file_ops.execute(
        "file_read",
        {"path": "input.txt"},
        context={"workspace_base": str(run_base)},
    )

    assert result == "run scoped file tool input\n"


async def test_file_list_uses_active_run_workspace_not_stale_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_base = workspace_root / "runs" / "file-tools-isolated"
    run_base.mkdir(parents=True)
    (workspace_root / "stale-output.txt").write_text("old run\n", encoding="utf-8")
    (run_base / "current.txt").write_text("current run\n", encoding="utf-8")
    monkeypatch.setattr(file_ops, "_ALLOWED_BASE", str(workspace_root))

    result = await file_ops.execute(
        "file_list",
        {"path": "."},
        context={"workspace_base": str(run_base)},
    )

    assert "current.txt" in result
    assert "stale-output.txt" not in result


async def test_file_tools_reject_raw_host_workspace_base_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    host_secret = tmp_path / "host-secret"
    host_secret.mkdir()
    (host_secret / "private.txt").write_text("must not be readable\n", encoding="utf-8")
    monkeypatch.setattr(file_ops, "_ALLOWED_BASE", str(workspace_root))

    with pytest.raises(ValueError, match="Workspace Connector"):
        await file_ops.execute(
            "file_read",
            {"path": "private.txt"},
            context={"workspace_base": str(host_secret)},
        )


async def test_file_tools_reject_run_suffix_workspace_base_outside_allowed_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside_run = Path("/tmp/outside/runs/fake")
    outside_run.mkdir(parents=True)
    (outside_run / "private.txt").write_text("suffix bypass\n", encoding="utf-8")
    monkeypatch.setattr(file_ops, "_ALLOWED_BASE", str(workspace_root))

    with pytest.raises(ValueError, match="Workspace Connector"):
        await file_ops.execute(
            "file_read",
            {"path": "private.txt"},
            context={"workspace_base": str(outside_run)},
        )
