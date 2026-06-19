"""Capability orchestration seams for conversation/runtime callers."""

from __future__ import annotations

from typing import Any

from app.core.capabilities.policy import (
    PolicyDecision,
    evaluate_worker_policy,
    require_worker_tool_policy,
    unpack_confirmation_args,
)
from app.models.worker import Worker, WorkerVersion


def evaluate_stream_worker_policy(
    worker: Worker,
    version: WorkerVersion | None,
    *,
    input_payload: dict[str, Any],
) -> PolicyDecision:
    return evaluate_worker_policy(worker, version, input_payload=input_payload)


def unpack_confirmed_tool_args(args: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    return unpack_confirmation_args(args)


def require_confirmed_worker_tool_policy(
    tool_name: str,
    worker_context: dict[str, Any] | None,
    *,
    risk: str | None = None,
) -> None:
    require_worker_tool_policy(tool_name, worker_context, risk=risk, confirmed=True)
