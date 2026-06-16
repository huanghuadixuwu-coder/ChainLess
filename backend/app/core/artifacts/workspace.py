"""Run-scoped workspace materialization for artifact-backed inputs."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.artifacts.service import (
    ARTIFACT_STATE_AVAILABLE,
    artifact_download_filename,
    read_artifact_bytes,
)
from app.models.artifact import Artifact

_DEFAULT_WORKSPACE_ROOT = os.environ.get("FILE_TOOLS_BASE_DIR", "/workspace")


@dataclass(frozen=True)
class RunWorkspace:
    """Materialized file view for one agent run."""

    run_id: str
    base_path: Path
    input_paths: dict[str, str]

    @property
    def summary_for_prompt(self) -> str:
        if not self.input_paths:
            return "No uploaded files are available in this run workspace."
        lines = [
            "Uploaded files are available to file tools at these workspace paths:",
        ]
        for artifact_id, path in sorted(self.input_paths.items()):
            lines.append(f"- artifact {artifact_id}: {path}")
        return "\n".join(lines)


async def prepare_run_workspace(
    *,
    run_id: str,
    artifacts: list[Artifact],
    root: str | Path | None = None,
) -> RunWorkspace:
    """Copy selected artifact bytes into a clean, run-scoped workspace."""
    workspace_root = _safe_workspace_root(root)
    safe_run_id = _safe_segment(run_id)
    base_path = workspace_root / "runs" / safe_run_id
    if base_path.exists():
        shutil.rmtree(base_path)
    input_root = base_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)

    input_paths: dict[str, str] = {}
    for artifact in artifacts:
        if artifact.state != ARTIFACT_STATE_AVAILABLE:
            raise ValueError(f"Attachment artifact {artifact.id} is {artifact.state}")
        artifact_id = str(artifact.id)
        filename = artifact_download_filename(artifact)
        relative_path = Path("input") / artifact_id / filename
        destination = base_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(await read_artifact_bytes(artifact, content_kind="content"))
        input_paths[artifact_id] = relative_path.as_posix()

    return RunWorkspace(
        run_id=safe_run_id,
        base_path=base_path,
        input_paths=input_paths,
    )


def cleanup_run_workspace(
    *,
    run_id: str,
    root: str | Path | None = None,
) -> None:
    """Delete only one run workspace directory."""
    workspace_root = _safe_workspace_root(root)
    target = (workspace_root / "runs" / _safe_segment(run_id)).resolve()
    runs_root = (workspace_root / "runs").resolve()
    if target != runs_root and runs_root in target.parents:
        shutil.rmtree(target, ignore_errors=True)


def _safe_workspace_root(root: str | Path | None) -> Path:
    workspace_root = Path(root or _DEFAULT_WORKSPACE_ROOT)
    if not workspace_root.is_absolute():
        workspace_root = workspace_root.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    return workspace_root.resolve()


def _safe_segment(value: str) -> str:
    safe = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in str(value)
    ).strip("-_")
    if not safe:
        raise ValueError("Run id cannot be empty")
    return safe[:160]
