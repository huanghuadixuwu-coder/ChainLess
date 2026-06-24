"""Small in-process counters and file-backed eval summaries for system metrics."""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from pathlib import Path

_COUNTERS: Counter[str] = Counter()
_LOCK = threading.Lock()
_SAFE_METRIC_RE = re.compile(r"^[a-z][a-z0-9_]{0,120}$")
ACQUISITION_METRIC_NAMES = frozenset(
    {
        "acquisition_analysis_jobs_enqueued",
        "acquisition_analysis_duplicate_enqueues",
        "acquisition_analysis_jobs_claimed",
        "acquisition_analysis_stale_reclaims",
        "acquisition_analysis_retries",
        "acquisition_analysis_succeeded",
        "acquisition_analysis_failures",
        "acquisition_analysis_timeouts",
        "acquisition_policy_blocks",
        "acquisition_rollback_failures",
        "acquisition_session_cleanups",
        "acquisition_credential_revocations",
        "acquisition_disabled_events",
    }
)


def increment_runtime_metric(name: str, amount: int = 1) -> None:
    """Increment a secret-free runtime counter."""
    _validate_metric_name(name)
    if amount <= 0:
        return
    with _LOCK:
        _COUNTERS[name] += amount


def increment_acquisition_metric(name: str, amount: int = 1) -> None:
    """Increment a whitelisted acquisition counter without runtime labels."""

    if name not in ACQUISITION_METRIC_NAMES:
        raise ValueError("unsupported acquisition metric")
    if amount <= 0:
        return
    with _LOCK:
        _COUNTERS[name] += amount


def _validate_metric_name(name: str) -> None:
    """Reject path-like or secret-looking metric names before they hit /metrics."""

    metric_name = str(name or "")
    lowered = metric_name.casefold()
    if not _SAFE_METRIC_RE.fullmatch(metric_name):
        raise ValueError("runtime metric names must be lower snake case")
    if any(token in lowered for token in ("secret", "token", "password", "credential", "prompt")):
        raise ValueError("runtime metric name may not contain sensitive tokens")
    if any(token in metric_name for token in ("\\", "/", ":", "~")):
        raise ValueError("runtime metric name may not contain path separators")


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
