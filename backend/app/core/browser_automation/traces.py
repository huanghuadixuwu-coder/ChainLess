"""Trace artifact handling for browser automation runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


DEFAULT_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "cookies",
        "password",
        "secret",
        "set-cookie",
        "screenshot",
        "screenshot_bytes",
        "token",
    }
)
SECRET_LIKE_PATTERN = re.compile(r"(bearer\s+)[A-Za-z0-9._~+/=-]+|([?&](?:token|key|secret|password)=)[^&\s]+", re.IGNORECASE)
ACTION_INPUT_TYPES = frozenset({"fill", "type"})
ACTION_INPUT_VALUE_KEYS = frozenset({"text", "value"})


@dataclass
class TraceRedactionSummary:
    """Trace redaction counters for audit evidence."""

    sensitive_values: int = 0
    screenshots: int = 0
    cookies: int = 0


class BrowserAutomationTraceRecorder:
    """Collects redacted frontend-visible evidence for one browser run."""

    def __init__(
        self,
        *,
        max_trace_bytes: int,
        redaction_policy: Mapping[str, Any] | None = None,
        trace_retention_days: int = 1,
    ) -> None:
        self.max_trace_bytes = max_trace_bytes
        self.redaction_policy = dict(redaction_policy or {})
        self.trace_retention_days = trace_retention_days
        self.events: list[dict[str, Any]] = []
        self.redaction = TraceRedactionSummary()
        self.truncated = False

    def record_event(self, event_type: str, payload: Mapping[str, Any] | None = None) -> None:
        redacted_payload, summary = redact_trace_value(payload or {}, policy=self.redaction_policy)
        self.redaction.sensitive_values += summary.sensitive_values
        self.redaction.screenshots += summary.screenshots
        self.redaction.cookies += summary.cookies
        self.events.append(
            {
                "type": event_type,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "payload": redacted_payload,
            }
        )
        self._trim_to_budget()

    def artifact(self, *, run_id: str) -> dict[str, Any]:
        payload = {
            "artifact_type": "browser_automation_trace",
            "schema_version": "browser_automation_trace.v1",
            "run_id": run_id,
            "events": self.events,
            "redaction": {
                "sensitive_values": self.redaction.sensitive_values,
                "screenshots": self.redaction.screenshots,
                "cookies": self.redaction.cookies,
            },
            "truncated": self.truncated,
            "retention_days": self.trace_retention_days,
        }
        payload["byte_size"] = len(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        return payload

    def _trim_to_budget(self) -> None:
        while self.events and _encoded_size(self.events) > self.max_trace_bytes:
            self.events.pop(0)
            self.truncated = True


def redact_trace_value(
    value: Any,
    *,
    policy: Mapping[str, Any] | None = None,
    key_hint: str | None = None,
) -> tuple[Any, TraceRedactionSummary]:
    """Return a redacted trace-safe value and redaction counters."""

    policy_keys = {
        str(key).lower()
        for key in (policy or {}).get("sensitive_keys", [])
        if str(key).strip()
    }
    sensitive_keys = DEFAULT_SENSITIVE_KEYS | policy_keys
    summary = TraceRedactionSummary()

    if key_hint and _is_sensitive_key(key_hint, sensitive_keys):
        summary.sensitive_values += 1
        lowered = key_hint.lower()
        if "screenshot" in lowered:
            summary.screenshots += 1
            return _redacted_binary_marker(value, kind="screenshot"), summary
        if "cookie" in lowered:
            summary.cookies += 1
        return "[REDACTED]", summary

    if isinstance(value, Mapping):
        action_kind = _action_kind(value)
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if (
                action_kind in ACTION_INPUT_TYPES
                and key_text.lower() in ACTION_INPUT_VALUE_KEYS
            ):
                summary.sensitive_values += 1
                redacted[key_text] = "[REDACTED]"
                continue
            safe_item, child_summary = redact_trace_value(item, policy=policy, key_hint=str(key))
            _merge(summary, child_summary)
            redacted[key_text] = safe_item
        return redacted, summary
    if isinstance(value, list):
        output = []
        for item in value:
            safe_item, child_summary = redact_trace_value(item, policy=policy)
            _merge(summary, child_summary)
            output.append(safe_item)
        return output, summary
    if isinstance(value, bytes):
        summary.sensitive_values += 1
        return _redacted_binary_marker(value, kind="bytes"), summary
    if isinstance(value, str):
        redacted = SECRET_LIKE_PATTERN.sub(lambda match: (match.group(1) or match.group(2) or "") + "[REDACTED]", value)
        if redacted != value:
            summary.sensitive_values += 1
        return redacted, summary
    return value, summary


def _is_sensitive_key(key: str, sensitive_keys: set[str]) -> bool:
    lowered = key.lower()
    return lowered in sensitive_keys or any(token in lowered for token in sensitive_keys)


def _action_kind(value: Mapping[str, Any]) -> str:
    return str(value.get("type") or value.get("kind") or value.get("action") or "").strip().lower()


def _redacted_binary_marker(value: Any, *, kind: str) -> dict[str, Any]:
    if isinstance(value, bytes):
        data = value
    else:
        data = str(value).encode("utf-8", errors="replace")
    return {
        "redacted": True,
        "kind": kind,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _merge(target: TraceRedactionSummary, source: TraceRedactionSummary) -> None:
    target.sensitive_values += source.sensitive_values
    target.screenshots += source.screenshots
    target.cookies += source.cookies


def _encoded_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8"))
