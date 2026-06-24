"""Canonical Server-Sent Events helpers for API streams."""

from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from app.api.contracts import ErrorDetail, error_envelope


SSEEventName = Literal[
    "text",
    "tool_call",
    "tool_result",
    "sandbox",
    "sandbox_output",
    "confirmation_required",
    "worker_notice",
    "capability_candidate",
    "acquisition_gap",
    "acquisition_exploration",
    "acquisition_recommendation",
    "acquisition_approval_required",
    "acquisition_verification",
    "acquisition_activation",
    "acquisition_runtime_planning_issue",
    "acquisition_permission",
    "acquisition_browser_trace",
    "done",
    "error",
    "heartbeat",
]


class SSEEvent(TypedDict, total=False):
    event: SSEEventName
    data: dict[str, Any]
    id: str


def sse_event(
    event: SSEEventName,
    data: dict[str, Any] | None = None,
    *,
    event_id: str | None = None,
) -> str:
    """Format one canonical SSE frame."""
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data or {}, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def sse_error(
    code: str,
    message: str,
    detail: ErrorDetail = None,
    *,
    event_id: str | None = None,
) -> str:
    """Format an SSE error frame using the HTTP API error envelope."""
    return sse_event("error", error_envelope(code, message, detail), event_id=event_id)
