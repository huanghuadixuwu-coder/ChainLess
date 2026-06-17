"""Bounded JSON/error helpers for durable capability-layer metadata."""

from __future__ import annotations

import json
from typing import Any

from app.api.contracts import validation_error

# PostgreSQL jsonb::text adds spaces around object/array punctuation.
# Use Python's default spaced JSON plus a margin below DB checks so public paths
# reject before persistence for both object-heavy and array-heavy payloads.
MAX_JSON_BYTES = 6144
MAX_JSON_DEPTH = 8
MAX_ERROR_MESSAGE_CHARS = 1024
TRUNCATION_SUFFIX = "...[truncated]"


def validate_bounded_json(value: Any, *, field: str) -> Any:
    """Reject oversized or deeply nested JSON before it reaches JSONB storage."""
    _check_depth(value, field=field, depth=0)
    try:
        encoded = json.dumps(value, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise validation_error(f"{field} must be JSON serializable") from exc
    if len(encoded) > MAX_JSON_BYTES:
        raise validation_error(f"{field} exceeds {MAX_JSON_BYTES} bytes")
    return value


def truncate_error_message(message: str | None) -> str | None:
    if message is None or len(message) <= MAX_ERROR_MESSAGE_CHARS:
        return message
    return message[: MAX_ERROR_MESSAGE_CHARS - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX


def _check_depth(value: Any, *, field: str, depth: int) -> None:
    if depth > MAX_JSON_DEPTH:
        raise validation_error(f"{field} exceeds JSON depth {MAX_JSON_DEPTH}")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise validation_error(f"{field} JSON object keys must be strings")
            _check_depth(item, field=field, depth=depth + 1)
        return
    if isinstance(value, list):
        for item in value:
            _check_depth(item, field=field, depth=depth + 1)
        return
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    raise validation_error(f"{field} contains unsupported JSON value")
