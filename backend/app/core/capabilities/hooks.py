"""Internal capability lifecycle hooks.

W6 hooks are intentionally observability-only. They record bounded internal
events and never execute user-authored code or override policy decisions.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

HOOK_NAMES = {
    "before_worker_match",
    "before_worker_run",
    "after_worker_run",
    "before_tool_call",
    "after_tool_call",
    "on_worker_failure",
    "on_capability_candidate_created",
}
MAX_HOOK_EVENTS = 200
MAX_PAYLOAD_DEPTH = 4
MAX_STRING_CHARS = 500
SECRET_MARKERS = ("secret", "token", "password", "api_key", "apikey", "authorization")

_HOOK_EVENTS: deque[dict[str, Any]] = deque(maxlen=MAX_HOOK_EVENTS)


async def emit_capability_hook(
    name: str,
    payload: dict[str, Any] | None = None,
    *,
    policy_action: str | None = None,
) -> None:
    """Record one bounded hook event.

    Unknown names are ignored rather than becoming a dynamic user-defined hook
    surface. Hooks are append-only telemetry; callers must not branch on return
    values because no hook can allow a denied policy decision.
    """

    if name not in HOOK_NAMES:
        return
    event = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "policy_action": policy_action,
        "payload": _sanitize(payload or {}),
    }
    _HOOK_EVENTS.append(event)


def get_hook_events() -> list[dict[str, Any]]:
    """Return recorded hook events for tests and future internal diagnostics."""

    return list(_HOOK_EVENTS)


def clear_hook_events() -> None:
    """Clear the in-process hook event buffer."""

    _HOOK_EVENTS.clear()


def _sanitize(value: Any, *, depth: int = 0, key: str | None = None) -> Any:
    if key and any(marker in key.casefold() for marker in SECRET_MARKERS):
        return "[redacted]"
    if depth >= MAX_PAYLOAD_DEPTH:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(item_key)[:MAX_STRING_CHARS]: _sanitize(item_value, depth=depth + 1, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item, depth=depth + 1) for item in value[:25]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
            return value[: MAX_STRING_CHARS - 15] + " [truncated]"
        return value
    return str(value)[:MAX_STRING_CHARS]
