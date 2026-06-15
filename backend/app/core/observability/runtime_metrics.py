"""Small in-process counters and file-backed eval summaries for system metrics."""

from __future__ import annotations

import json
import threading
from collections import Counter
from pathlib import Path

_COUNTERS: Counter[str] = Counter()
_LOCK = threading.Lock()


def increment_runtime_metric(name: str, amount: int = 1) -> None:
    """Increment a secret-free runtime counter."""
    if amount <= 0:
        return
    with _LOCK:
        _COUNTERS[name] += amount


def get_runtime_metric_snapshot() -> dict[str, int]:
    """Return a copy of runtime counters for metrics exposition."""
    with _LOCK:
        return dict(_COUNTERS)


def reset_runtime_metrics() -> None:
    """Clear counters for isolated tests."""
    with _LOCK:
        _COUNTERS.clear()


def summarize_eval_outcomes(results_dir: str | Path | None = None) -> dict[str, int]:
    """Summarize eval result files without exposing prompts or model responses."""
    base = (
        Path(results_dir)
        if results_dir is not None
        else Path(__file__).resolve().parents[3] / "tests" / "eval" / "results"
    )
    summary = {"pass": 0, "fail": 0, "error": 0}
    if not base.exists():
        return summary

    for result_file in base.glob("*_results.json"):
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        result_summary = payload.get("summary") or {}
        for key in summary:
            summary[key] += int(result_summary.get(key, 0) or 0)
    return summary
